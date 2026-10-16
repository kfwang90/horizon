import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import src.processing.profiles as profile_module
from src.models import ProcessingConfig, ProfileSettingsConfig
from src.processing import ProfileRegistry


def test_loads_builtin_profiles():
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "tech-news"
    )

    for profile_id in ("tech-news", "tech-blog", "finance-news"):
        profile = registry.get(profile_id)
        assert profile.match_prompt
        assert profile.analysis_prompt
        assert profile.enrichment_prompt

    tech_impact = next(
        block
        for block in registry.get("tech-news").definition.enrichment.blocks
        if block.id == "impact"
    )
    finance_impact = next(
        block
        for block in registry.get("finance-news").definition.enrichment.blocks
        if block.id == "impact"
    )
    assert tech_impact.optional is True
    assert finance_impact.optional is True


@pytest.mark.parametrize(
    ("route", "message"),
    [
        ([], "cannot be empty"),
        (["tech-news", ""], "non-empty strings"),
        (["tech-news", "tech-news"], "must be unique"),
        (["tech-news", "auto"], "cannot contain 'auto'"),
        (["tech-news", "missing"], "Unknown processing profile"),
    ],
)
def test_rejects_invalid_profile_candidate_lists(route, message):
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "tech-news"
    )

    with pytest.raises(ValueError, match=message):
        registry.validate_source_references({"profile": route})


def test_default_profiles_fall_back_to_packaged_resources(tmp_path, monkeypatch):
    packaged_profiles = tmp_path / "packaged-profiles"
    source_profiles = Path(__file__).resolve().parents[1] / "profiles"
    shutil.copytree(source_profiles, packaged_profiles)
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(profile_module, "BUILTIN_PROFILES_DIR", packaged_profiles)

    registry = ProfileRegistry.load(Path("profiles"), "tech-news")

    assert registry.get("tech-news").analysis_prompt


def test_rejects_runtime_filter_settings_in_profile(tmp_path):
    profile_dir = tmp_path / "invalid"
    profile_dir.mkdir()
    for name in ("match.md", "analysis.md", "enrichment.md"):
        (profile_dir / name).write_text("prompt", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "invalid",
                "name": "Invalid",
                "match": "match.md",
                "analysis": "analysis.md",
                "filter": {"enabled": True, "threshold": 7.0},
                "enrichment": {
                    "prompt": "enrichment.md",
                    "blocks": [{"id": "body", "type": "section", "tools": []}],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ProfileRegistry.load(tmp_path, "invalid")


@pytest.mark.parametrize("threshold", [-0.1, 10.1])
def test_rejects_profile_threshold_outside_score_range(threshold):
    with pytest.raises(ValidationError):
        ProfileSettingsConfig(threshold=threshold)


def test_profile_settings_default_to_no_filter_and_topic_dedup():
    settings = ProcessingConfig().profile_settings.get("tech-news")

    assert settings is None
    defaults = ProfileSettingsConfig()
    assert defaults.threshold is None
    assert defaults.topic_dedup is True


def test_rejects_prompt_path_outside_profile_directory(tmp_path):
    profile_dir = tmp_path / "invalid"
    profile_dir.mkdir()
    (tmp_path / "outside.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "analysis.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "enrichment.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "invalid",
                "name": "Invalid",
                "match": "../outside.md",
                "analysis": "analysis.md",
                "enrichment": {
                    "prompt": "enrichment.md",
                    "blocks": [{"id": "body", "type": "section", "tools": []}],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes"):
        ProfileRegistry.load(tmp_path, "invalid")
