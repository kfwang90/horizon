import argparse

import pytest

from src._cli import add_data_dir_arguments, add_log_level_argument


def _parser(*builders) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    for builder in builders:
        builder(parser)
    return parser


def test_log_level_defaults_to_warning():
    args = _parser(add_log_level_argument).parse_args([])

    assert args.log_level == "WARNING"


@pytest.mark.parametrize("flag", ["-l", "--log-level"])
def test_log_level_accepts_short_and_long_flags(flag):
    args = _parser(add_log_level_argument).parse_args([flag, "info"])

    assert args.log_level == "INFO"


def test_log_level_is_case_insensitive():
    args = _parser(add_log_level_argument).parse_args(["--log-level", "dEbUg"])

    assert args.log_level == "DEBUG"


def test_log_level_rejects_unknown_value():
    with pytest.raises(SystemExit):
        _parser(add_log_level_argument).parse_args(["--log-level", "NOPE"])


def test_data_dir_arguments_default_to_data_and_none_config():
    args = _parser(add_data_dir_arguments).parse_args([])

    assert args.data_dir == "data"
    assert args.config is None


@pytest.mark.parametrize(
    ("flags", "expected_data_dir", "expected_config"),
    [
        (["-d", "/tmp/custom"], "/tmp/custom", None),
        (["--data-dir", "/tmp/custom"], "/tmp/custom", None),
        (["-c", "/tmp/custom.json"], "data", "/tmp/custom.json"),
        (["--config", "/tmp/custom.json"], "data", "/tmp/custom.json"),
    ],
)
def test_data_dir_arguments_accept_short_and_long_flags(flags, expected_data_dir, expected_config):
    args = _parser(add_data_dir_arguments).parse_args(flags)

    assert args.data_dir == expected_data_dir
    assert args.config == expected_config


def test_both_helpers_can_be_combined_on_one_parser():
    args = _parser(add_data_dir_arguments, add_log_level_argument).parse_args(
        ["-d", "/tmp/custom", "-c", "/tmp/custom.json", "-l", "error"]
    )

    assert args.data_dir == "/tmp/custom"
    assert args.config == "/tmp/custom.json"
    assert args.log_level == "ERROR"
