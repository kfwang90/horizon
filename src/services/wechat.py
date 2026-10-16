"""iLink delivery: QR login credentials, conversation context, and chunked Markdown."""

import base64
import json
import logging
import re
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Optional

import httpx
from rich.console import Console

from .._file_utils import _atomic_write_text
from ..ai.markdown_utils import clean_app_summary_markdown
from ..console_icons import get_icons
from ..models import WeChatConfig
from ..storage.manager import StorageManager
from ..url_security import UnsafeURLError, safe_request

logger = logging.getLogger(__name__)

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_CHANNEL_VERSION = "2.4.9"  # Reference client's protocol revision.
CONTEXT_MESSAGE_BUDGET = 10
SESSION_FILE = "wechat_session.json"
API_TIMEOUT = 15.0
LONG_POLL_TIMEOUT = 35.0
CONTEXT_REFRESH_TIMEOUT = 8.0

try:
    ILINK_BOT_AGENT = f"Horizon/{version('horizon')}"
except PackageNotFoundError:  # pragma: no cover
    ILINK_BOT_AGENT = "Horizon/0.1.0"


def _client_version_number(value: str) -> int:
    parts = [int(p) if p.isdigit() else 0 for p in value.split(".")[:3]]
    parts += [0] * (3 - len(parts))
    major, minor, patch = parts
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


def _random_wechat_uin() -> str:
    return base64.b64encode(str(secrets.randbits(32)).encode("ascii")).decode("ascii")


class ILinkError(Exception):
    def __init__(self, message: str, *, ret: int | None = None, errcode: int | None = None):
        super().__init__(message)
        self.ret = ret
        self.errcode = errcode

    @property
    def session_timeout(self) -> bool:
        return -14 in (self.ret, self.errcode)

    @property
    def budget_exhausted(self) -> bool:
        return self.ret == -2

    def hint(self) -> str:
        if self.session_timeout:
            return (
                "WeChat receive session timed out (-14); delivery may still work. "
                "If this persists, run 'horizon-wechat login --force'."
            )
        if self.budget_exhausted:
            return (
                "WeChat refused the message (-2), usually because the reply budget is exhausted. "
                "Send the bot a message, then run Horizon again."
            )
        return f"WeChat API error: {self}"


