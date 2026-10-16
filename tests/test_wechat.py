"""WeChat wire format, persisted context, and delivery failure handling."""

import asyncio
import base64
import json
import os
import sys

import httpx
import pytest
from pydantic import ValidationError

from src.models import WeChatConfig
from src.services import wechat
from src.services.wechat import (
    CONTEXT_MESSAGE_BUDGET, ILINK_BASE_URL, ILinkClient, ILinkError,
    WeChatDeliveryStatus, WeChatNotifier, WeChatSession,
    format_markdown_for_wechat, plan_chunks, split_text_chunks,
)
from src.storage.manager import StorageManager


def run(coro):
    return asyncio.run(coro)


def session(**overrides):
    return WeChatSession(**{
        "bot_token": "test-token", "user_id": "user@im.wechat",
        "context_token": "ctx-1", "get_updates_buf": "buf-1", **overrides,
    })


def message(token="ctx-2", sender="user@im.wechat", **extra):
    return {"message_type": 1, "from_user_id": sender, "context_token": token, **extra}


def test_config_defaults_and_limits():
    assert WeChatConfig().enabled is False
    assert WeChatConfig().chunk_size == 4000
    for limit in (0, 4001):
        with pytest.raises(ValidationError):
            WeChatConfig(chunk_size=limit)


def test_session_persistence_ignores_old_fields_and_keeps_credentials_private(tmp_path):
    path = tmp_path / "wechat_session.json"
    session(context_sends=3).save(path)
    if sys.platform != "win32":
        assert os.stat(path).st_mode & 0o777 == 0o600
    data = json.loads(path.read_text())
    data["style"] = "overview"  # Existing PR sessions still load after simplification.
    path.write_text(json.dumps(data))
    loaded = WeChatSession.load(path)
    assert loaded.ready and loaded.remaining_budget == 7
    assert loaded.bot_token == "test-token"
    assert WeChatSession.load(tmp_path / "missing.json") is None
    path.write_text('{"user_id": "u"}')
    with pytest.raises(ValueError):
        WeChatSession.load(path)


def test_only_the_bound_users_new_context_resets_budget():
    saved = session(context_sends=8)
    assert not saved.update_from_message(message(sender="someone-else"))
    assert not saved.update_from_message(message(message_type=2))
    assert not saved.update_from_message(message(sender=""))
    assert saved.update_from_message(message("ctx-1"))
    assert saved.context_sends == 8  # Replaying the same token grants no new budget.
    assert saved.update_from_message(message())
    assert saved.context_token == "ctx-2" and saved.context_sends == 0
    assert saved.context_updated_at
    unbound = session(user_id="", context_token="")
    assert unbound.update_from_message(message()) and unbound.ready


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, client, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, data = response
        return httpx.Response(status, json=data, request=httpx.Request(method, url))


def test_send_wire_format(monkeypatch):
    transport = Transport([(200, {"ret": 0})])
    monkeypatch.setattr(wechat, "safe_request", transport)
    run(ILinkClient("https://api.example/", "tok").send_text("u", "中文", context_token="ctx"))
    call = transport.calls[0]
    assert call["url"] == "https://api.example/ilink/bot/sendmessage"
    headers = call["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert headers["AuthorizationType"] == "ilink_bot_token"
    assert headers["iLink-App-Id"] == "bot"
    assert int(headers["iLink-App-ClientVersion"]) == (2 << 16) | (4 << 8) | 9
    assert base64.b64decode(headers["X-WECHAT-UIN"]).decode().isdigit()
    data = json.loads(call["content"])
    assert data["base_info"]["channel_version"] == "2.4.9"
    assert data["base_info"]["bot_agent"].startswith("Horizon/")
    msg = data["msg"]
    assert msg["to_user_id"] == "u" and msg["context_token"] == "ctx"
    assert msg["message_type"] == msg["message_state"] == 2
    assert msg["client_id"].startswith("horizon:")
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "中文"}}]


