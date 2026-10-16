import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

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
from src.processing.history import HistorySearchTool
from src.processing.tools import ToolRegistry


BEFORE = date(2026, 4, 2)


def story(title, summary, url="https://example.com/story", level=3, extra=""):
    return (
        f"{'#' * level} [{title}]({url}) ⭐️ 8.0/10\n\n"
        f"{summary}\n\nrss · Example · Apr 1, 10:00\n\n{extra}\n\n---\n\n"
    )


def search(tool, query, **kwargs):
    return asyncio.run(tool.execute({"query": query}, before=BEFORE, **kwargs))


def test_search_reads_current_renderer_and_does_not_index_background(tmp_path):
    item = ContentItem(
        id="rss:example:release",
        source_type=SourceType.RSS,
        title="Atlas preview",
        url="https://example.com/atlas",
        published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        processing=ProcessingResult(
            classification=ClassificationResult(profile="tech-news", method="source_override"),
            analysis=ContentAnalysis(score=8, reason="Release", summary="Atlas preview", tags=["Atlas"]),
            artifacts={"en": ContentArtifact(
                language="en",
                title="Atlas preview",
                blocks=[
                    ContentBlock(id="summary", title="Summary", content="Atlas adds batch inference.", primary=True),
                    ContentBlock(id="background", title="Background", content="Previous callback mentions Zephyr."),
                ],
            )},
        ),
    )
    digest = asyncio.run(DailySummarizer().generate_summary([item], "2026-04-01", 1))
    (tmp_path / "horizon-2026-04-01-en.md").write_text(digest, encoding="utf-8")
    tool = HistorySearchTool(tmp_path)

    results = search(tool, "Atlas batch inference")

    assert len(results) == 1
    assert results[0]["url"] == "https://example.com/atlas"
    assert "2026-04-01" in results[0]["title"]
    assert "Atlas adds batch inference." in results[0]["text"]
    assert "Zephyr" not in results[0]["text"]
    assert search(tool, "Zephyr") == []


@pytest.mark.parametrize("level", [2, 3])
def test_legacy_headings_and_chinese_search(tmp_path, level):
    (tmp_path / "horizon-2026-04-01-zh-model.md").write_text(
        story("推理框架更新", "新版本优化了显存占用。", level=level, extra="**标签**: `#vLLM`"),
        encoding="utf-8",
    )
    tool = HistorySearchTool(tmp_path)

    assert len(search(tool, "显存优化")) == 1
    assert len(search(tool, "VLLM")) == 1
    assert search(tool, "机器人") == []


def test_bm25_prioritizes_specific_project_and_title(tmp_path):
    (tmp_path / "horizon-2026-04-01.md").write_text(
        story("Atlas inference", "Atlas improves batch throughput.", "https://example.com/relevant")
        + story("Inference industry overview", "Inference performance " * 100, "https://example.com/general")
        + story("Hardware performance", "Inference performance is improving.", "https://example.com/hardware"),
        encoding="utf-8",
    )

    results = search(HistorySearchTool(tmp_path), "Atlas inference performance")

    assert results[0]["url"] == "https://example.com/relevant"


def test_version_numbers_do_not_match_unrelated_versions(tmp_path):
    (tmp_path / "horizon-2026-04-01.md").write_text(
        story("GPT-5.6 pricing", "GPT-5.6 prices changed.", "https://example.com/gpt")
        + story("Seedance 2.5", "Seedance now accepts 5 images.", "https://example.com/seedance"),
        encoding="utf-8",
    )

    results = search(HistorySearchTool(tmp_path), "GPT-5.6 pricing")

    assert [entry["url"] for entry in results] == ["https://example.com/gpt"]


def test_dates_come_from_filename_and_current_or_future_digests_are_excluded(tmp_path):
    for day in ("2025-01-01", "2026-04-01", "2026-04-02", "2026-04-03"):
        (tmp_path / f"horizon-{day}-en.md").write_text(
            story("Atlas release", "Atlas release notes.", f"https://example.com/{day}"),
            encoding="utf-8",
        )
    (tmp_path / "horizon-2026-02-31.md").write_text("invalid date", encoding="utf-8")

    results = search(HistorySearchTool(tmp_path), "Atlas")

    assert [entry["url"] for entry in results] == ["https://example.com/2026-04-01"]


