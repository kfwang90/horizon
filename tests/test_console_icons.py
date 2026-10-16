import pytest
from pydantic import ValidationError

from src.console_icons import ICON_SETS, get_icons
from src.models import Config


MINIMAL_CONFIG = {
    "ai": {
        "provider": "openai",
        "model": "test",
        "api_key_env": "OPENAI_API_KEY",
    },
    "sources": {},
}


def test_icon_sets_have_the_same_semantic_keys():
    expected = set(ICON_SETS["emoji"])

    assert set(ICON_SETS["nerd"]) == expected
    assert set(ICON_SETS["ascii"]) == expected


def test_default_icon_style_is_emoji():
    config = Config.model_validate(MINIMAL_CONFIG)

    assert config.display.icon_style == "emoji"
    assert get_icons(config.display.icon_style)["success"] == "✅"


@pytest.mark.parametrize("style", ["emoji", "nerd", "ascii"])
def test_config_accepts_supported_icon_styles(style):
    config = Config.model_validate({**MINIMAL_CONFIG, "display": {"icon_style": style}})

    assert config.display.icon_style == style


def test_config_rejects_unknown_icon_style():
    with pytest.raises(ValidationError):
        Config.model_validate(
            {**MINIMAL_CONFIG, "display": {"icon_style": "unicode"}}
        )