def test_login_endpoints_and_query_encoding(monkeypatch):
    transport = Transport([(200, {"qrcode": "q1"}), (200, {"status": "wait"})])
    monkeypatch.setattr(wechat, "safe_request", transport)
    client = ILinkClient()
    assert run(client.get_bot_qrcode(["old"]))["qrcode"] == "q1"
    run(client.get_qrcode_status("q 1", verify_code="12 34", base_url="https://sh.example"))
    first, second = transport.calls
    assert first["url"] == f"{ILINK_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
    assert json.loads(first["content"]) == {"local_token_list": ["old"]}
    assert "Authorization" not in first["headers"]
    url = httpx.URL(second["url"])
    assert second["method"] == "GET" and url.host == "sh.example"
    assert url.params["qrcode"] == "q 1" and url.params["verify_code"] == "12 34"


def test_client_distinguishes_timeouts_business_errors_and_http_errors(monkeypatch):
    transport = Transport([
        httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"),
        (200, {"ret": 0, "errcode": -14}), (200, {"ret": -2}),
        (500, {}), (200, []),
    ])
    monkeypatch.setattr(wechat, "safe_request", transport)
    client = ILinkClient(bot_token="tok")
    assert run(client.get_updates("cursor"))["get_updates_buf"] == "cursor"
    assert run(client.get_qrcode_status("qr")) == {"status": "wait"}
    with pytest.raises(ILinkError) as exc:
        run(client.get_updates())
    assert exc.value.session_timeout
    with pytest.raises(ILinkError) as exc:
        run(client.send_text("u", "hi", context_token="ctx"))
    assert exc.value.budget_exhausted
    for expected in ("HTTP 500", "unexpected response"):
        with pytest.raises(ILinkError, match=expected):
            run(client.get_updates())


def test_formatting_keeps_links_and_bold_but_flattens_html_and_cjk_italics():
    result = format_markdown_for_wechat(
        "# Title\n\n![alt](https://img.example/x.png)\n\n##### Deep\n\n"
        "[Entry](#item-1) · [site](https://example.com/x)\n\n"
        "*中文强调* *emphasis* _下划线_ _under_ **bold**\n\n"
        '<details><summary>Refs</summary><ul><li><a href="https://example.com/a">Link A</a></li></ul></details>'
    )
    assert "![" not in result and "#####" not in result and "Deep" in result
    assert "(#item" not in result and "[site](https://example.com/x)" in result
    assert "*中文强调*" not in result and "_下划线_" not in result
    assert "*emphasis*" in result and "_under_" in result and "**bold**" in result
    assert "<details>" not in result and "[Link A](https://example.com/a)" in result


def test_chunking_prefers_paragraphs_then_splits_long_lines():
    paragraphs = ["para " + "x" * 40] * 10
    chunks = split_text_chunks("\n\n".join(paragraphs), 120)
    assert all(len(chunk) <= 120 and chunk.startswith("para") for chunk in chunks)
    assert split_text_chunks("a" * 250, 100) == ["a" * 100, "a" * 100, "a" * 50]
    assert split_text_chunks("   ", 10) == []


@pytest.mark.parametrize("lang", ["zh", "en"])
@pytest.mark.parametrize("limit", [10, 120, 400])
def test_budget_reminder_never_exceeds_the_configured_chunk_size(lang, limit):
    chunks = plan_chunks("a" * 1000, limit, lang, remaining=2)
    assert all(len(chunk) <= limit for chunk in chunks)
    if limit >= 120:
        assert "> " in chunks[1]  # Reminder arrives before the estimated budget is exhausted.


class FakeClient:
    def __init__(self, updates=None, send_error=None, fail_after=None):
        self.updates = updates or {"msgs": []}
        self.send_error, self.fail_after = send_error, fail_after
        self.sent, self.polls = [], 0

    async def get_updates(self, cursor, *, timeout):
        self.polls += 1
        if isinstance(self.updates, Exception):
            raise self.updates
        return self.updates

    async def send_text(self, user, text, *, context_token):
        if self.send_error:
            raise self.send_error
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise ILinkError("prepare failed", ret=-2)
        self.sent.append((user, text, context_token))


def notifier(tmp_path, monkeypatch, saved=None, fake=None, **config):
    if saved:
        saved.save(tmp_path / "wechat_session.json")
    result = WeChatNotifier(WeChatConfig(**{"enabled": True, **config}), StorageManager(str(tmp_path)))
    fake = fake or FakeClient()
    monkeypatch.setattr(result, "client", lambda: fake)
    return result, fake


