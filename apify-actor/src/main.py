from typing import Any

from apify import Actor
from pydantic import ValidationError

from seo_analyzer.config import Settings

from .audit import ActorInput, RecordingAnalyzer, RunSummary, run_audit


class ApifySink:
    def affordable(self, event: str) -> int | None:
        return Actor.get_charging_manager().calculate_max_event_charge_count_within_limit(event)

    async def push(self, items: list[dict[str, Any]], event: str | None) -> None:
        await Actor.push_data(items, event)
        for item in items:
            Actor.log.info(f"{item['type']}: {item['url']}")


def status_message(summary: RunSummary) -> str:
    message = f"Pages audited: {summary.audited}, URLs failed: {summary.failed}"
    if summary.stopped_by_budget:
        message += ", stopped at the maximum charge set for this run"
    return message


async def main() -> None:
    async with Actor:
        try:
            actor_input = ActorInput.model_validate(await Actor.get_input() or {})
        except ValidationError as exc:
            error = exc.errors()[0]
            field = ".".join(str(part) for part in error["loc"]) or "input"
            await Actor.fail(status_message=f"Invalid input, {field}: {error['msg']}")
            return
        analyzer = RecordingAnalyzer(Settings(_env_file=None))
        try:
            summary = await run_audit(actor_input, analyzer, ApifySink())
        finally:
            await analyzer.close()
        await Actor.set_status_message(status_message(summary), is_terminal=True)
