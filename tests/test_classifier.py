import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.ai.classifier import ContentClassifier
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentArtifact,
    ContentItem,
    ProcessingResult,
    SourceType,
)
from src.processing import ProfileRegistry


BASE_PROFILES = ProfileRegistry.load(
    Path(__file__).resolve().parents[1] / "profiles", "tech-news"
)
TECH_PROFILE = BASE_PROFILES.get("tech-news")
OTHER_PROFILE = replace(
    TECH_PROFILE,
    definition=TECH_PROFILE.definition.model_copy(
        update={"id": "other", "name": "Other"}
    ),
)
PROFILES = ProfileRegistry(
    {"tech-news": TECH_PROFILE, "other": OTHER_PROFILE},
    "tech-news",
)


def make_processed_item(
    *, requested: str, classified: str, method: str = "source_override"
) -> ContentItem:
    return ContentItem(
        id="rss:test:item",
        source_type=SourceType.RSS,
        title="A release",
        url="https://example.com/item",
        published_at=datetime.now(timezone.utc),
        profile=requested,
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile=classified,
                method=method,
                confidence=0.9 if method == "ai_match" else None,
                reason="Earlier classification" if method == "ai_match" else None,
            ),
            analysis=ContentAnalysis(
                score=8,
                reason="Relevant",
                summary="A release",
            ),
            artifacts={
                "en": ContentArtifact(language="en", title="A release")
            },
        ),
    )


def test_explicit_profile_refresh_clears_incoherent_processing_state():
    item = make_processed_item(requested="tech-news", classified="other")

    profile = asyncio.run(
        ContentClassifier(SimpleNamespace(), PROFILES).resolve(item)
    )

    assert profile.id == "tech-news"
    assert item.processing is not None
    assert item.processing.classification == ClassificationResult(
        profile="tech-news", method="source_override"
    )
    assert item.processing.analysis is None
    assert item.processing.artifacts == {}


def test_explicit_profile_refresh_preserves_coherent_processing_state():
    item = make_processed_item(requested="tech-news", classified="tech-news")
    prior_analysis = item.processing.analysis
    prior_artifacts = item.processing.artifacts

    asyncio.run(ContentClassifier(SimpleNamespace(), PROFILES).resolve(item))

    assert item.processing.classification == ClassificationResult(
        profile="tech-news", method="source_override"
    )
    assert item.processing.analysis is prior_analysis
    assert item.processing.artifacts is prior_artifacts


def test_resolved_ai_profile_is_not_rewritten_as_source_override():
    item = make_processed_item(
        requested="tech-news",
        classified="tech-news",
        method="ai_match",
    )
    prior_classification = item.processing.classification

    profile = asyncio.run(
        ContentClassifier(SimpleNamespace(), PROFILES).resolve(item)
    )

    assert profile.id == "tech-news"
    assert item.processing.classification is prior_classification
    assert item.processing.classification.method == "ai_match"
    assert item.processing.classification.confidence == 0.9


def test_candidate_profiles_restrict_ai_catalog():
    requests = []

    async def complete(**kwargs):
        requests.append(kwargs)
        return '{"profile":"finance-news","confidence":0.95,"reason":"Finance first"}'

    item = ContentItem(
        id="telegram:test:1",
        source_type=SourceType.TELEGRAM,
        title="Central bank cuts rates",
        url="https://example.com/finance",
        content="The central bank reduced its benchmark rate.",
        published_at=datetime.now(timezone.utc),
        profile=["tech-news", "finance-news"],
    )

    profile = asyncio.run(
        ContentClassifier(SimpleNamespace(complete=complete), BASE_PROFILES).resolve(item)
    )

    assert profile.id == "finance-news"
    assert item.processing is not None
    assert item.processing.classification.method == "ai_match"
    assert "## tech-news:" in requests[0]["user"]
    assert "## finance-news:" in requests[0]["user"]
    assert "## tech-blog:" not in requests[0]["user"]


def test_candidate_classification_failure_falls_back_within_candidates():
    async def complete(**kwargs):
        return '{"profile":"tech-news","confidence":0.9,"reason":"Wrong catalog"}'

    item = ContentItem(
        id="telegram:test:2",
        source_type=SourceType.TELEGRAM,
        title="Quarterly earnings",
        url="https://example.com/earnings",
        published_at=datetime.now(timezone.utc),
        profile=["finance-news", "tech-blog"],
    )

    profile = asyncio.run(
        ContentClassifier(SimpleNamespace(complete=complete), BASE_PROFILES).resolve(item)
    )

    assert profile.id == "finance-news"
    assert item.processing is not None
    assert item.processing.classification.profile == "finance-news"
    assert item.processing.classification.confidence == 0