def test_send_summary_chunks_and_persists_budget_across_languages(tmp_path, monkeypatch):
    sender, fake = notifier(tmp_path, monkeypatch, session(), chunk_size=400)
    result = run(sender.send_daily_summary("a" * 900, "en"))
    assert result.sent and result.chunks_sent == 3
    assert all(user == "user@im.wechat" and token == "ctx-1" for user, _, token in fake.sent)
    assert WeChatSession.load(sender.session_path).context_sends == 3
    assert run(sender.send_daily_summary("中文日报", "zh")).sent
    assert fake.polls == 1
    assert WeChatSession.load(sender.session_path).context_sends == 4


def test_first_context_is_picked_up_before_readiness_check_and_chat_is_not_answered(tmp_path, monkeypatch):
    fake = FakeClient({"msgs": [message(item_list=[{"type": 1, "text_item": {"text": "帮助"}}])], "get_updates_buf": "buf-2"})
    sender, _ = notifier(tmp_path, monkeypatch, session(context_token=""), fake)
    assert run(sender.send_daily_summary("# Briefing", "en")).sent
    assert fake.sent == [("user@im.wechat", "# Briefing", "ctx-2")]
    saved = WeChatSession.load(sender.session_path)
    assert saved.get_updates_buf == "buf-2" and saved.context_sends == 1


def test_server_budget_error_stops_partial_delivery_and_new_context_recovers(tmp_path, monkeypatch):
    fake = FakeClient(fail_after=1)
    sender, _ = notifier(tmp_path, monkeypatch, session(context_sends=9), fake, chunk_size=200)
    result = run(sender.send_text("a" * 500, "en"))
    assert result.status == WeChatDeliveryStatus.PLATFORM_FAILURE and result.chunks_sent == 1
    assert "Reply to the bot" in fake.sent[0][1]
    assert WeChatSession.load(sender.session_path).context_sends == CONTEXT_MESSAGE_BUDGET
    fake.fail_after = None
    fake.updates = {"msgs": [message()]}
    run(sender.refresh_context())
    assert run(sender.send_text("next")).sent
    assert WeChatSession.load(sender.session_path).context_sends == 1


def test_stored_budget_is_only_an_estimate_server_can_allow_more(tmp_path, monkeypatch):
    sender, fake = notifier(tmp_path, monkeypatch, session(context_sends=10))
    assert run(sender.send_text("next")).sent
    assert len(fake.sent) == 1


def test_receive_timeout_does_not_block_delivery(tmp_path, monkeypatch):
    sender, fake = notifier(tmp_path, monkeypatch, session(), FakeClient(ILinkError("stale", errcode=-14)))
    assert run(sender.send_failure("2026-09-21", "generation failed")).sent
    assert "generation failed" in fake.sent[0][1]


@pytest.mark.parametrize("error,status", [
    (ILinkError("expired", errcode=-14), WeChatDeliveryStatus.PLATFORM_FAILURE),
    (httpx.ConnectError("down"), WeChatDeliveryStatus.NETWORK_FAILURE),
    (RuntimeError("unexpected"), WeChatDeliveryStatus.INTERNAL_FAILURE),
])
def test_delivery_failure_results(tmp_path, monkeypatch, error, status):
    sender, _ = notifier(tmp_path, monkeypatch, session(), FakeClient(send_error=error))
    result = run(sender.send_text("briefing"))
    assert result.status == status and result.chunks_sent == 0


def test_disabled_filtered_missing_and_stale_sessions_do_not_send(tmp_path, monkeypatch):
    sender, fake = notifier(tmp_path, monkeypatch, session(), enabled=False)
    assert run(sender.send_text("x")).status == WeChatDeliveryStatus.DISABLED
    assert fake.polls == 0
    sender.config.enabled = True
    sender.config.languages = ["zh"]
    assert run(sender.send_daily_summary("x", "en")).status == WeChatDeliveryStatus.SKIPPED
    assert fake.polls == 0
    sender.session_path.unlink()
    assert run(sender.send_text("x")).status == WeChatDeliveryStatus.SKIPPED
    assert sender.session is None and not fake.sent
