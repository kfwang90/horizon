"""CLI configuration, QR login transitions, and offline preview."""

import asyncio
from types import SimpleNamespace

import pytest

from src.models import WeChatConfig
from src.services import wechat_cli
from src.services.wechat import ILINK_BASE_URL, WeChatSession
from src.storage.manager import StorageManager


@pytest.fixture(autouse=True)
def quiet_cli(monkeypatch):
    monkeypatch.setattr(wechat_cli, "configure_logging", lambda *a, **kw: None)
    monkeypatch.setattr(wechat_cli, "load_dotenv", lambda: None)


def use_config(monkeypatch, tmp_path, **wechat):
    calls = []
    config = SimpleNamespace(
        wechat=WeChatConfig(**wechat), ai=SimpleNamespace(languages=["zh"]),
        display=SimpleNamespace(icon_style="emoji"),
    )

    class Storage(StorageManager):
        def __init__(self, data_dir, config_path):
            calls.append((data_dir, config_path))
            super().__init__(str(tmp_path))

        def load_config(self):
            return config

    monkeypatch.setattr(wechat_cli, "StorageManager", Storage)
    return calls


def save_session(tmp_path, **kwargs):
    saved = WeChatSession(**{
        "bot_token": "test-private-token", "user_id": "u@im.wechat", "context_token": "test-context", **kwargs,
    })
    saved.save(tmp_path / "wechat_session.json")
    return saved


def test_status_forwards_paths_and_never_prints_credentials(monkeypatch, tmp_path, capsys):
    save_session(tmp_path, context_sends=4)
    calls = use_config(monkeypatch, tmp_path, enabled=True)
    monkeypatch.setattr("sys.argv", ["horizon-wechat", "-d", str(tmp_path), "-c", "config.json", "status"])
    wechat_cli.main()
    assert calls == [(str(tmp_path), "config.json")]
    output = capsys.readouterr().err
    assert "u@im.wechat" in output and "6/10" in output and "Ready to deliver" in output
    assert "test-private-token" not in output and "test-context" not in output


def test_missing_session_exits_with_login_hint(monkeypatch, tmp_path, capsys):
    use_config(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["horizon-wechat", "status"])
    with pytest.raises(SystemExit) as exc:
        wechat_cli.main()
    assert exc.value.code == 1 and "login" in capsys.readouterr().err


def test_dry_run_needs_neither_session_nor_network(monkeypatch, tmp_path, capsys):
    use_config(monkeypatch, tmp_path)

    def unexpected(*args, **kwargs):
        raise AssertionError("Offline preview must not construct a notifier or read credentials")

    monkeypatch.setattr(wechat_cli, "WeChatNotifier", unexpected)
    monkeypatch.setattr("sys.argv", ["horizon-wechat", "test", "--dry-run"])
    wechat_cli.main()
    assert "No message was sent" in capsys.readouterr().err


def test_sending_test_requires_enabled_config(monkeypatch, tmp_path):
    use_config(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["horizon-wechat", "test"])
    with pytest.raises(SystemExit) as exc:
        wechat_cli.main()
    assert exc.value.code == 1


class LoginClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.codes, self.polls = [], []

    async def get_bot_qrcode(self, tokens):
        self.codes.append(list(tokens))
        return {"qrcode": f"q{len(self.codes)}", "qrcode_img_content": "https://qr.example/login"}

    async def get_qrcode_status(self, code, **kwargs):
        self.polls.append({"code": code, **kwargs})
        return self.statuses.pop(0)


@pytest.fixture
def fast_login(monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr(wechat_cli.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(wechat_cli, "_render_qr", lambda _: None)


def test_login_redirect_expiry_and_verification(monkeypatch, fast_login):
    monkeypatch.setattr("builtins.input", lambda _: "1234")
    client = LoginClient([
        {"status": "scaned"},
        {"status": "scaned_but_redirect", "redirect_host": "sh.ilinkai.weixin.qq.com"},
        {"status": "expired"}, {"status": "need_verifycode"},
        {"status": "confirmed", "bot_token": "test-token"},
    ])
    result = asyncio.run(wechat_cli._wait_for_login(client, ["old"]))
    assert result["bot_token"] == "test-token" and client.codes == [["old"], ["old"]]
    assert client.polls[2]["base_url"] == "https://sh.ilinkai.weixin.qq.com"
    assert client.polls[-1] == {"code": "q2", "verify_code": "1234", "base_url": ILINK_BASE_URL}


@pytest.mark.parametrize("statuses", [
    [{"status": "verify_code_blocked"}], [{"status": "expired"}] * 4,
])
def test_login_stops_on_verification_failure_or_repeated_expiry(fast_login, statuses):
    assert asyncio.run(wechat_cli._wait_for_login(LoginClient(statuses), [])) is None


def test_force_login_withholds_old_token(monkeypatch, tmp_path):
    save_session(tmp_path)
    seen = []

    async def wait(client, tokens):
        seen.append(tokens)

    monkeypatch.setattr(wechat_cli, "_wait_for_login", wait)
    storage = StorageManager(str(tmp_path))
    asyncio.run(wechat_cli._run_login(WeChatConfig(), storage, False))
    assert seen == []
    with pytest.raises(SystemExit):
        asyncio.run(wechat_cli._run_login(WeChatConfig(), storage, True))
    assert seen == [[]]


def test_login_saves_first_context_without_consuming_reply_budget(monkeypatch, tmp_path, capsys):
    async def wait(client, tokens):
        return {"status": "confirmed", "bot_token": "test-token", "ilink_user_id": "u@im.wechat"}

    class Inbox:
        def __init__(self, *args):
            pass

        async def get_updates(self, cursor, *, timeout):
            return {"get_updates_buf": "next", "msgs": [{
                "message_type": 1, "from_user_id": "u@im.wechat", "context_token": "context",
            }]}

        async def send_text(self, *args, **kwargs):
            raise AssertionError("Login should not spend the reader's reply budget")

    monkeypatch.setattr(wechat_cli, "_wait_for_login", wait)
    monkeypatch.setattr("src.services.wechat.ILinkClient", Inbox)
    asyncio.run(wechat_cli._run_login(WeChatConfig(), StorageManager(str(tmp_path)), False))
    saved = WeChatSession.load(tmp_path / "wechat_session.json")
    assert saved.context_token == "context" and saved.get_updates_buf == "next"
    assert saved.context_sends == 0 and "Connected" in capsys.readouterr().err
