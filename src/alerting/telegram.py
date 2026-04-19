"""Telegram bot alerter for Sahayak — prevents silent failures.

The alerter is intentionally fire-and-forget:
  - Never raises exceptions (it is invoked from error handlers)
  - Degrades gracefully when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set
  - Rate-limited internally (max 1 alert per 10 s per alert type) to avoid
    flooding the channel during cascading failures

Configuration (via .env or environment):
    TELEGRAM_BOT_TOKEN  — bot token from @BotFather
    TELEGRAM_CHAT_ID    — numeric chat/channel ID to post to

Threat model note: the bot token is a secret. Never log it. The module
reads it fresh from os.environ on each call so it can be rotated without
restart.

Usage::

    from src.alerting.telegram import alert, alert_startup, alert_error

    await alert("⚠️ Custom message")
    alert_sync("📣 From sync context")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal rate-limiting state
# ---------------------------------------------------------------------------
_RATE_WINDOW_SECS = 10          # min seconds between same-type alerts
_last_sent: dict[str, float] = {}   # alert_type → last send timestamp
_MAX_MSG_LEN = 4096             # Telegram hard limit


# ---------------------------------------------------------------------------
# Core send
# ---------------------------------------------------------------------------

async def _send(text: str) -> None:
    """Low-level: POST to Telegram sendMessage API.  Never raises."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        # Not configured — silently skip (no log spam)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:_MAX_MSG_LEN],
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        import urllib.request, urllib.error, json as _json
        req_data = _json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Use a short timeout — we're in an async context but this is sync IO.
        # We run it in a thread so as not to block the event loop.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_request, req)
    except Exception as exc:
        # Never raise from an alerter
        logger.debug("Telegram alert failed (non-fatal): %s", exc)


def _do_request(req: Any) -> None:
    """Execute the HTTP request (runs in thread pool executor)."""
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except urllib.error.URLError as exc:
        logger.debug("Telegram HTTP error: %s", exc)
    except Exception as exc:
        logger.debug("Telegram send exception: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def alert(text: str, alert_type: str = "general") -> None:
    """Send an alert to the configured Telegram channel.

    Rate-limited: the same *alert_type* is suppressed for 10 s after each send
    to prevent flooding during cascading failures.

    Args:
        text: Markdown-formatted message (Telegram Markdown v1).
        alert_type: Deduplication key (e.g. "matching_error", "startup").
    """
    now = time.monotonic()
    if now - _last_sent.get(alert_type, 0) < _RATE_WINDOW_SECS:
        return  # Rate-limited — skip
    _last_sent[alert_type] = now
    await _send(text)


def alert_sync(text: str, alert_type: str = "general") -> None:
    """Synchronous wrapper — schedules alert on the running event loop if available,
    otherwise creates a new one.  Safe to call from sync exception handlers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(alert(text, alert_type))
        else:
            loop.run_until_complete(alert(text, alert_type))
    except Exception:
        pass  # Never raise from an alerter


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

async def alert_startup(version: str = "1.0", host: str = "localhost", port: int = 8000) -> None:
    """Alert when the server starts — confirms the bot is connected."""
    await alert(
        f"🟢 *Sahayak started*\n"
        f"Version: `{version}` | `{host}:{port}`\n"
        f"Telegram alerting is active.",
        alert_type="startup",
    )


async def alert_shutdown() -> None:
    """Alert when the server shuts down."""
    await alert("🔴 *Sahayak stopped* — server process terminated.", alert_type="shutdown")


async def alert_matching_error(session_id: str, error: Exception) -> None:
    """Alert on matching engine failures."""
    await alert(
        f"⚠️ *Matching engine error*\n"
        f"Session: `{session_id[:8]}…`\n"
        f"`{type(error).__name__}: {str(error)[:200]}`",
        alert_type="matching_error",
    )


async def alert_repeated_ws_failure(client_ip: str, count: int) -> None:
    """Alert when a client generates many WebSocket errors (possible abuse)."""
    await alert(
        f"🚨 *Repeated WebSocket errors*\n"
        f"IP: `{client_ip}` | Count: `{count}`\n"
        f"Consider rate-limiting or blocking this IP.",
        alert_type=f"ws_failure_{client_ip}",
    )


async def alert_rate_limit_breach(client_ip: str) -> None:
    """Alert when a client exceeds the rate limit."""
    await alert(
        f"🚨 *Rate limit breached*\n"
        f"IP: `{client_ip}` is being throttled.",
        alert_type=f"rate_limit_{client_ip}",
    )


async def alert_slow_response(duration_s: float, session_id: str) -> None:
    """Alert when a request takes unusually long (possible resource exhaustion)."""
    await alert(
        f"🐢 *Slow response detected*\n"
        f"Session: `{session_id[:8]}…` | Duration: `{duration_s:.1f}s`",
        alert_type="slow_response",
    )
