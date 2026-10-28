"""Helpers for the Jekyll site published from ``docs/``.

The digest posts double as the data source for the index page's 「近期消息」
(recent items) section: each post carries its item list in the front matter,
so the index can list the last week without re-reading every page.
"""

import json
from typing import Any, Dict, List

from ..ai.summarizer import DailySummaryView


def recent_items(view: DailySummaryView) -> List[Dict[str, Any]]:
    """Flatten a digest view into the per-post item list.

    Only what a list entry needs is kept: the display title, the anchor that
    the item renders under inside the day's page, its section and its score.

    ``key`` carries the stable source id (e.g. ``github:repo:owner/name``).
    The index page deduplicates repeated days by it, because AI-generated
    display titles can drift while the underlying item stays the same.
    """
    return [
        {
            "key": view_item.item.id,
            "title": view_item.title,
            "anchor": view_item.anchor_id,
            "section": group.name,
            "score": view_item.score,
        }
        for group in view.groups
        for view_item in group.items
    ]


def post_front_matter(date: str, language: str, items: List[Dict[str, Any]]) -> str:
    """Build the Jekyll front matter for one digest post.

    ``items`` is serialized as JSON, which is a subset of YAML, so titles that
    contain quotes, colons or CJK text need no hand-rolled escaping.
    """
    return (
        "---\n"
        "layout: default\n"
        f'title: "Horizon Summary: {date} ({language.upper()})"\n'
        f"date: {date}\n"
        f"lang: {language}\n"
        f"items: {json.dumps(items, ensure_ascii=False)}\n"
        "---\n\n"
    )
