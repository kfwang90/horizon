"""GitHub scraper implementation."""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper
from ..models import ContentItem, SourceType, GitHubSourceConfig

logger = logging.getLogger(__name__)

TRENDING_BASE_URL = "https://github.com/trending"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class GitHubScraper(BaseScraper):
    """Scraper for GitHub events and releases."""

    def __init__(self, sources: List[GitHubSourceConfig], http_client: httpx.AsyncClient):
        """Initialize GitHub scraper.

        Args:
            sources: List of GitHub source configurations
            http_client: Shared async HTTP client
        """
        super().__init__({"sources": sources}, http_client)
        self.token = os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"

    def _get_headers(self) -> dict:
        """Get request headers with optional authentication.

        Returns:
            dict: HTTP headers
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Horizon-Aggregator"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch GitHub content items.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        items = []
        sources = self.config["sources"]

        for source in sources:
            if not source.enabled:
                continue

            if source.type == "user_events" and source.username:
                user_items = await self._fetch_user_events(source, since)
                items.extend(user_items)
            elif source.type == "repo_releases" and source.owner and source.repo:
                release_items = await self._fetch_repo_releases(source, since)
                items.extend(release_items)
            elif source.type == "trending":
                trending_items = await self._fetch_trending(source)
                items.extend(trending_items)
            elif source.type == "search" and source.query:
                search_items = await self._fetch_search(source, since)
                items.extend(search_items)

        return items

    async def _fetch_trending(self, source: GitHubSourceConfig) -> List[ContentItem]:
        """Fetch the github.com/trending leaderboard.

        Scrapes the public HTML page (no API, no token). One request per
        configured language; an empty `languages` list means the all-language
        page. There is no per-repository timestamp on that page, so items are
        dated "now" and treated as part of the current run's window.
        """
        languages = source.languages or ["all"]
        since = source.since if source.since in {"daily", "weekly", "monthly"} else "daily"

        items: List[ContentItem] = []
        seen: set[str] = set()

        for language in languages:
            rows = await self._fetch_trending_page(language, since)
            for repo, meta in rows:
                if repo in seen:
                    continue
                seen.add(repo)
                items.append(
                    ContentItem(
                        id=self._generate_id("github", "trending", repo),
                        source_type=SourceType.GITHUB,
                        title=repo,
                        url=f"https://github.com/{repo}",
                        content=self._trending_content(repo, meta),
                        author=repo.split("/")[0],
                        published_at=datetime.now(timezone.utc),
                        profile=source.profile,
                        metadata={
                            "repo": repo,
                            "trending_language": language or "all",
                            "trending_since": since,
                            "language": meta.get("language", ""),
                            "stars_today": meta.get("stars_today", 0),
                            "stars_total": meta.get("stars_total", 0),
                            "description": meta.get("description", ""),
                            "category": source.category,
                        },
                    )
                )

        items.sort(key=lambda item: item.metadata.get("stars_today", 0), reverse=True)
        if source.max_items:
            items = items[: source.max_items]
        return items

    async def _fetch_search(
        self, source: GitHubSourceConfig, since: datetime
    ) -> List[ContentItem]:
        """Search repositories through the GitHub search API.

        `source.query` may contain `{since_date}` (the start of the run window)
        and `{days_N}` (N days before now), which are expanded at fetch time so
        relative windows such as `pushed:>{since_date}` stay current.

        Results are dated "now" like the trending page: a search hit is news for
        the day it surfaced, whereas the repository's own `pushed_at` would drop
        long-lived projects from the run window.
        """
        query = self._expand_query(source.query or "", since)
        if not query:
            return []

        params = {"q": query, "per_page": str(min(source.max_items or 20, 100))}
        sort = (source.sort or "").strip().lower()
        if sort and sort != "best-match":
            params["sort"] = sort
            params["order"] = "desc"

        try:
            response = await self.client.get(
                f"{self.base_url}/search/repositories",
                headers=self._get_headers(),
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "").strip().replace("\n", " ")[:200]
            logger.warning("GitHub search rejected (%s): %s %s", query, e, body)
            return []
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Error searching GitHub repositories (%s): %s", query, e)
            return []

        items: List[ContentItem] = []
        for repo in payload.get("items") or []:
            if not isinstance(repo, dict):
                continue
            full_name = repo.get("full_name") or ""
            if "/" not in full_name:
                continue
            items.append(self._search_item(full_name, repo, source))

        return items

    @staticmethod
    def _expand_query(query: str, since: datetime) -> str:
        """Expand `{today}`, `{since_date}` and `{days_N}` in a search query."""
        now = datetime.now(timezone.utc)
        expanded = query.replace("{today}", now.date().isoformat())
        expanded = expanded.replace(
            "{since_date}", since.astimezone(timezone.utc).date().isoformat()
        )

        def _replace_days(match: re.Match) -> str:
            days = int(match.group(1))
            return (now - timedelta(days=days)).date().isoformat()

        return re.sub(r"\{days_(\d+)\}", _replace_days, expanded).strip()

    @staticmethod
    def _search_content(repo: str, meta: dict) -> str:
        lines = [f"Repository: {repo}"]
        if meta.get("description"):
            lines.append(f"Description: {meta['description']}")
        if meta.get("language"):
            lines.append(f"Primary language: {meta['language']}")
        if meta.get("topics"):
            lines.append(f"Topics: {', '.join(meta['topics'][:12])}")
        lines.append(
            f"Stars: {meta.get('stars_total', 0)} (forks {meta.get('forks_total', 0)}, "
            f"open issues {meta.get('open_issues', 0)})"
        )
        if meta.get("created_at"):
            lines.append(f"Created: {str(meta['created_at'])[:10]}")
        if meta.get("pushed_at"):
            lines.append(f"Last pushed: {str(meta['pushed_at'])[:10]}")
        if meta.get("search_query"):
            lines.append(f"Matched query: {meta['search_query']}")
        return "\n".join(lines)

    def _search_item(
        self, repo: str, payload: dict, source: GitHubSourceConfig
    ) -> ContentItem:
        """Build a ContentItem from one repository search result."""
        metadata = {
            "repo": repo,
            "search_query": source.query or "",
            "language": payload.get("language") or "",
            "stars_total": payload.get("stargazers_count") or 0,
            "forks_total": payload.get("forks_count") or 0,
            "open_issues": payload.get("open_issues_count") or 0,
            "topics": payload.get("topics") or [],
            "created_at": payload.get("created_at") or "",
            "pushed_at": payload.get("pushed_at") or "",
            "description": payload.get("description") or "",
            "homepage": payload.get("homepage") or "",
            "category": source.category,
        }
        return ContentItem(
            id=self._generate_id("github", "search", repo),
            source_type=SourceType.GITHUB,
            title=repo,
            url=payload.get("html_url") or f"https://github.com/{repo}",
            content=self._search_content(repo, metadata),
            author=repo.split("/")[0],
            published_at=datetime.now(timezone.utc),
            profile=source.profile,
            metadata=metadata,
        )

    async def _fetch_trending_page(
        self, language: str, since: str
    ) -> List[tuple[str, dict]]:
        """Fetch and parse one trending page. Returns (repo, metadata) pairs."""
        url = TRENDING_BASE_URL
        language = "" if language.strip().lower() in {"", "all", "any"} else language.strip().strip("/")
        if language:
            url = f"{url}/{language}"
        url = f"{url}?since={since}"

        try:
            response = await self.client.get(
                url, headers=BROWSER_HEADERS, follow_redirects=True
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error fetching GitHub trending (%s): %s", url, e)
            return []

        return self._parse_trending(response.text)

    @staticmethod
    def _parse_trending(html: str) -> List[tuple[str, dict]]:
        """Parse trending repositories out of a GitHub trending page."""
        soup = BeautifulSoup(html, "html.parser")
        rows: List[tuple[str, dict]] = []

        for article in soup.select("article.Box-row"):
            link = article.select_one("h2 a")
            if not link:
                continue
            repo = (link.get("href") or "").strip("/")
            if not repo or "/" not in repo:
                continue

            description_el = article.select_one("p")
            language_el = article.select_one('[itemprop="programmingLanguage"]')
            stars_el = article.select_one('a[href$="/stargazers"]')

            text = article.get_text(" ", strip=True)
            today_match = re.search(r"([\d,]+)\s+stars?\s+today", text)

            rows.append(
                (
                    repo,
                    {
                        "description": (
                            description_el.get_text(" ", strip=True)
                            if description_el
                            else ""
                        ),
                        "language": (
                            language_el.get_text(strip=True) if language_el else ""
                        ),
                        "stars_today": (
                            int(today_match.group(1).replace(",", ""))
                            if today_match
                            else 0
                        ),
                        "stars_total": (
                            GitHubScraper._to_int(stars_el.get_text(strip=True))
                            if stars_el
                            else 0
                        ),
                    },
                )
            )

        return rows

    @staticmethod
    def _to_int(value: str) -> int:
        digits = re.sub(r"[^\d]", "", value or "")
        return int(digits) if digits else 0

    @staticmethod
    def _trending_content(repo: str, meta: dict) -> str:
        lines = [f"Repository: {repo}"]
        if meta.get("description"):
            lines.append(f"Description: {meta['description']}")
        if meta.get("language"):
            lines.append(f"Primary language: {meta['language']}")
        lines.append(
            f"Stars gained today: {meta.get('stars_today', 0)} "
            f"(total {meta.get('stars_total', 0)})"
        )
        return "\n".join(lines)

    async def _fetch_user_events(
        self,
        source: GitHubSourceConfig,
        since: datetime,
    ) -> List[ContentItem]:
        """Fetch public events for a user.

        Args:
            source: GitHub source configuration
            since: Only fetch events after this time

        Returns:
            List[ContentItem]: Event content items
        """
        url = f"{self.base_url}/users/{source.username}/events/public"
        items = []

        try:
            response = await self.client.get(url, headers=self._get_headers(), follow_redirects=True)
            response.raise_for_status()
            events = response.json()

            for event in events:
                created_at = datetime.fromisoformat(
                    event["created_at"].replace("Z", "+00:00")
                )

                if created_at < since:
                    continue

                # Filter interesting event types
                event_type = event["type"]
                if event_type not in [
                    "PushEvent", "CreateEvent", "ReleaseEvent",
                    "PublicEvent", "WatchEvent"
                ]:
                    continue

                item = self._parse_event(event, source)
                if item:
                    items.append(item)

        except httpx.HTTPError as e:
            logger.warning("Error fetching GitHub events for %s: %s", source.username, e)

        return items

    def _parse_event(self, event: dict, source: GitHubSourceConfig) -> Optional[ContentItem]:
        """Parse GitHub event into ContentItem.

        Args:
            event: GitHub event data
            username: GitHub username

        Returns:
            Optional[ContentItem]: Parsed content item or None
        """
        event_type = event["type"]
        event_id = event["id"]
        created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
        username = source.username

        repo_name = event["repo"]["name"]
        repo_url = f"https://github.com/{repo_name}"

        # Generate title and content based on event type
        if event_type == "PushEvent":
            commits = event["payload"].get("commits", [])
            title = f"{username} pushed {len(commits)} commit(s) to {repo_name}"
            content = "\n".join([c.get("message", "") for c in commits[:3]])
        elif event_type == "CreateEvent":
            ref_type = event["payload"].get("ref_type", "repository")
            title = f"{username} created {ref_type} in {repo_name}"
            content = event["payload"].get("description", "")
        elif event_type == "ReleaseEvent":
            release = event["payload"].get("release", {})
            title = f"{username} released {release.get('tag_name', '')} in {repo_name}"
            content = release.get("body", "")
            repo_url = release.get("html_url", repo_url)
        elif event_type == "PublicEvent":
            title = f"{username} made {repo_name} public"
            content = ""
        elif event_type == "WatchEvent":
            title = f"{username} starred {repo_name}"
            content = ""
        else:
            return None

        return ContentItem(
            id=self._generate_id("github", "event", event_id),
            source_type=SourceType.GITHUB,
            title=title,
            url=repo_url,
            content=content,
            author=username,
            published_at=created_at,
            profile=source.profile,
            metadata={
                "event_type": event_type,
                "repo": repo_name,
                "category": source.category,
            }
        )

    async def _fetch_repo_releases(
        self,
        source: GitHubSourceConfig,
        since: datetime,
    ) -> List[ContentItem]:
        """Fetch releases for a repository.

        Args:
            source: GitHub source configuration
            since: Only fetch releases after this time

        Returns:
            List[ContentItem]: Release content items
        """
        owner, repo = source.owner, source.repo
        url = f"{self.base_url}/repos/{owner}/{repo}/releases"
        items = []

        try:
            response = await self.client.get(url, headers=self._get_headers(), follow_redirects=True)
            response.raise_for_status()
            releases = response.json()

            for release in releases:
                published_at = datetime.fromisoformat(
                    release["published_at"].replace("Z", "+00:00")
                )

                if published_at < since:
                    continue

                item = ContentItem(
                    id=self._generate_id("github", "release", str(release["id"])),
                    source_type=SourceType.GITHUB,
                    title=f"{owner}/{repo} released {release['tag_name']}",
                    url=release["html_url"],
                    content=release.get("body", ""),
                    author=release["author"]["login"],
                    published_at=published_at,
                    profile=source.profile,
                    metadata={
                        "repo": f"{owner}/{repo}",
                        "tag": release["tag_name"],
                        "prerelease": release.get("prerelease", False),
                        "category": source.category,
                    }
                )
                items.append(item)

        except httpx.HTTPError as e:
            logger.warning("Error fetching releases for %s/%s: %s", owner, repo, e)

        return items
