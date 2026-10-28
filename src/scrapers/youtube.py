"""YouTube scraper implementation.

Lists the newest videos of configured channels and runs keyword searches
(`ytsearch{N}:query` via yt-dlp), then keeps the most viewed results with
GitHub-related ones boosted to the top. Uses yt-dlp's *flat playlist*
extraction, which needs no API key and no YouTube account.

Why flat extraction: full per-video extraction triggers YouTube's
"Sign in to confirm you're not a bot" challenge from datacenter IPs, while
channel listing stays cheap (one request per channel). The trade-off is that
flat entries carry no upload date, so items are dated at fetch time.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from .base import BaseScraper
from ..models import (
    ContentItem,
    ProfileRoute,
    SourceType,
    YouTubeChannelConfig,
    YouTubeConfig,
)

logger = logging.getLogger(__name__)


class YouTubeScraper(BaseScraper):
    """Scraper for YouTube channel uploads (metadata only)."""

    def __init__(
        self,
        config: YouTubeConfig,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        """Initialize scraper.

        Args:
            config: YouTube source configuration
            http_client: Unused; kept for BaseScraper compatibility
        """
        super().__init__({"config": config}, http_client)
        self.cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch the most viewed recent videos across channels and searches.

        Args:
            since: Pipeline time window. Flat extractions carry no upload
                date, so this is currently informational only.

        Returns:
            List[ContentItem]: Fetched video items, GitHub-related ones first
            and most viewed otherwise
        """
        if not self.cfg.enabled or (not self.cfg.channels and not self.cfg.keywords):
            return []

        enabled = [c for c in self.cfg.channels if c.enabled]
        keywords = [k.strip() for k in self.cfg.keywords if k.strip()]
        jobs = [(c.channel, self._fetch_channel(c)) for c in enabled]
        jobs += [(k, self._fetch_keyword(k)) for k in keywords]
        results = await asyncio.gather(
            *(job[1] for job in jobs),
            return_exceptions=True,
        )

        items: List[ContentItem] = []
        seen: set[str] = set()
        for label, result in zip((job[0] for job in jobs), results):
            if isinstance(result, BaseException):
                logger.warning("YouTube source %s failed: %s", label, result)
                continue
            for item in result:
                if item.id in seen:
                    continue
                seen.add(item.id)
                items.append(item)

        if self.cfg.min_views:
            items = [
                item
                for item in items
                if (item.metadata.get("view_count") or 0) >= self.cfg.min_views
            ]

        # Prioritize GitHub-related content: keyword searches often cover other
        # topics as well, so anything mentioning GitHub stays at the top, and
        # view count decides the order inside each group.
        items.sort(
            key=lambda item: (
                not self._github_related(item),
                -(item.metadata.get("view_count") or 0),
            )
        )
        if self.cfg.max_items:
            items = items[: self.cfg.max_items]
        return items

    @staticmethod
    def _github_related(item: ContentItem) -> bool:
        """Whether title or content mentions GitHub."""
        text = f"{item.title} {item.content}".lower()
        return "github" in text

    async def _fetch_keyword(self, keyword: str) -> List[ContentItem]:
        """Run one keyword search via yt-dlp's `ytsearch{N}:query` extractor."""
        limit = max(1, self.cfg.search_fetch_limit)
        url = f"ytsearch{limit}:{keyword}"
        entries = await asyncio.to_thread(self._list_videos, url, limit)
        return self._entries_to_items(
            entries,
            author=keyword,
            category=self.cfg.category,
            profile=self.cfg.profile,
            search_query=keyword,
        )

    async def _fetch_channel(self, channel: YouTubeChannelConfig) -> List[ContentItem]:
        """List one channel's newest videos."""
        url = self._channel_url(channel.channel)
        limit = channel.fetch_limit or self.cfg.fetch_limit
        entries = await asyncio.to_thread(self._list_videos, url, limit)
        return self._entries_to_items(
            entries,
            author=channel.channel,
            channel_label=self._channel_label(channel.channel),
            category=channel.category or self.cfg.category,
            profile=channel.profile or self.cfg.profile,
        )

    def _entries_to_items(
        self,
        entries: List[dict],
        author: str,
        channel_label: Optional[str] = None,
        category: Optional[str] = None,
        profile: ProfileRoute = None,
        search_query: Optional[str] = None,
    ) -> List[ContentItem]:
        """Turn yt-dlp flat entries into ContentItems."""
        items: List[ContentItem] = []
        for entry in entries:
            video_id = entry.get("id")
            title = (entry.get("title") or "").strip()
            if not video_id or not title:
                continue
            metadata: dict = {
                "channel": channel_label or self._channel_label(author),
                "video_id": str(video_id),
                "view_count": entry.get("view_count"),
                "duration": entry.get("duration"),
                "category": category,
            }
            if search_query is not None:
                metadata["search_query"] = search_query
            items.append(
                ContentItem(
                    id=self._generate_id("youtube", "video", str(video_id)),
                    source_type=SourceType.YOUTUBE,
                    title=title,
                    url=entry.get("url")
                    or f"https://www.youtube.com/watch?v={video_id}",
                    content=self._video_content(entry),
                    author=author,
                    published_at=datetime.now(timezone.utc),
                    profile=profile,
                    metadata=metadata,
                )
            )
        return items

    @staticmethod
    def _list_videos(url: str, limit: int) -> List[dict]:
        """Run yt-dlp flat extraction for one channel URL."""
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            logger.warning(
                "yt-dlp is not installed; skipping the YouTube source. "
                "Install it with: uv sync --extra youtube"
            )
            return []

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": max(1, limit),
            "ignoreerrors": True,
            "noprogress": True,
            "socket_timeout": 20,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # yt-dlp raises its own error hierarchy
            logger.warning("yt-dlp failed for %s: %s", url, exc)
            return []

        if not info:
            return []
        entries = info.get("entries") or []
        return [entry for entry in entries if isinstance(entry, dict)]

    @staticmethod
    def _channel_label(value: str) -> str:
        """Short channel label for terminal output."""
        value = (value or "").strip()
        if value.startswith(("http://", "https://")):
            parts = [p for p in value.rstrip("/").split("/") if p]
            label = parts[-2] if parts and parts[-1] == "videos" else (parts[-1] if parts else value)
            return label.lstrip("@")
        return value.lstrip("@")

    @staticmethod
    def _channel_url(value: str) -> str:
        """Normalize a channel handle, id, or URL into a /videos listing URL."""
        value = (value or "").strip()
        if value.startswith(("http://", "https://")):
            base = value.rstrip("/")
            return base if base.endswith("/videos") else f"{base}/videos"

        handle = value.lstrip("@")
        if handle.startswith("UC") and len(handle) == 24:
            return f"https://www.youtube.com/channel/{handle}/videos"
        return f"https://www.youtube.com/@{handle}/videos"

    @staticmethod
    def _video_content(entry: dict) -> str:
        """Build the text handed to the AI for one video."""
        lines: List[str] = []
        channel = entry.get("channel") or entry.get("uploader")
        if channel:
            lines.append(f"Channel: {channel}")
        if entry.get("view_count") is not None:
            lines.append(f"Views: {entry['view_count']}")
        if entry.get("duration"):
            lines.append(f"Duration: {entry['duration']} seconds")
        if entry.get("description"):
            lines.append(f"Description: {entry['description']}")
        if entry.get("url"):
            lines.append(f"Video URL: {entry['url']}")
        return "\n".join(lines)