def test_can_extend_history_window(tmp_path):
    (tmp_path / "horizon-2025-11-01.md").write_text(story("Atlas", "Atlas preview."), encoding="utf-8")
    tool = HistorySearchTool(tmp_path)

    assert search(tool, "Atlas") == []
    assert len(asyncio.run(tool.execute({"query": "Atlas", "days": 365}, before=BEFORE))) == 1


def test_deduplicates_translations_and_excludes_current_url_before_limit(tmp_path):
    original = story("Atlas preview", "Atlas preview.", "https://example.com/atlas")
    (tmp_path / "horizon-2026-04-01-en.md").write_text(original, encoding="utf-8")
    (tmp_path / "horizon-2026-04-01-zh.md").write_text(
        story("Atlas 预览", "Atlas 预览。", "https://example.com/atlas/#section")
        + "".join(story("Atlas extension", "Atlas extension.", f"https://example.com/{i}") for i in range(5)),
        encoding="utf-8",
    )
    tool = HistorySearchTool(tmp_path)

    results = search(tool, "Atlas")
    assert len(results) == 3
    assert len({entry["url"].split("#")[0].rstrip("/") for entry in results}) == 3
    excluded = search(tool, "Atlas", exclude_url="https://example.com/atlas/#new")
    assert len(excluded) == 3
    assert all("/atlas" not in entry["url"] for entry in excluded)


def test_bounds_returned_summary_and_handles_missing_archive(tmp_path):
    tool = HistorySearchTool(tmp_path / "missing")
    assert search(tool, "Atlas") == []
    assert not (tmp_path / "missing").exists()
    assert search(HistorySearchTool(), "Atlas") == []

    (tmp_path / "horizon-2026-04-01.md").write_text(
        story("Atlas", "Atlas " + "x" * 10000), encoding="utf-8",
    )
    results = search(HistorySearchTool(tmp_path), "Atlas")
    assert len(results[0]["text"].split("Archived summary: ")[1]) == 500


def test_loads_archive_once_for_concurrent_queries(tmp_path, monkeypatch):
    import src.processing.history as history

    (tmp_path / "horizon-2026-04-01.md").write_text(story("Atlas", "Atlas preview."), encoding="utf-8")
    read_entries = history._read_entries
    calls = []

    def record_read(directory):
        calls.append(directory)
        return read_entries(directory)

    monkeypatch.setattr(history, "_read_entries", record_read)
    tool = HistorySearchTool(tmp_path)

    async def queries():
        return await asyncio.gather(*(
            tool.execute({"query": "Atlas"}, before=BEFORE) for _ in range(3)
        ))

    assert all(asyncio.run(queries()))
    assert calls == [tmp_path]


@pytest.mark.parametrize("arguments", [{"query": " "}, {"query": "Atlas", "days": 0}, {"query": "Atlas", "days": True}])
def test_rejects_invalid_tool_arguments(tmp_path, arguments):
    with pytest.raises(ValueError):
        asyncio.run(HistorySearchTool(tmp_path).execute(arguments))


def test_registry_uses_current_item_context_instead_of_model_supplied_exclusions(tmp_path):
    (tmp_path / "horizon-2026-04-01.md").write_text(
        story("Atlas preview", "Atlas preview.")
        + story("Atlas earlier release", "Atlas release.", "https://example.com/earlier"),
        encoding="utf-8",
    )
    (tmp_path / "horizon-2026-04-03.md").write_text(
        story("Atlas later release", "Atlas release.", "https://example.com/later"), encoding="utf-8",
    )
    result = asyncio.run(ToolRegistry(tmp_path).execute(
        "tool-1", "background", "history_search", {"query": "Atlas", "before": "2099-01-01"},
        current_item=SimpleNamespace(
            url="https://example.com/story",
            published_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
        ),
    ))

    assert result.tool == "history_search"
    assert [entry["url"] for entry in result.results] == ["https://example.com/earlier"]
