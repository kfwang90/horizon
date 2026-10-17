from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.models import GitHubSourceConfig
from src.scrapers.github import GitHubScraper


def _repo(name: str, **overrides) -> dict:
    payload = {
        "full_name": name,
        "html_url": f"https://github.com/{name}",
        "description": "An AI coding assistant",
        "language": "Python",
        "stargazers_count": 1234,
        "forks_count": 56,
        "open_issues_count": 7,
        "topics": ["ai-agent", "code-review"],
        "created_at": "2026-09-01T10:00:00Z",
        "pushed_at": "2026-10-17T08:30:00Z",
    }
    payload.update(overrides)
    return payload


def _mock_client(payload: dict, status: int = 200) -> AsyncMock:
    response = MagicMock()
    response.json.return_value = payload
    response.text = "boom"
    response.status_code = status
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    return client


def _since() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=24)


def test_search_builds_items_from_results() -> None:
    payload = {"items": [_repo("acme/high"), _repo("acme/low", stargazers_count=5)]}
    client = _mock_client(payload)
    source = GitHubSourceConfig(
        type="search",
        query="topic:ai-agent stars:>10",
        sort="stars",
        max_items=5,
        category="gh-trending",
        profile="gh-trending",
    )
    scraper = GitHubScraper([source], client)

    items = asyncio.run(scraper.fetch(_since()))

    assert [item.title for item in items] == ["acme/high", "acme/low"]
    assert str(items[0].url) == "https://github.com/acme/high"
    assert items[0].author == "acme"
    assert items[0].profile == "gh-trending"
    assert items[0].metadata["stars_total"] == 1234
    assert items[0].metadata["topics"] == ["ai-agent", "code-review"]
    assert items[0].metadata["category"] == "gh-trending"
    content = items[0].content
    assert "Repository: acme/high" in content
    assert "An AI coding assistant" in content
    assert "Created: 2026-09-01" in content
    assert "Last pushed: 2026-10-17" in content
    assert "Matched query: topic:ai-agent stars:>10" in content


def test_search_expands_relative_dates_in_query() -> None:
    since = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)

    expanded = GitHubScraper._expand_query(
        "topic:mcp-server stars:>1 pushed:>{since_date} created:>{days_30} today:{today}",
        since,
    )

    assert "pushed:>2026-10-16" in expanded
    created = expanded.split("created:>")[1].split(" ")[0]
    assert created == (
        datetime.now(timezone.utc) - timedelta(days=30)
    ).date().isoformat()
    assert f"today:{datetime.now(timezone.utc).date().isoformat()}" in expanded


def test_search_sends_query_and_sort_params() -> None:
    client = _mock_client({"items": []})
    source = GitHubSourceConfig(
        type="search",
        query="topic:mcp-server stars:>100 pushed:>{since_date}",
        sort="updated",
        max_items=3,
    )
    scraper = GitHubScraper([source], client)

    asyncio.run(scraper.fetch(datetime(2026, 10, 16, tzinfo=timezone.utc)))

    _, kwargs = client.get.call_args
    assert kwargs["params"]["q"] == "topic:mcp-server stars:>100 pushed:>2026-10-16"
    assert kwargs["params"]["sort"] == "updated"
    assert kwargs["params"]["order"] == "desc"
    assert kwargs["params"]["per_page"] == "3"
    assert kwargs["params"]["q"].find("{") == -1


def test_search_best_match_omits_sort_param() -> None:
    client = _mock_client({"items": []})
    source = GitHubSourceConfig(type="search", query="topic:x", sort="best-match")
    scraper = GitHubScraper([source], client)

    asyncio.run(scraper.fetch(_since()))

    _, kwargs = client.get.call_args
    assert "sort" not in kwargs["params"]
    assert "order" not in kwargs["params"]


def test_search_uses_token_header_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    client = _mock_client({"items": []})
    source = GitHubSourceConfig(type="search", query="topic:x")
    scraper = GitHubScraper([source], client)

    asyncio.run(scraper.fetch(_since()))

    _, kwargs = client.get.call_args
    assert kwargs["headers"]["Authorization"] == "token secret-token"
    assert kwargs["headers"]["Accept"] == "application/vnd.github.v3+json"


def test_search_survives_rejected_query() -> None:
    client = _mock_client({"message": "Validation Failed"}, status=422)
    request = httpx.Request("GET", "https://api.github.com/search/repositories")
    response = httpx.Response(422, request=request, text="Validation Failed")
    client.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "422", request=request, response=response
    )
    source = GitHubSourceConfig(type="search", query="stars:>100000000000")
    scraper = GitHubScraper([source], client)

    assert asyncio.run(scraper.fetch(_since())) == []


def test_search_survives_broken_json() -> None:
    client = _mock_client({})
    client.get.return_value.json.side_effect = ValueError("not json")
    source = GitHubSourceConfig(type="search", query="topic:x")
    scraper = GitHubScraper([source], client)

    assert asyncio.run(scraper.fetch(_since())) == []


def test_search_skips_invalid_entries() -> None:
    payload = {
        "items": [
            _repo("acme/ok"),
            {"full_name": "", "html_url": ""},
            {"description": "no name"},
            "not-a-dict",
        ]
    }
    client = _mock_client(payload)
    source = GitHubSourceConfig(type="search", query="topic:x")
    scraper = GitHubScraper([source], client)

    items = asyncio.run(scraper.fetch(_since()))

    assert [item.title for item in items] == ["acme/ok"]


def test_search_without_query_is_ignored() -> None:
    client = _mock_client({"items": [_repo("acme/ok")]})
    source = GitHubSourceConfig(type="search")
    scraper = GitHubScraper([source], client)

    assert asyncio.run(scraper.fetch(_since())) == []
    client.get.assert_not_called()


def test_disabled_search_source_is_skipped() -> None:
    client = _mock_client({"items": [_repo("acme/ok")]})
    source = GitHubSourceConfig(type="search", query="topic:x", enabled=False)
    scraper = GitHubScraper([source], client)

    assert asyncio.run(scraper.fetch(_since())) == []
    client.get.assert_not_called()


def test_search_result_ids_differ_from_trending() -> None:
    """A repo found by both sources must not collide on id."""
    payload = {"items": [_repo("acme/ok")]}
    latest = _mock_client(payload)
    search = GitHubScraper(
        [GitHubSourceConfig(type="search", query="topic:x")], latest
    )._search_item("acme/ok", payload["items"][0], GitHubSourceConfig(type="search"))

    trending = GitHubScraper(
        [GitHubSourceConfig(type="trending")], _mock_client("")
    )

    assert search.id != trending._generate_id("github", "trending", "acme/ok")