@dataclass
class WeChatSession:
    bot_token: str
    base_url: str = ILINK_BASE_URL
    bot_id: str = ""
    user_id: str = ""
    context_token: str = ""
    get_updates_buf: str = ""
    logged_in_at: str = ""
    context_updated_at: str = ""
    context_sends: int = 0

    @classmethod
    def load(cls, path: Path) -> Optional["WeChatSession"]:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("bot_token"):
            raise ValueError(f"WeChat session file is missing bot_token: {path}")
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The existing atomic writer creates its temporary file with mode 0600.
        _atomic_write_text(path, json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n")

    @property
    def ready(self) -> bool:
        return bool(self.bot_token and self.user_id and self.context_token)

    @property
    def remaining_budget(self) -> int:
        return max(0, CONTEXT_MESSAGE_BUDGET - self.context_sends)

    def update_from_message(self, message: dict[str, Any]) -> bool:
        if message.get("message_type") not in (None, 1):
            return False
        token, sender = message.get("context_token"), message.get("from_user_id")
        if not token or not sender or (self.user_id and sender != self.user_id):
            return False
        self.user_id = sender
        if token != self.context_token:
            self.context_sends = 0
        self.context_token = token
        self.context_updated_at = datetime.now(timezone.utc).isoformat()
        return True


class ILinkClient:
    """Wire format follows Tencent's openclaw-weixin reference client."""

    def __init__(self, base_url: str = ILINK_BASE_URL, bot_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.bot_token = bot_token

    async def _request(
        self, method: str, endpoint: str, payload: Optional[dict] = None,
        *, timeout: float = API_TIMEOUT, base_url: Optional[str] = None,
    ) -> dict[str, Any]:
        headers = {
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": str(_client_version_number(ILINK_CHANNEL_VERSION)),
        }
        kwargs: dict[str, Any] = {"headers": headers}
        if payload is not None:
            headers.update({
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "X-WECHAT-UIN": _random_wechat_uin(),
            })
            kwargs["content"] = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.bot_token:
            headers["Authorization"] = f"Bearer {self.bot_token}"
        url = f"{(base_url or self.base_url).rstrip('/')}/{endpoint}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await safe_request(client, method, url, **kwargs)
        if response.status_code >= 400:
            raise ILinkError(f"WeChat returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ILinkError("WeChat returned a non-JSON response") from exc
        if not isinstance(data, dict):
            raise ILinkError("WeChat returned an unexpected response")
        ret, errcode = data.get("ret"), data.get("errcode")
        if ret not in (None, 0) or errcode not in (None, 0):
            raise ILinkError(
                f"ret={ret}, errcode={errcode}: {data.get('errmsg', '')}",
                ret=ret, errcode=errcode,
            )
        return data

    async def _post(self, endpoint: str, payload: dict, timeout: float = API_TIMEOUT) -> dict:
        return await self._request("POST", endpoint, {
            **payload,
            "base_info": {"channel_version": ILINK_CHANNEL_VERSION, "bot_agent": ILINK_BOT_AGENT},
        }, timeout=timeout)

    async def get_bot_qrcode(self, local_tokens: Optional[list[str]] = None) -> dict:
        return await self._request(
            "POST", "ilink/bot/get_bot_qrcode?bot_type=3",
            {"local_token_list": list(local_tokens or [])[:10]},
        )

    async def get_qrcode_status(
        self, qrcode: str, *, verify_code: Optional[str] = None, base_url: Optional[str] = None,
    ) -> dict:
        params = {"qrcode": qrcode, **({"verify_code": verify_code} if verify_code else {})}
        try:
            return await self._request(
                "GET", f"ilink/bot/get_qrcode_status?{httpx.QueryParams(params)}",
                timeout=LONG_POLL_TIMEOUT + 5, base_url=base_url,
            )
        except httpx.TimeoutException:
            return {"status": "wait"}

    async def get_updates(self, get_updates_buf: str = "", *, timeout: float = LONG_POLL_TIMEOUT) -> dict:
        try:
            return await self._post(
                "ilink/bot/getupdates", {"get_updates_buf": get_updates_buf or ""}, timeout,
            )
        except httpx.TimeoutException:
            return {"msgs": [], "get_updates_buf": get_updates_buf}

    async def send_text(self, to_user_id: str, text: str, *, context_token: str) -> dict:
        return await self._post("ilink/bot/sendmessage", {"msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": f"horizon:{int(time.time() * 1000)}-{secrets.token_hex(4)}",
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }})


_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TOC_LINK_RE = re.compile(r"\[([^\]]+)\]\(#[^)]*\)")
_H5_H6_RE = re.compile(r"^#{5,6}[ \t]+", re.MULTILINE)
_CJK_RE = re.compile(r"[⺀-鿿가-힯豈-﫿]")
_STAR_ITALIC_RE = re.compile(r"(?<![*\w\\])\*(?!\*)([^*\n]+?)(?<!\\)\*(?![*\w])")
_UNDERSCORE_ITALIC_RE = re.compile(r"(?<![_\w\\])_(?!_)([^_\n]+?)(?<!\\)_(?![_\w])")


def format_markdown_for_wechat(value: str) -> str:
    """Flatten HTML and remove markup unsupported by WeChat's Markdown subset."""
    value = clean_app_summary_markdown(value)
    value = _IMAGE_RE.sub("", value)
    value = _TOC_LINK_RE.sub(r"\1", value)
    value = _H5_H6_RE.sub("", value)
    for pattern in (_STAR_ITALIC_RE, _UNDERSCORE_ITALIC_RE):
        value = pattern.sub(
            lambda m: m.group(1) if _CJK_RE.search(m.group(1)) else m.group(0), value,
        )
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _pack(units: list[str], sep: str, limit: int) -> list[str]:
    packed, current = [], ""
    for unit in units:
        candidate = unit if not current else f"{current}{sep}{unit}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                packed.append(current)
            current = unit
    if current:
        packed.append(current)
    return packed


def split_text_chunks(text: str, limit: int) -> list[str]:
    """Prefer paragraph/line boundaries; hard-split only an overlong line."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    result = []
    for paragraph in _pack(text.strip().split("\n\n"), "\n\n", limit):
        if len(paragraph) <= limit:
            result.append(paragraph)
        else:
            for line in _pack(paragraph.split("\n"), "\n", limit):
                result.extend(line[i:i + limit] for i in range(0, len(line), limit))
    return [chunk.strip() for chunk in result if chunk.strip()]


def plan_chunks(text: str, limit: int, lang: str, remaining: int = CONTEXT_MESSAGE_BUDGET) -> list[str]:
    text = format_markdown_for_wechat(text)
    chunks = split_text_chunks(text, limit)
    if chunks and remaining - len(chunks) <= 2:
        footer = "\n\n> " + (
            "回复任意消息，以补充微信推送额度。" if lang == "zh"
            else "Reply to the bot to renew the WeChat reply budget."
        )
        if len(footer) < limit:
            chunks = split_text_chunks(text, limit - len(footer))
            # Remind the reader before the estimated budget runs out, even on a partial delivery.
            chunks[min(len(chunks), max(remaining, 1)) - 1] += footer
    return chunks


class WeChatDeliveryStatus(str, Enum):
    DISABLED = "disabled"
    SKIPPED = "skipped"
    SUCCESS = "success"
    PLATFORM_FAILURE = "platform_failure"
    NETWORK_FAILURE = "network_failure"
    INTERNAL_FAILURE = "internal_failure"


@dataclass(frozen=True)
class WeChatDeliveryResult:
    status: WeChatDeliveryStatus
    detail: str | None = None
    chunks_sent: int = 0

    @property
    def sent(self) -> bool:
        return self.status == WeChatDeliveryStatus.SUCCESS


class WeChatNotifier:
    def __init__(self, config: WeChatConfig, storage: StorageManager, console=None, icons=None):
        self.config = config
        self.console = console if console is not None else Console(stderr=True)
        self.icons = icons if icons is not None else get_icons()
        self.session_path = Path(storage.data_dir) / SESSION_FILE
        self.session: Optional[WeChatSession] = None
        self._refreshed_at = 0.0
        self.reload_session()

    def reload_session(self) -> None:
        self.session = None
        try:
            self.session = WeChatSession.load(self.session_path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not load WeChat session: %s", exc)

    def client(self) -> ILinkClient:
        if self.session is None:
            raise RuntimeError("WeChat session is not loaded")
        return ILinkClient(self.session.base_url, self.session.bot_token)

    async def refresh_context(self, timeout: float = CONTEXT_REFRESH_TIMEOUT) -> bool:
        if self.session is None:
            return False
        data = await self.client().get_updates(self.session.get_updates_buf, timeout=timeout)
        self._refreshed_at = time.monotonic()
        changed = False
        for message in data.get("msgs") or []:
            if isinstance(message, dict) and self.session.update_from_message(message):
                changed = True
        cursor = data.get("get_updates_buf")
        if cursor and cursor != self.session.get_updates_buf:
            self.session.get_updates_buf = cursor
            changed = True
        if changed:
            self.session.save(self.session_path)
        return changed

    async def _refresh_before_send(self) -> None:
        if self._refreshed_at and time.monotonic() - self._refreshed_at < 60:
            return
        self.reload_session()
        try:
            await self.refresh_context()
        except ILinkError as exc:
            # A receive-session timeout does not necessarily invalidate sending.
            logger.warning("WeChat inbox check failed; using stored context. %s", exc.hint())
        except (httpx.HTTPError, UnsafeURLError) as exc:
            logger.warning("WeChat inbox check failed; using stored context: %s", exc)

    async def send_text(self, markdown_text: str, lang: str = "zh") -> WeChatDeliveryResult:
        if not self.config.enabled:
            return WeChatDeliveryResult(WeChatDeliveryStatus.DISABLED)
        sent = 0
        try:
            # Refresh before checking readiness: login may have saved credentials before
            # the user's first message arrived.
            await self._refresh_before_send()
            if self.session is None or not self.session.ready:
                hint = (
                    "Run 'horizon-wechat login' to connect."
                    if self.session is None else
                    "No context token yet. Send the bot a message and try again."
                )
                self.console.print(f"[yellow]{hint}[/yellow]")
                return WeChatDeliveryResult(WeChatDeliveryStatus.SKIPPED, hint)
            chunks = plan_chunks(markdown_text, self.config.chunk_size, lang, self.session.remaining_budget)
            if not chunks:
                return WeChatDeliveryResult(WeChatDeliveryStatus.SKIPPED, "empty message")
            for chunk in chunks:
                try:
                    await self.client().send_text(
                        self.session.user_id, chunk, context_token=self.session.context_token,
                    )
                except ILinkError as exc:
                    if exc.budget_exhausted:
                        self.session.context_sends = CONTEXT_MESSAGE_BUDGET
                        self.session.save(self.session_path)
                    raise
                sent += 1
                self.session.context_sends += 1
                self.session.save(self.session_path)
        except ILinkError as exc:
            status, detail = WeChatDeliveryStatus.PLATFORM_FAILURE, exc.hint()
        except (httpx.HTTPError, UnsafeURLError) as exc:
            status, detail = WeChatDeliveryStatus.NETWORK_FAILURE, str(exc)
        except Exception as exc:
            status, detail = WeChatDeliveryStatus.INTERNAL_FAILURE, str(exc)
        else:
            return WeChatDeliveryResult(WeChatDeliveryStatus.SUCCESS, chunks_sent=sent)
        logger.error("WeChat delivery failed after %d messages: %s", sent, detail)
        self.console.print(f"[red]WeChat delivery failed: {detail}[/red]")
        return WeChatDeliveryResult(status, detail, sent)

    async def send_daily_summary(self, summary: str, lang: str) -> WeChatDeliveryResult:
        if self.config.languages and lang not in self.config.languages:
            return WeChatDeliveryResult(WeChatDeliveryStatus.SKIPPED, "language filtered")
        self.console.print(f"{self.icons['wechat']} Sending {lang.upper()} WeChat notification...")
        result = await self.send_text(summary, lang)
        if result.sent:
            self.console.print(f"[green]WeChat notification sent ({result.chunks_sent} messages).[/green]")
        return result

    async def send_failure(self, date: str, error_message: str) -> WeChatDeliveryResult:
        return await self.send_text(
            f"**Horizon generation failed** ({date})\n\n{error_message}",
            (self.config.languages or ["zh"])[0],
        )
