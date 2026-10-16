from pathlib import Path
from datetime import datetime, timezone

from src.ai.prompting.enrichment import (
    artifact_prompt,
    block_prompt,
    item_context,
    tool_planning_prompt,
)
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.processing import ProfileRegistry


PROFILES = ProfileRegistry.load(
    Path(__file__).resolve().parents[1] / "profiles", "tech-news"
)


def test_tool_planning_excludes_profile_writing_policy():
    profile = PROFILES.get("tech-news")
    blocks = profile.definition.enrichment.blocks

    planning = tool_planning_prompt(blocks)
    artifact = artifact_prompt(profile, "en", blocks)
    block = block_prompt(profile, "en", blocks[0], include_header=True)

    assert profile.enrichment_prompt not in planning
    assert profile.enrichment_prompt in artifact
    assert profile.enrichment_prompt in block
    assert all(configured.id in planning for configured in blocks)
    assert "Block `background` is required" in planning
    assert "history_search" in planning
    assert "at most 3 short results" in planning
    assert "Request at most one history search per item" in planning


def test_enrichment_context_uses_profile_content_budget():
    profile = PROFILES.get("tech-blog")
    item = ContentItem(
        id="rss:test:blog",
        source_type=SourceType.RSS,
        title="Long article",
        url="https://example.com/blog",
        published_at=datetime.now(timezone.utc),
        profile="tech-blog",
        content="OPENING" + "A" * 25000 + "MIDDLE" + "B" * 25000 + "ENDING",
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-blog", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8,
                reason="Deep article",
                summary="A long argument",
            ),
        ),
    )

    context = item_context(item, profile, include_content=True)

    assert "[Opening excerpt]" in context
    assert "[Middle excerpt]" in context
    assert "[Closing excerpt]" in context
    assert "OPENING" in context
    assert "MIDDLE" in context
    assert "ENDING" in context
