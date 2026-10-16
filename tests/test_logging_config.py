import logging

from rich.console import Console

from src.logging_config import configure_logging


def test_configure_logging_forces_shared_console(monkeypatch):
    calls = []
    console = Console(stderr=True)
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: calls.append(kwargs))

    configure_logging(console)

    assert len(calls) == 1
    assert calls[0]["force"] is True
    assert calls[0]["level"] == logging.WARNING
    assert calls[0]["handlers"][0].console is console
