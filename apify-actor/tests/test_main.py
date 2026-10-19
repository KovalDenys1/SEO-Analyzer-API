import logging
from typing import Any

import pytest
from src import main
from src.main import ApifySink


class FakeActor:
    """Mirrors the Apify SDK 4 `Actor.push_data` signature, where the event is keyword-only."""

    log = logging.getLogger("fake-actor")

    def __init__(self) -> None:
        self.pushed: list[tuple[list[dict[str, Any]], str | None]] = []

    async def push_data(
        self, data: list[dict[str, Any]], *, charged_event_name: str | None = None
    ) -> None:
        self.pushed.append((data, charged_event_name))


@pytest.fixture
def actor(monkeypatch: pytest.MonkeyPatch) -> FakeActor:
    fake = FakeActor()
    monkeypatch.setattr(main, "Actor", fake)
    return fake


async def test_sink_pushes_items_and_charges_their_event(actor: FakeActor) -> None:
    items = [{"type": "page", "url": "https://example.com/"}]

    await ApifySink().push(items, "page-audited")

    assert actor.pushed == [(items, "page-audited")]


async def test_sink_pushes_free_items_without_an_event(actor: FakeActor) -> None:
    items = [{"type": "error", "url": "https://no-such-host.invalid"}]

    await ApifySink().push(items, None)

    assert actor.pushed == [(items, None)]
