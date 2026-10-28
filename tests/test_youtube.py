from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.models import YouTubeChannelConfig, YouTubeConfig
from src.scrapers.youtube import YouTubeScraper


def _entries() -> list[dict]:
    return [
        {
            "id": "aaaaaaaaaaa",
            "title": "Cool AI demo",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "view_count": 1000,
            "duration": 600,
        },
        {
            "id": "bbbbbbbbbbb",
            "title": "Even cooler AI demo",
            "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            "view_count": 50_000,
            "duration": 1200,
        },
    ]


def _scraper(monkeypatch, config: YouTubeConfig, captured: dict | None = None) -> YouTubeScraper:
    def fake_list_videos(url: str, limit: int) -> list[dict]:
        if captured is not None:
            captured["url"] = url
            captured["limit"] = limit
        return _entries()

    monkeypatch.setattr(YouTubeScraper, "_list_videos", staticmethod(fake_list_videos))
    return YouTubeScraper(config)


def _fetch(scraper: YouTubeScraper):
    since = datetime.now(timezone.utc)
    return asyncio.run(scraper.fetch(since))


def test_channel_url_normalization() -> None:
    assert YouTubeScraper._channel_url("@TwoMinutePapers") == (
        "https://www.youtube.com/@TwoMinutePapers/videos"
    )
    assert YouTubeScraper._channel_url("TwoMinutePapers") == (
        "https://www.youtube.com/@TwoMinutePapers/videos"
    )
    assert YouTubeScraper._channel_url("UC" + "a" * 22) == (
        f"https://www.youtube.com/channel/UC{'a' * 22}/videos"
    )
    assert YouTubeScraper._channel_url("https://www.youtube.com/@x") == (
        "https://www.youtube.com/@x/videos"
    )
    assert YouTubeScraper._channel_url("https://www.youtube.com/@x/videos") == (
        "https://www.youtube.com/@x/videos"
    )


def test_channel_label() -> None:
    assert YouTubeScraper._channel_label("@handle") == "handle"
    assert YouTubeScraper._channel_label("https://www.youtube.com/@handle/videos") == "handle"


def test_fetch_sorts_by_views(monkeypatch) -> None:
    captured: dict = {}
    config = YouTubeConfig(channels=[YouTubeChannelConfig(channel="@x")])
    scraper = _scraper(monkeypatch, config, captured)

    items = _fetch(scraper)

    assert [item.title for item in items] == ["Even cooler AI demo", "Cool AI demo"]
    assert items[0].metadata["view_count"] == 50_000
    assert items[0].metadata["channel"] == "x"
    assert str(items[0].url) == "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    assert captured["url"] == "https://www.youtube.com/@x/videos"
    assert captured["limit"] == 3


def test_per_channel_fetch_limit_overrides_default(monkeypatch) -> None:
    captured: dict = {}
    config = YouTubeConfig(
        fetch_limit=3,
        channels=[YouTubeChannelConfig(channel="@x", fetch_limit=7)],
    )
    scraper = _scraper(monkeypatch, config, captured)

    _fetch(scraper)

    assert captured["limit"] == 7


def test_max_items_and_min_views(monkeypatch) -> None:
    config = YouTubeConfig(
        channels=[YouTubeChannelConfig(channel="@x")],
        min_views=100,
        max_items=1,
    )
    scraper = _scraper(monkeypatch, config)

    items = _fetch(scraper)

    assert len(items) == 1
    assert items[0].metadata["view_count"] == 50_000


def test_duplicate_videos_across_channels_are_deduped(monkeypatch) -> None:
    config = YouTubeConfig(
        channels=[
            YouTubeChannelConfig(channel="@x"),
            YouTubeChannelConfig(channel="@y"),
        ]
    )
    scraper = _scraper(monkeypatch, config)

    items = _fetch(scraper)

    assert len(items) == 2


def test_disabled_source_returns_nothing(monkeypatch) -> None:
    config = YouTubeConfig(enabled=False, channels=[YouTubeChannelConfig(channel="@x")])
    scraper = _scraper(monkeypatch, config)

    assert _fetch(scraper) == []


def test_channel_failure_does_not_break_others(monkeypatch) -> None:
    def fake_list_videos(url: str, limit: int) -> list[dict]:
        if url.endswith("/@bad/videos"):
            raise RuntimeError("boom")
        return _entries()

    monkeypatch.setattr(YouTubeScraper, "_list_videos", staticmethod(fake_list_videos))
    config = YouTubeConfig(
        channels=[
            YouTubeChannelConfig(channel="@bad"),
            YouTubeChannelConfig(channel="@good"),
        ]
    )
    scraper = YouTubeScraper(config)

    items = _fetch(scraper)

    assert len(items) == 2


def test_keyword_search_uses_ytsearch_and_metadata(monkeypatch) -> None:
    captured: dict = {}

    def fake_list_videos(url: str, limit: int) -> list[dict]:
        captured["url"] = url
        captured["limit"] = limit
        return _entries()

    monkeypatch.setattr(YouTubeScraper, "_list_videos", staticmethod(fake_list_videos))
    config = YouTubeConfig(keywords=["GitHub"], search_fetch_limit=10)
    scraper = YouTubeScraper(config)

    items = _fetch(scraper)

    assert captured["url"] == "ytsearch10:GitHub"
    assert captured["limit"] == 10
    assert len(items) == 2
    assert items[0].author == "GitHub"
    assert items[0].metadata["search_query"] == "GitHub"


def test_github_related_items_are_boosted(monkeypatch) -> None:
    entries = [
        {"id": "low", "title": "Random video", "view_count": 90_000},
        {"id": "high", "title": "New GitHub tool released", "view_count": 500},
    ]

    monkeypatch.setattr(
        YouTubeScraper,
        "_list_videos",
        staticmethod(lambda url, limit: entries),
    )
    config = YouTubeConfig(channels=[YouTubeChannelConfig(channel="@x")])
    scraper = YouTubeScraper(config)

    items = _fetch(scraper)

    assert [item.id for item in items] == [
        "youtube:video:high",
        "youtube:video:low",
    ]
