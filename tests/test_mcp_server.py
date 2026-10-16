from src.mcp import server


def test_log_level_flag_is_forwarded_to_configure_logging(monkeypatch):
    logging_calls = []

    monkeypatch.setattr(
        server,
        "configure_logging",
        lambda console, level=None: logging_calls.append(level),
    )
    monkeypatch.setattr(server.mcp, "run", lambda: None)
    monkeypatch.setattr("sys.argv", ["horizon-mcp", "--log-level", "debug"])

    server.main()

    assert logging_calls == ["DEBUG"]


def test_log_level_defaults_to_info(monkeypatch):
    logging_calls = []

    monkeypatch.setattr(
        server,
        "configure_logging",
        lambda console, level=None: logging_calls.append(level),
    )
    monkeypatch.setattr(server.mcp, "run", lambda: None)
    monkeypatch.setattr("sys.argv", ["horizon-mcp"])

    server.main()

    assert logging_calls == ["INFO"]


def test_main_starts_the_mcp_server(monkeypatch):
    run_calls = []

    monkeypatch.setattr(server, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(server.mcp, "run", lambda: run_calls.append(True))
    monkeypatch.setattr("sys.argv", ["horizon-mcp"])

    server.main()

    assert run_calls == [True]
