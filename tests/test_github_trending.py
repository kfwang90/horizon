from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.models import GitHubSourceConfig
from src.scrapers.github import GitHubScraper


def _page(*rows: str) -> str:
    return "<html><body>" + "".join(rows) + "</body></html>"


def _row(repo: str, desc: str, language: str, total: str, today: str) -> str:
    return f"""
    <article class="Box-row">
      <h2 class="h3 lh-condensed">
        <a href="/{repo}" data-view-component="true">{repo}</a>
      </h2>
      <p class="col-9 color-fg-muted my-1 pr-4">{desc}</p>
      <span class="d-inline-block ml-0 mr-3">
        <span class="repo-language-color"></span>
        <span itemprop="programmingLanguage">{language}</span>
      </span>
      <a href="/{repo}/stargazers" class="Link"> {total} </a>
      <span class="d-inline-block float-sm-right">{today} stars today</span>
    </article>
    """


def _mock_client(text: str) -> AsyncMock:
    response = MagicMock()
    response.text = text
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    return client


def test_parses_repo_rows() -> None:
    html = _page(
        _row("acme/tool", "A useful tool", "Rust", "12,345", "678"),
        _row("acme/other", "Another tool", "Python", "1,000", "99"),
    )

    rows = GitHubScraper._parse_trending(html)

    assert [repo for repo, _ in rows] == ["acme/tool", "acme/other"]
    meta = dict(rows)["acme/tool"]
    assert meta["description"] == "A useful tool"
    assert meta["language"] == "Rust"
    assert meta["stars_total"] == 12345
    assert meta["stars_today"] == 678


def test_skips_malformed_rows() -> None:
    html = _page("<article class='Box-row'><h2>no link</h2></article>")

    assert GitHubScraper._parse_trending(html) == []


def test_fetch_sorts_and_limits() -> None:
    html = _page(
        _row("acme/low", "Low", "Go", "10", "5"),
        _row("acme/high", "High", "Go", "10", "500"),
    )
    client = _mock_client(html)
    source = GitHubSourceConfig(type="trending", max_items=1)
    scraper = GitHubScraper([source], client)

    items = asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=24)))

    assert [item.title for item in items] == ["acme/high"]
    assert str(items[0].url) == "https://github.com/acme/high"
    assert items[0].metadata["stars_today"] == 500
    assert "Stars gained today: 500" in items[0].content


def test_language_all_uses_root_page() -> None:
    client = _mock_client(_page(_row("acme/tool", "D", "Go", "1", "1")))
    source = GitHubSourceConfig(type="trending", languages=["all"], since="weekly")
    scraper = GitHubScraper([source], client)

    asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=24)))

    url = client.get.call_args.args[0]
    assert url == "https://github.com/trending?since=weekly"


def test_language_filter_uses_subpage() -> None:
    client = _mock_client(_page(_row("acme/tool", "D", "Go", "1", "1")))
    source = GitHubSourceConfig(type="trending", languages=["python"])
    scraper = GitHubScraper([source], client)

    asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=24)))

    assert client.get.call_args.args[0] == "https://github.com/trending/python?since=daily"


def test_duplicate_repos_across_languages_collapse() -> None:
    client = _mock_client(_page(_row("acme/tool", "D", "Go", "1", "1")))
    source = GitHubSourceConfig(type="trending", languages=["all", "go"])
    scraper = GitHubScraper([source], client)

    items = asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=24)))

    assert len(items) == 1
    assert client.get.call_count == 2


def test_invalid_since_falls_back_to_daily() -> None:
    client = _mock_client(_page(_row("acme/tool", "D", "Go", "1", "1")))
    source = GitHubSourceConfig(type="trending", since="yearly")
    scraper = GitHubScraper([source], client)

    asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=24)))

    assert client.get.call_args.args[0] == "https://github.com/trending?since=daily"
