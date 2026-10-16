from types import SimpleNamespace

import pytest

from src.services import webhook_cli


def _fake_config(webhook=None, languages=("en",), icon_style="emoji"):
    return SimpleNamespace(
        webhook=webhook,
        ai=SimpleNamespace(languages=list(languages)),
        display=SimpleNamespace(icon_style=icon_style),
    )


def _silence(monkeypatch):
    monkeypatch.setattr(webhook_cli, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(webhook_cli.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(webhook_cli, "load_dotenv", lambda: None)


def test_data_dir_and_config_flags_are_forwarded_to_storage_manager(monkeypatch, tmp_path):
    data_dir = tmp_path / "state"
    config_path = tmp_path / "custom" / "horizon.json"
    storage_calls = []

    class RecordingStorage:
        def __init__(self, data_dir, config_path):
            storage_calls.append({"data_dir": data_dir, "config_path": config_path})

        def load_config(self):
            return _fake_config()

    _silence(monkeypatch)
    monkeypatch.setattr(webhook_cli, "StorageManager", RecordingStorage)
    monkeypatch.setattr(
        "sys.argv",
        ["horizon-webhook", "--data-dir", str(data_dir), "--config", str(config_path)],
    )

    with pytest.raises(SystemExit):
        webhook_cli.main()

    assert storage_calls == [{"data_dir": str(data_dir), "config_path": str(config_path)}]


def test_data_dir_and_config_default_to_data_directory(monkeypatch):
    storage_calls = []

    class RecordingStorage:
        def __init__(self, data_dir, config_path):
            storage_calls.append({"data_dir": data_dir, "config_path": config_path})

        def load_config(self):
            return _fake_config()

    _silence(monkeypatch)
    monkeypatch.setattr(webhook_cli, "StorageManager", RecordingStorage)
    monkeypatch.setattr("sys.argv", ["horizon-webhook"])

    with pytest.raises(SystemExit):
        webhook_cli.main()

    assert storage_calls == [{"data_dir": "data", "config_path": None}]


def test_log_level_flag_is_forwarded_to_configure_logging(monkeypatch):
    logging_calls = []

    class FixedStorage:
        def __init__(self, data_dir, config_path):
            pass

        def load_config(self):
            return _fake_config()

    monkeypatch.setattr(webhook_cli.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(webhook_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(webhook_cli, "StorageManager", FixedStorage)
    monkeypatch.setattr(
        webhook_cli,
        "configure_logging",
        lambda console, level=None: logging_calls.append(level),
    )
    monkeypatch.setattr("sys.argv", ["horizon-webhook", "--log-level", "debug"])

    with pytest.raises(SystemExit):
        webhook_cli.main()

    assert logging_calls == ["DEBUG"]


def test_exits_when_webhook_not_enabled(monkeypatch):
    class FixedStorage:
        def __init__(self, data_dir, config_path):
            pass

        def load_config(self):
            return _fake_config(webhook=None)

    _silence(monkeypatch)
    monkeypatch.setattr(webhook_cli, "StorageManager", FixedStorage)
    monkeypatch.setattr("sys.argv", ["horizon-webhook"])

    with pytest.raises(SystemExit) as exc_info:
        webhook_cli.main()

    assert exc_info.value.code == 1


def test_lang_dry_run_and_delivery_flags_are_forwarded_to_run_test(monkeypatch):
    run_calls = []

    async def fake_run_test(webhook_config, lang, dry_run, delivery_override=None, icon_style="emoji"):
        run_calls.append(
            {
                "webhook_config": webhook_config,
                "lang": lang,
                "dry_run": dry_run,
                "delivery_override": delivery_override,
                "icon_style": icon_style,
            }
        )

    webhook_config = SimpleNamespace(enabled=True)

    class FixedStorage:
        def __init__(self, data_dir, config_path):
            pass

        def load_config(self):
            return _fake_config(webhook=webhook_config, languages=["en", "zh"])

    _silence(monkeypatch)
    monkeypatch.setattr(webhook_cli, "StorageManager", FixedStorage)
    monkeypatch.setattr(webhook_cli, "_run_test", fake_run_test)
    monkeypatch.setattr(
        "sys.argv",
        ["horizon-webhook", "--lang", "zh", "--dry-run", "--delivery", "summary_and_items"],
    )

    webhook_cli.main()

    assert run_calls == [
        {
            "webhook_config": webhook_config,
            "lang": "zh",
            "dry_run": True,
            "delivery_override": "summary_and_items",
            "icon_style": "emoji",
        }
    ]


def test_lang_defaults_to_first_configured_language(monkeypatch):
    run_calls = []

    async def fake_run_test(webhook_config, lang, dry_run, delivery_override=None, icon_style="emoji"):
        run_calls.append(lang)

    class FixedStorage:
        def __init__(self, data_dir, config_path):
            pass

        def load_config(self):
            return _fake_config(webhook=SimpleNamespace(enabled=True), languages=["zh", "en"])

    _silence(monkeypatch)
    monkeypatch.setattr(webhook_cli, "StorageManager", FixedStorage)
    monkeypatch.setattr(webhook_cli, "_run_test", fake_run_test)
    monkeypatch.setattr("sys.argv", ["horizon-webhook"])

    webhook_cli.main()

    assert run_calls == ["zh"]
