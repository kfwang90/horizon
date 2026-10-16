"""Connect a WeChat account and preview or test iLink delivery."""

import argparse
import asyncio
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .._cli import add_data_dir_arguments, add_log_level_argument
from ..console_icons import get_icons
from ..logging_config import configure_logging
from ..models import WeChatConfig
from ..storage.manager import ConfigError, StorageManager
from .wechat import (
    CONTEXT_MESSAGE_BUDGET,
    ILINK_BASE_URL,
    LONG_POLL_TIMEOUT,
    SESSION_FILE,
    ILinkClient,
    ILinkError,
    WeChatNotifier,
    WeChatSession,
    plan_chunks,
)

console = Console(stderr=True)
QR_LOGIN_TIMEOUT = 480.0
MAX_QR_REFRESHES = 3
FIRST_MESSAGE_WAIT = 300.0


def _render_qr(content: str) -> None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(content)
        qr.make(fit=True)
        buffer = io.StringIO()
        qr.print_ascii(out=buffer, invert=True)
        console.print(buffer.getvalue(), markup=False, highlight=False)
    except Exception:  # pragma: no cover - terminal/library dependent
        console.print("[yellow]QR rendering failed. Open the link on another screen.[/yellow]")
    console.print(content, markup=False, highlight=False)


async def _wait_for_login(client: ILinkClient, local_tokens: list[str]) -> dict | None:
    qr = await client.get_bot_qrcode(local_tokens)
    if not qr.get("qrcode") or not qr.get("qrcode_img_content"):
        raise ValueError("WeChat did not return a login QR code")
    console.print("Scan with WeChat and confirm:")
    _render_qr(qr["qrcode_img_content"])
    base_url, verify_code = ILINK_BASE_URL, None
    refreshes = 0
    scanned = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + QR_LOGIN_TIMEOUT
    while loop.time() < deadline:
        status = await client.get_qrcode_status(qr["qrcode"], verify_code=verify_code, base_url=base_url)
        state = status.get("status")
        if state in ("confirmed", "binded_redirect"):
            return status
        if state == "scaned" and not scanned:
            console.print("Scanned. Confirm on your phone...")
            scanned = True
        elif state == "scaned_but_redirect":
            host = status.get("redirect_host")
            if host:
                base_url = host if host.startswith("http") else f"https://{host}"
        elif state == "need_verifycode":
            verify_code = input("Verification code shown in WeChat: ").strip() or None
        elif state == "verify_code_blocked":
            console.print("[red]Too many failed verification attempts.[/red]")
            return None
        elif state == "expired":
            refreshes += 1
            if refreshes > MAX_QR_REFRESHES:
                break
            qr = await client.get_bot_qrcode(local_tokens)
            if not qr.get("qrcode") or not qr.get("qrcode_img_content"):
                raise ValueError("WeChat did not return a replacement QR code")
            _render_qr(qr["qrcode_img_content"])
            base_url, verify_code, scanned = ILINK_BASE_URL, None, False
        await asyncio.sleep(1)
    console.print("[red]Login timed out. Run 'horizon-wechat login' again.[/red]")
    return None


async def _run_login(config: WeChatConfig, storage: StorageManager, force: bool) -> None:
    path = Path(storage.data_dir) / SESSION_FILE
    existing = None
    try:
        existing = WeChatSession.load(path)
    except (OSError, ValueError, TypeError):
        console.print("[yellow]Ignoring unreadable WeChat session.[/yellow]")
    if existing and existing.ready and not force:
        console.print("Already connected. Use 'login --force' to log in again.")
        return

    # Omitting the saved token makes --force request a fresh session.
    tokens = [existing.bot_token] if existing and not force else []
    status = await _wait_for_login(ILinkClient(), tokens)
    if status is None:
        sys.exit(1)
    if status.get("status") != "binded_redirect" or existing is None:
        if not status.get("bot_token"):
            raise ValueError("WeChat login did not return a bot token")
        WeChatSession(
            bot_token=status["bot_token"],
            base_url=(status.get("baseurl") or ILINK_BASE_URL).rstrip("/"),
            bot_id=status.get("ilink_bot_id") or "",
            user_id=status.get("ilink_user_id") or "",
            logged_in_at=datetime.now(timezone.utc).isoformat(),
        ).save(path)

    console.print("Send the bot a message in WeChat to enable delivery. Waiting up to 5 minutes...")
    notifier = WeChatNotifier(config, storage, console=console)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + FIRST_MESSAGE_WAIT
    while loop.time() < deadline:
        await notifier.refresh_context(timeout=LONG_POLL_TIMEOUT)
        if notifier.session and notifier.session.ready:
            console.print(f"[green]Connected.[/green] Session saved to {path}")
            if not config.enabled:
                console.print("Set wechat.enabled = true to send daily briefings.")
            return
        await asyncio.sleep(1)
    console.print("Send the bot a message later, then run 'horizon-wechat status --refresh'.")


