"""Tests for the cross-run seen-items dedup registry."""

import json
from datetime import date, datetime, timedelta, timezone

from src.models import ContentItem, SourceType
from src.services.seen_registry import SeenRegistry


def _item(item_id: str, title: str = "Some title") -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.GITHUB,
        title=title,
        url=f"https://example.com/{item_id}",
        content="content",
        published_at=datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc),
    )


def _registry(tmp_path, data: dict | None = None) -> SeenRegistry:
    path = tmp_path / "seen-items.json"
    if data is not None:
        path.write_text(
            json.dumps({"version": 1, "items": data}, ensure_ascii=False),
            encoding="utf-8",
        )
    return SeenRegistry(path)


def test_missing_file_starts_empty(tmp_path):
    registry = _registry(tmp_path)

    fresh, repeats = registry.filter_out_seen([_item("a")], window_days=7)

    assert fresh and not repeats
    assert not (tmp_path / "seen-items.json").exists()


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "seen-items.json"
    path.write_text("not json at all{", encoding="utf-8")

    registry = SeenRegistry(path)
    fresh, repeats = registry.filter_out_seen([_item("a")], window_days=7)

    assert fresh and not repeats


def test_window_boundary(tmp_path):
    today = date(2026, 10, 28)
    # last_seen 7 days back is still inside the window (>= today - 7);
    # 8 days back is outside.
    registry = _registry(
        tmp_path,
        data={
            "inside:1": {"last_seen": (today - timedelta(days=7)).isoformat()},
            "outside:1": {"last_seen": (today - timedelta(days=8)).isoformat()},
        },
    )

    items = [_item("inside:1"), _item("outside:1")]
    fresh, repeats = registry.filter_out_seen(items, window_days=7, today=today)

    assert [i.id for i in repeats] == ["inside:1"]
    assert [i.id for i in fresh] == ["outside:1"]


def test_record_round_trips_and_keeps_first_title(tmp_path):
    path = tmp_path / "seen-items.json"
    registry = SeenRegistry(path)
    today = date(2026, 10, 28)

    registry.record([_item("github:repo:owner/name", title="first title")], today=today)
    assert len(registry._entries) == 1

    reloaded = SeenRegistry(path)
    fresh, repeats = reloaded.filter_out_seen(
        [_item("github:repo:owner/name", title="drifted title")],
        window_days=7,
        today=today,
    )
    assert not fresh and len(repeats) == 1
    assert reloaded._entries["github:repo:owner/name"]["title"] == "first title"


def test_record_renews_last_seen(tmp_path):
    today = date(2026, 10, 28)
    registry = _registry(
        tmp_path,
        data={
            "github:repo:owner/x": {
                "last_seen": (today - timedelta(days=5)).isoformat(),
                "title": "old point",
            }
        },
    )

    registry.record([_item("github:repo:owner/x")], today=today)

    assert registry._entries["github:repo:owner/x"]["last_seen"] == today.isoformat()
    assert registry._entries["github:repo:owner/x"]["title"] == "old point"


def test_record_prunes_stale_entries(tmp_path):
    today = date(2026, 10, 28)
    stale_date = (today - timedelta(days=30)).isoformat()
    registry = _registry(
        tmp_path,
        data={
            "stale:1": {"last_seen": stale_date},
            "fresh:1": {"last_seen": today.isoformat()},
        },
    )

    registry.record([_item("fresh:2")], today=today, prune_days=7)

    assert set(registry._entries) == {"fresh:1", "fresh:2"}


def test_load_ignores_unexpected_layout(tmp_path):
    path = tmp_path / "seen-items.json"
    path.write_text(
        json.dumps({"version": 2, "items": {"a": {"last_seen": "2026-10-28"}}}),
        encoding="utf-8",
    )

    registry = SeenRegistry(path)
    fresh, repeats = registry.filter_out_seen([_item("a")], window_days=7)

    assert fresh and not repeats


def test_filter_handles_unparseable_dates(tmp_path):
    registry = _registry(tmp_path, data={"weird:1": {"last_seen": "not-a-date"}})

    fresh, repeats = registry.filter_out_seen([_item("weird:1")], window_days=7)

    assert fresh and not repeats
