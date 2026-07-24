import asyncio
from dataclasses import dataclass

from seo_analyzer.cache import AsyncTTLCache
from seo_analyzer.config import Settings
from seo_analyzer.fetcher import SafeFetcher
from seo_analyzer.models import PageAnalysis
from seo_analyzer.parser import ParsedPage, parse_page
from seo_analyzer.performance import PageSpeedClient
from seo_analyzer.scoring import apply_scoring
from seo_analyzer.utils import normalize_url, utc_now_iso


@dataclass(slots=True)
class AnalysisArtifact:
    report: PageAnalysis
    parsed: ParsedPage


class Analyzer:
    def __init__(
        self,
        settings: Settings,
        *,
        fetcher: SafeFetcher | None = None,
        pagespeed: PageSpeedClient | None = None,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher or SafeFetcher(settings)
        self.pagespeed = pagespeed or PageSpeedClient(settings)
        self.cache: AsyncTTLCache[tuple[str, bool, bool], AnalysisArtifact] = AsyncTTLCache(
            settings.cache_max_entries, settings.cache_ttl_seconds
        )
        self._inflight_lock = asyncio.Lock()
        self._inflight: dict[tuple[str, bool, bool], asyncio.Task[AnalysisArtifact]] = {}
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def close(self) -> None:
        await self.fetcher.close()
        await self.pagespeed.close()

    async def analyze(
        self,
        url: str,
        *,
        include_pagespeed: bool = False,
        include_subdomains: bool = False,
    ) -> PageAnalysis:
        artifact = await self.analyze_artifact(
            url,
            include_pagespeed=include_pagespeed,
            include_subdomains=include_subdomains,
        )
        return artifact.report

    async def analyze_artifact(
        self,
        url: str,
        *,
        include_pagespeed: bool = False,
        include_subdomains: bool = False,
    ) -> AnalysisArtifact:
        parsed_url, _ = await self.fetcher.validate(url)
        key = (
            normalize_url(str(parsed_url), keep_query=True),
            include_pagespeed,
            include_subdomains,
        )
        cached = await self.cache.get(key)
        if cached is not None:
            return cached

        async with self._inflight_lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._analyze_uncached(
                        key[0],
                        include_pagespeed=include_pagespeed,
                        include_subdomains=include_subdomains,
                    )
                )
                self._inflight[key] = task

                def clean_up(completed: asyncio.Task[AnalysisArtifact]) -> None:
                    cleanup_task = asyncio.create_task(self._remove_inflight(key, completed))
                    self._cleanup_tasks.add(cleanup_task)
                    cleanup_task.add_done_callback(self._cleanup_tasks.discard)

                task.add_done_callback(clean_up)
        try:
            artifact = await asyncio.shield(task)
        finally:
            # The task callback also cleans up when every waiting client is
            # cancelled before the shared analysis completes.
            if task.done():
                await self._remove_inflight(key, task)
        await self.cache.set(key, artifact)
        return artifact

    async def _remove_inflight(
        self, key: tuple[str, bool, bool], task: asyncio.Task[AnalysisArtifact]
    ) -> None:
        owns_entry = False
        async with self._inflight_lock:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)
                owns_entry = True
        if owns_entry and not task.cancelled() and task.exception() is None:
            # Preserve useful completed work even if the original HTTP client
            # disconnected while the shielded upstream request was running.
            await self.cache.set(key, task.result())

    async def _analyze_uncached(
        self,
        url: str,
        *,
        include_pagespeed: bool,
        include_subdomains: bool,
    ) -> AnalysisArtifact:
        fetch = await self.fetcher.fetch(url)
        parsed = parse_page(fetch, include_subdomains=include_subdomains)
        issues, score, recommendations = apply_scoring(
            parsed, requested_url=fetch.requested_url, final_url=fetch.final_url
        )
        if include_pagespeed:
            parsed.sections["performance"] = await self.pagespeed.analyze(fetch.final_url)
        limitations = [
            "The analyzer evaluates fetched HTML and headers; it does not execute page JavaScript unless optional PageSpeed analysis is enabled.",
            "Scores are transparent diagnostics, not predictions of Google position, traffic, revenue, or rich-result eligibility.",
            "A single fetch cannot detect duplicate pages, orphan pages, or broken targets; use the site-audit endpoint for sampled crawl evidence.",
            "Content usefulness, factual accuracy, visual hierarchy, accessibility, and conversion impact require human and first-party-data validation.",
        ]
        report = PageAnalysis(
            analyzed_at=utc_now_iso(),
            requested_url=fetch.requested_url,
            final_url=fetch.final_url,
            score=score,
            issues=issues,
            recommendations=recommendations,
            limitations=limitations,
            **parsed.sections,
        )
        return AnalysisArtifact(report=report, parsed=parsed)
