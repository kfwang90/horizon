"""Tests for the Jekyll post helpers that feed the index page.

The front matter is emitted with the item list as JSON (a subset of YAML), so
the tests round-trip it through ``json`` instead of pulling in a YAML parser.
"""

import json
from datetime import datetime, timezone

from src.ai.summarizer import DailySummarizer
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentArtifact,
    ContentBlock,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.services.pages import post_front_matter, recent_items

PROFILE_NAMES = {
    "gh-trending": {"zh": "GitHub AI 开发工具", "en": "AI Dev Tools"},
    "ai-news": {"zh": "AI 热门新闻", "en": "AI News"},
}


def _make_item(idx: int, profile: str, title: str, score: float | str = 8.0):
    return ContentItem(
        id=f"github:item-{idx}",
        source_type=SourceType.GITHUB,
        title=title,
        url=f"https://example.com/items/{idx}",
        content="content",
        published_at=datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc),
        profile=profile,
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile=profile, method="source_override"
            ),
            analysis=ContentAnalysis(score=score, reason="test", summary="summary"),
            artifacts={
                language: ContentArtifact(
                    language=language,
                    title=f"{title} ({language})",
                    blocks=[
                        ContentBlock(
                            id="summary",
                            title="Summary",
                            content="summary",
                            primary=True,
                        )
                    ],
                )
                for language in ("en", "zh")
            },
        ),
    )


def _parse_front_matter(text: str) -> dict:
    """Read the emitted front matter back into ``{key: raw value}``."""
    lines = text.split("\n")
    assert lines[0] == "---"
    matter = {}
    for line in lines[1:]:
        if line == "---":
            break
        key, separator, value = line.partition(": ")
        assert separator, f"front matter line is not `key: value`: {line!r}"
        matter[key] = value
    assert matter, "front matter is empty"
    return matter


def test_recent_items_follow_group_order_and_language_titles():
    summarizer = DailySummarizer(
        profile_names=PROFILE_NAMES,
        profile_order=["gh-trending", "ai-news"],
    )
    items = [
        _make_item(1, "ai-news", "News One"),
        _make_item(2, "gh-trending", "Tool One"),
        _make_item(3, "gh-trending", "Tool Two"),
    ]

    recent = recent_items(summarizer.build_view(items, "zh"))

    assert [entry["title"] for entry in recent] == [
        "Tool One (zh)",
        "Tool Two (zh)",
        "News One (zh)",
    ]
    assert [entry["section"] for entry in recent] == [
        "GitHub AI 开发工具",
        "GitHub AI 开发工具",
        "AI 热门新闻",
    ]
    assert [entry["anchor"] for entry in recent] == [
        "item-gh-trending-1",
        "item-gh-trending-2",
        "item-ai-news-1",
    ]
    assert recent[0]["score"] == 8.0
    assert set(recent[0]) == {"title", "anchor", "section", "score"}


def test_recent_items_use_requested_language():
    summarizer = DailySummarizer(profile_names=PROFILE_NAMES)
    items = [_make_item(1, "gh-trending", "Tool One")]

    recent = recent_items(summarizer.build_view(items, "en"))

    assert [entry["title"] for entry in recent] == ["Tool One (en)"]


def test_post_front_matter_has_expected_keys():
    matter = _parse_front_matter(post_front_matter("2026-10-16", "zh", []))

    assert matter["layout"] == "default"
    assert matter["lang"] == "zh"
    assert matter["date"] == "2026-10-16"
    assert json.loads(matter["title"]) == "Horizon Summary: 2026-10-16 (ZH)"
    assert json.loads(matter["items"]) == []


def test_post_front_matter_round_trips_items():
    items = [
        {
            "title": "owner/repo：AI 代码审查",
            "anchor": "item-gh-trending-1",
            "section": "GitHub AI 开发工具",
            "score": 9.0,
        },
        {
            "title": "News One",
            "anchor": "item-ai-news-1",
            "section": "AI 热门新闻",
            "score": "?",
        },
    ]

    matter = _parse_front_matter(post_front_matter("2026-10-16", "zh", items))

    assert json.loads(matter["items"]) == items


def test_post_front_matter_survives_tricky_titles():
    """Quotes, colons, hashes and newlines must not break the YAML scalar."""
    tricky = 'Tool: "quoted" # not a comment:\n第二行 中文 🚀 '
    items = [
        {
            "title": tricky,
            "anchor": "item-ai-news-1",
            "section": "AI 热门新闻: 实践",
            "score": 7.5,
        }
    ]

    matter = _parse_front_matter(post_front_matter("2026-10-16", "en", items))

    assert json.loads(matter["items"])[0]["title"] == tricky

    # The newline is escaped, so the item list stays on a single YAML line and
    # no extra front-matter key appears.
    assert "\\n" in matter["items"]
    assert "\n" not in matter["items"]
    assert set(matter) == {"layout", "title", "date", "lang", "items"}
