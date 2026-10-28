"""Cross-run dedup registry.

Keeps a persistent map of ``item.id -> last seen date`` so that content that
was already published in a recent digest (a repo stuck on the trending list,
a popular video...) is skipped on later runs instead of showing up again day
after day. The registry lives in ``data/seen-items.json`` and travels with
the digests through the deploy repo's archive, so both local runs and CI see
the same history.

Only ids count for matching, never display titles: AI-generated titles can
drift between runs while the underlying item stays the same.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import ContentItem

logger = logging.getLogger(__name__)

# Registry version; entries from older layouts are ignored on load.
_SCHEMA_VERSION = 1


class SeenRegistry:
    """Persistence for "already reported" item ids within a look-back window."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: Dict[str, Dict[str, str]] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> Dict[str, Dict[str, str]]:
        """Read the registry file; any failure means an empty registry."""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as exc:  # corrupt file must not kill the daily run
            logger.warning("Seen registry %s is unreadable (%s); starting empty.", self.path, exc)
            return {}

        if not isinstance(data, dict) or data.get("version") != _SCHEMA_VERSION:
            return {}
        items = data.get("items")
        if not isinstance(items, dict):
            return {}
        return {
            key: value
            for key, value in items.items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def save(self) -> None:
        """Write the registry atomically (tmp file + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _SCHEMA_VERSION, "items": self._entries}
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        tmp_path.replace(self.path)

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------
    def filter_out_seen(
        self,
        items: List[ContentItem],
        window_days: int,
        today: Optional[date] = None,
    ) -> Tuple[List[ContentItem], List[ContentItem]]:
        """Split items into (fresh, repeats) within the look-back window.

        An item repeats when its id was recorded in the last ``window_days``
        days. Older entries keep the item eligible — they are only used to
        bound the file size, not to block anything.
        """
        today = today or date.today()
        earliest = today - timedelta(days=window_days)
        fresh: List[ContentItem] = []
        repeats: List[ContentItem] = []
        for item in items:
            entry = self._entries.get(item.id)
            last_seen = self._parse_date(entry.get("last_seen")) if entry else None
            if last_seen and last_seen >= earliest:
                repeats.append(item)
            else:
                fresh.append(item)
        return fresh, repeats

    def record(
        self,
        items: List[ContentItem],
        today: Optional[date] = None,
        prune_days: Optional[int] = None,
    ) -> int:
        """Record the items as seen today and prune stale entries.

        Args:
            items: items that actually made it into a digest
            today: reference date for ``last_seen``
            prune_days: drop entries older than this; pass the dedup window
                so entries can never block anything again once stale. ``None``
                keeps every entry (file grows until the next windowed call).
        Returns:
            Number of entries currently held after saving.
        """
        today = today or date.today()
        for item in items:
            old = self._entries.get(item.id)
            # Keep the first, usually descriptive title for troubleshooting.
            title = (old.get("title") if old else item.title) or ""
            self._entries[item.id] = {"last_seen": today.isoformat(), "title": title[:120]}
        self._prune(today, prune_days)
        self.save()
        return len(self._entries)

    def _prune(self, today: date, prune_days: Optional[int]) -> None:
        if not prune_days or prune_days <= 0:
            return
        earliest = today - timedelta(days=prune_days)
        keep: Dict[str, Dict[str, str]] = {}
        for key, entry in self._entries.items():
            last_seen = self._parse_date(entry.get("last_seen"))
            if last_seen is None or last_seen >= earliest:
                keep[key] = entry
        self._entries = keep

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None