async def _run_status(config: WeChatConfig, storage: StorageManager, refresh: bool) -> None:
    notifier = WeChatNotifier(config, storage, console=console)
    if notifier.session is None:
        console.print(f"No session at {notifier.session_path}. Run 'horizon-wechat login'.")
        sys.exit(1)
    if refresh:
        await notifier.refresh_context(timeout=LONG_POLL_TIMEOUT)
    session = notifier.session
    for label, value in (
        ("Session file", notifier.session_path),
        ("Enabled", config.enabled),
        ("User", session.user_id or "unknown"),
        ("Context", "present" if session.context_token else "missing"),
        ("Replies left", f"{session.remaining_budget}/{CONTEXT_MESSAGE_BUDGET} (estimated)"),
    ):
        console.print(f"{label}: {value}", markup=False)
    console.print("Ready to deliver." if session.ready else "Send the bot a message, then rerun with --refresh.")


async def _run_test(config: WeChatConfig, storage: StorageManager, lang: str, dry_run: bool, icons=None) -> None:
    if config.languages and lang not in config.languages:
        console.print(f"Language '{lang}' is filtered out by wechat.languages.")
        return
    sample = (
        "# Horizon 微信推送测试\n\n这是一条测试消息。\n\n[Horizon](https://github.com/Thysrael/Horizon)"
        if lang == "zh" else
        "# Horizon WeChat test\n\nThis is a test message.\n\n[Horizon](https://github.com/Thysrael/Horizon)"
    )
    if dry_run:
        # A preview neither loads credentials nor connects to WeChat.
        for index, chunk in enumerate(plan_chunks(sample, config.chunk_size, lang), start=1):
            console.print(Panel(chunk, title=f"Message {index}"))
        console.print("Dry run complete. No message was sent.")
        return
    if not config.enabled:
        console.print("Set wechat.enabled = true, or use --dry-run to preview.")
        sys.exit(1)
    result = await WeChatNotifier(config, storage, console=console, icons=icons).send_daily_summary(sample, lang)
    if not result.sent:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect Horizon to WeChat and test delivery")
    add_data_dir_arguments(parser)
    add_log_level_argument(parser)
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Scan a QR code with WeChat")
    login.add_argument("--force", action="store_true", help="Request a fresh session")
    status = commands.add_parser("status", help="Show connection status")
    status.add_argument("--refresh", action="store_true", help="Poll for a new conversation context")
    test = commands.add_parser("test", help="Send or preview a test message")
    test.add_argument("--lang", help="Defaults to the first configured AI language")
    test.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()
    configure_logging(console, level=args.log_level)
    try:
        load_dotenv()
        storage = StorageManager(data_dir=args.data_dir, config_path=args.config)
        config = storage.load_config()
        wechat = config.wechat or WeChatConfig()
        if args.command == "login":
            asyncio.run(_run_login(wechat, storage, args.force))
        elif args.command == "status":
            asyncio.run(_run_status(wechat, storage, args.refresh))
        else:
            lang = args.lang or (config.ai.languages or ["en"])[0]
            asyncio.run(_run_test(wechat, storage, lang, args.dry_run, get_icons(config.display.icon_style)))
    except FileNotFoundError:
        console.print("Configuration file not found. Run 'uv run horizon-wizard' to create it.")
        sys.exit(1)
    except (ConfigError, ILinkError) as exc:
        console.print(exc.hint() if isinstance(exc, ILinkError) else str(exc), markup=False)
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("Interrupted.")
    except Exception as exc:
        console.print(f"WeChat error: {exc}", markup=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
