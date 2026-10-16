from pathlib import Path
from types import SimpleNamespace

import pytest

from src import main as main_module


def test_missing_custom_config_reports_requested_path(monkeypatch, tmp_path):
    config_path = tmp_path / "custom" / "horizon.json"

    class MissingConfigStorage:
        def __init__(self, data_dir, config_path):
            self.config_path = Path(config_path)

        def load_config(self):
            raise FileNotFoundError

    output = []
    monkeypatch.setattr(main_module, "StorageManager", MissingConfigStorage)
    monkeypatch.setattr(main_module, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(
        main_module,
        "console",
        SimpleNamespace(
            print=lambda *args, **kwargs: output.append(" ".join(map(str, args)))
        ),
    )
    monkeypatch.setattr("sys.argv", ["horizon", "--config", str(config_path)])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    rendered = "\n".join(output)
    assert exc_info.value.code == 1
    assert str(config_path) in rendered
    assert "horizon-wizard" not in rendered


def test_data_dir_and_config_flags_are_forwarded_to_storage_manager(monkeypatch, tmp_path):
    data_dir = tmp_path / "state"
    config_path = tmp_path / "custom" / "horizon.json"
    storage_calls = []

    class RecordingStorage:
        def __init__(self, data_dir, config_path):
            storage_calls.append({"data_dir": data_dir, "config_path": config_path})

        def load_config(self):
            raise FileNotFoundError

    monkeypatch.setattr(main_module, "StorageManager", RecordingStorage)
    monkeypatch.setattr(main_module, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(main_module.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--data-dir", str(data_dir), "--config", str(config_path)],
    )

    with pytest.raises(SystemExit):
        main_module.main()

    assert storage_calls == [{"data_dir": str(data_dir), "config_path": str(config_path)}]


def test_data_dir_and_config_default_to_data_directory(monkeypatch):
    storage_calls = []

    class RecordingStorage:
        def __init__(self, data_dir, config_path):
            storage_calls.append({"data_dir": data_dir, "config_path": config_path})

        def load_config(self):
            raise FileNotFoundError

    monkeypatch.setattr(main_module, "StorageManager", RecordingStorage)
    monkeypatch.setattr(main_module, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(main_module.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr("sys.argv", ["horizon"])

    with pytest.raises(SystemExit):
        main_module.main()

    assert storage_calls == [{"data_dir": "data", "config_path": None}]


def test_log_level_flag_is_forwarded_to_configure_logging(monkeypatch, tmp_path):
    logging_calls = []

    class RecordingStorage:
        def __init__(self, data_dir, config_path):
            pass

        def load_config(self):
            raise FileNotFoundError

    monkeypatch.setattr(main_module, "StorageManager", RecordingStorage)
    monkeypatch.setattr(
        main_module,
        "configure_logging",
        lambda console, level=None: logging_calls.append(level),
    )
    monkeypatch.setattr(main_module.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr("sys.argv", ["horizon", "--log-level", "debug"])

    with pytest.raises(SystemExit):
        main_module.main()

    # The first call is the pre-argparse default; the second reflects the CLI flag.
    assert logging_calls[-1] == "DEBUG"
