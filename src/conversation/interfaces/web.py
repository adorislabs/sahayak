"""FastAPI web interface for CBC Part 5 — citizen-friendly conversational UI.

Provides a bilingual (English/Hindi) chat interface with:
- WebSocket real-time conversation
- HTTP POST fallback
- Per-message "Details" panel (explainability audit drawer)
- Warm, approachable design for low-literacy Indian citizens
- Mobile-first, large tap targets, high-contrast text

Usage::

    uvicorn src.conversation.interfaces.web:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# Load .env before anything reads env vars
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.conversation.config import DEFAULT_RULE_BASE_PATH
from src.conversation.engine import ConversationEngine
from src.alerting.telegram import alert_startup, alert_rate_limit_breach, alert_repeated_ws_failure

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security configuration
# ---------------------------------------------------------------------------
_MAX_MESSAGE_LEN = 2_000          # characters — reject anything longer
_MAX_BODY_BYTES   = 4_194_304     # 4 MB request body cap (Vercel allows ~4.5 MB)
_RATE_LIMIT_RPM   = 30            # max requests per IP per minute
_RATE_LIMIT_WS_PER_IP = 5        # max simultaneous WS connections per IP

# ---------------------------------------------------------------------------
# Security middleware — headers + rate limiting
# ---------------------------------------------------------------------------

# In-memory rate-limit counters: ip → [timestamp, ...]
_rate_buckets: dict[str, list[float]] = defaultdict(list)
# WS connection counter per IP
_ws_connections: dict[str, int] = defaultdict(int)
# WS error counter per IP (for abuse detection)
_ws_errors: dict[str, int] = defaultdict(int)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every HTTP response."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Deny framing (clickjacking protection)
        response.headers["X-Frame-Options"] = "DENY"
        # Force HTTPS in production (1 year, include subdomains)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        # Strict Content-Security-Policy
        # allow same-origin scripts + Google Fonts (for UI); no eval, no inline script
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "   # inline needed for embedded HTML
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "connect-src 'self' ws: wss:; "
            "img-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy — disable unused browser APIs
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter for HTTP routes."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Skip rate-limiting for WebSocket upgrades (handled per-connection below)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        client_ip = _get_client_ip(request)
        now = time.monotonic()
        bucket = _rate_buckets[client_ip]
        # Slide window: keep only timestamps within the last 60 s
        _rate_buckets[client_ip] = [t for t in bucket if now - t < 60]
        _rate_buckets[client_ip].append(now)

        if len(_rate_buckets[client_ip]) > _RATE_LIMIT_RPM:
            asyncio.ensure_future(alert_rate_limit_breach(client_ip))
            return JSONResponse(
                {"error": "Too many requests. Please wait a moment."},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        # Enforce body size limit for POST requests
        if request.method == "POST":
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > _MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": "Request body too large."},
                    status_code=413,
                )

        return await call_next(request)


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # Take the first (leftmost) IP — the actual client
        ip = forwarded.split(",")[0].strip()
        # Validate it looks like an IP to prevent log injection
        if re.match(r"^[\d.]+$|^[0-9a-fA-F:]+$", ip):
            return ip
    return getattr(request.client, "host", "unknown")


def _sanitise_input(text: str) -> str:
    """Sanitise user input: strip HTML, normalise whitespace, enforce length cap.

    This prevents:
      - XSS via reflected user input in error messages
      - Log injection (strip control characters)
      - Prompt injection via HTML/script tags embedded in messages
    """
    # Decode HTML entities first (prevent double-encoding bypass)
    text = html.unescape(text)
    # Strip all HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Strip control characters (but keep standard whitespace)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Collapse multiple whitespace
    text = re.sub(r" {3,}", "  ", text)
    # Enforce length cap
    return text[:_MAX_MESSAGE_LEN]


def _get_thinking_hint(message: str) -> str:
    """Return a short (3-5 word) hint about what the bot is processing."""
    lower = message.lower()
    if any(w in lower for w in ["lakh", "hazar", "income", "salary", "earning", "rupay", "paisa", "kamata", "kamate"]):
        return "Parsing income details…"
    if any(w in lower for w in [" sc", " st", " obc", "dalit", "adivasi", "caste", "jati", "category", "varg"]):
        return "Noting community category…"
    if any(w in lower for w in ["bpl", "ration", "aadhaar", "aadhar", "document", "card"]):
        return "Checking document details…"
    if any(w in lower for w in ["state", "district", "village", "gaon", "city", "shahar", "pradesh", "from"]):
        return "Identifying your location…"
    if any(w in lower for w in ["age", " saal", "years old", "born", "umar"]):
        return "Noting your age…"
    if any(w in lower for w in ["farmer", "kisaan", "kisan", "agriculture", "khet", "land", "zameen"]):
        return "Noting occupation…"
    if any(w in lower for w in ["family", "parivar", "member", "wife", "husband", "children", "bache"]):
        return "Understanding family details…"
    if any(w in lower for w in ["check", "eligib", "patrata", "yojana", "scheme", "apply"]):
        return "Running eligibility check…"
    return "Understanding your message…"


def _trim_audit_for_wire(turn_audit: dict) -> dict:
    """Trim turn_audit before sending over WebSocket.

    The full matching_result can be several MB (3,000+ schemes × rule traces).
    We send only the schemes the UI actually renders (eligible + near-miss),
    and strip rule_evaluations down to the first 8 per scheme.
    Ineligible schemes are replaced with lightweight stubs.
    """
    if not turn_audit or "matching_result" not in turn_audit:
        return turn_audit

    trimmed = {k: v for k, v in turn_audit.items() if k != "matching_result"}
    mr = turn_audit["matching_result"]
    if not isinstance(mr, dict):
        trimmed["matching_result"] = mr
        return trimmed

    _KEEP_STATUSES = {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS", "REQUIRES_PREREQUISITE"}
    full_schemes = mr.get("scheme_results", [])

    # Separate near-miss from eligible, cap near-miss to top 50 by confidence (H5)
    eligible_like = [s for s in full_schemes
                     if s.get("status") in {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "REQUIRES_PREREQUISITE"}]
    near_miss = sorted(
        [s for s in full_schemes if s.get("status") == "NEAR_MISS"],
        key=lambda s: s.get("confidence", 0.0),
        reverse=True,
    )[:50]
    keep_ids = {s.get("id") for s in eligible_like + near_miss}

    # Keep full data for eligible/near-miss; lightweight stub for others
    trimmed_schemes = []
    for s in full_schemes:
        if s.get("id") in keep_ids:
            # Keep but limit rule_evaluations to top 8
            s2 = dict(s)
            if "rule_evaluations" in s2:
                s2["rule_evaluations"] = s2["rule_evaluations"][:8]
            trimmed_schemes.append(s2)
        else:
            # Minimal stub — just enough for count/status display
            trimmed_schemes.append({
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "status": s.get("status", ""),
                "confidence": s.get("confidence", 0.0),
            })

    trimmed["matching_result"] = {k: v for k, v in mr.items() if k != "scheme_results"}
    trimmed["matching_result"]["scheme_results"] = trimmed_schemes
    return trimmed


# ---------------------------------------------------------------------------
# FastAPI app setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sahayak — Welfare Scheme Eligibility",
    description="Conversational welfare scheme eligibility checker for Indian citizens",
    version="1.0.0",
    # Disable auto-generated docs in production to reduce attack surface
    docs_url=None,
    redoc_url=None,
)

# Wire security middleware (order matters: rate limit before headers)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# Custom exception handler — never leak stack traces to clients
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s: %s", request.url.path, exc)
    return JSONResponse(
        {"error": "Something went wrong. Please try again."},
        status_code=500,
    )


_engine = ConversationEngine(rule_base_path=DEFAULT_RULE_BASE_PATH)

_static_dir = Path(__file__).parent / "templates" / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Mount public directory for HTML files (ambiguity maps, report, etc.)
# Try multiple paths since Vercel's file layout varies
_public_dir = None
for _candidate in [
    Path(__file__).resolve().parent.parent.parent.parent / "public",
    Path.cwd() / "public",
    Path("/var/task/public"),
    Path("/var/task/user/public"),
    Path(os.path.dirname(os.path.abspath(__file__))).parent.parent.parent / "public",
]:
    if _candidate.exists():
        _public_dir = _candidate
        break
if _public_dir is None:
    _public_dir = Path("/var/task/public")  # fallback
logger.info("Public dir resolved to: %s (exists=%s)", _public_dir, _public_dir.exists())

# Pre-load public files into memory for reliable serving on Vercel
_PUBLIC_FILES: dict[str, bytes] = {}
_PUBLIC_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".js": "application/javascript",
}
if _public_dir.exists():
    for _pf in _public_dir.iterdir():
        if _pf.is_file() and _pf.suffix in _PUBLIC_TYPES:
            try:
                _PUBLIC_FILES[_pf.name] = _pf.read_bytes()
                logger.info("Loaded public file: %s (%d bytes)", _pf.name, len(_PUBLIC_FILES[_pf.name]))
            except Exception as e:
                logger.warning("Failed to load public file %s: %s", _pf.name, e)
    try:
        app.mount("/public", StaticFiles(directory=str(_public_dir)), name="public-static")
    except Exception:
        pass
else:
    logger.warning("Public dir NOT found. Tried all candidate paths.")


# ---------------------------------------------------------------------------
# Startup/shutdown events — Telegram notifications
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _on_startup() -> None:
    asyncio.ensure_future(alert_startup(version="1.0", port=8000))
    logger.info("Sahayak started — Telegram alerting armed")


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    from src.alerting.telegram import alert_shutdown
    await alert_shutdown()


# ---------------------------------------------------------------------------
# Inline HTML — warm, citizen-friendly, bilingual
# ---------------------------------------------------------------------------

_CHAT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sahayak — Find Your Government Benefits</title>
    <meta name="description" content="Find out which government welfare schemes you qualify for. Free, simple, and available in Hindi.">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&family=Noto+Sans+Devanagari:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            /* Warm, earthy palette — welcoming for first-time users */
            --saffron:      #F4880A;
            --saffron-pale: #FEF3E2;
            --saffron-mid:  #FDDBA8;
            --india-green:  #138808;
            --green-pale:   #E7F5E7;
            --bg:           #FAFAF8;
            --bg-card:      #FFFFFF;
            --bg-raised:    #F5F0E8;
            --text-dark:    #1A1208;
            --text-body:    #3D3320;
            --text-soft:    #7A6A50;
            --text-hint:    #B0A08A;
            --border:       #E8DDD0;
            --border-focus: #F4880A;
            --success:      #138808;
            --success-pale: #E7F5E7;
            --warning:      #D97706;
            --warning-pale: #FEF3CD;
            --danger:       #DC2626;
            --danger-pale:  #FEF2F2;
            --info:         #1D4ED8;
            --info-pale:    #EFF6FF;
            --font:         'Nunito', 'Noto Sans Devanagari', system-ui, sans-serif;
            --font-deva:    'Noto Sans Devanagari', 'Nunito', sans-serif;
            --font-mono:    'JetBrains Mono', monospace;
            --radius:       16px;
            --radius-sm:    10px;
            --shadow:       0 2px 12px rgba(60,40,0,0.08);
            --shadow-lg:    0 8px 32px rgba(60,40,0,0.14);
            --panel-width:  440px;
        }

        html { font-size: 17px; }

        body {
            font-family: var(--font);
            background: var(--bg);
            color: var(--text-dark);
            height: 100dvh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* ── Ashoka stripe at top ────────────────────── */
        .stripe {
            height: 4px;
            background: linear-gradient(90deg, #FF9933 33.3%, #FFFFFF 33.3% 66.6%, #138808 66.6%);
            flex-shrink: 0;
        }

        /* ── Header ─────────────────────────────────── */
        header {
            background: var(--bg-card);
            border-bottom: 1px solid var(--border);
            padding: 0.85rem 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.9rem;
            flex-shrink: 0;
            box-shadow: var(--shadow);
            position: relative;
            z-index: 200;
        }
        .logo-mark {
            width: 42px; height: 42px;
            border-radius: 12px;
            background: linear-gradient(135deg, #FF9933, #F4880A);
            display: flex; align-items: center; justify-content: center;
            font-size: 1.35rem;
            flex-shrink: 0;
            box-shadow: 0 2px 8px rgba(244,136,10,0.3);
        }
        .header-text { flex: 1; min-width: 0; }
        header h1 {
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--text-dark);
            line-height: 1.2;
        }
        header h1 span.hi {
            display: block;
            font-size: 0.78rem;
            font-weight: 600;
            color: var(--text-soft);
            font-family: var(--font-deva);
        }
        .lang-toggle {
            display: flex;
            border: 1.5px solid var(--border);
            border-radius: 20px;
            overflow: hidden;
            flex-shrink: 0;
        }
        .lang-btn {
            background: none;
            border: none;
            padding: 0.3rem 0.75rem;
            font-size: 0.78rem;
            font-weight: 700;
            font-family: var(--font);
            cursor: pointer;
            color: var(--text-soft);
            transition: all 0.15s;
        }
        .lang-btn.active {
            background: var(--saffron);
            color: #fff;
        }
        .status-pip {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--text-hint);
            flex-shrink: 0;
            transition: background 0.3s;
        }
        .status-pip.online { background: var(--india-green); box-shadow: 0 0 6px var(--india-green); }

        /* ── Progress bar ────────────────────────────── */
        #profile-progress {
            flex-shrink: 0;
            background: var(--bg-raised);
            border-bottom: 1px solid var(--border);
            padding: 0.6rem 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        .progress-label {
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--text-soft);
            white-space: nowrap;
        }
        .progress-track {
            flex: 1;
            height: 6px;
            background: var(--border);
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--saffron), var(--india-green));
            border-radius: 3px;
            width: 0%;
            transition: width 0.4s ease;
        }
        .progress-pct {
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--saffron);
            width: 2.5rem;
            text-align: right;
        }

        /* ── Main layout ─────────────────────────────── */
        .main-layout {
            flex: 1;
            display: flex;
            overflow: hidden;
            position: relative;
        }

        /* ── Chat area ───────────────────────────────── */
        #chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: margin-right 0.3s ease;
        }
        #chat-area.panel-open { margin-right: var(--panel-width); }

        #chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 1.25rem 1rem 0.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.9rem;
            scroll-behavior: smooth;
        }
        #chat-container::-webkit-scrollbar { width: 4px; }
        #chat-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

        /* ── Messages ────────────────────────────────── */
        .message-wrapper {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            animation: msgIn 0.22s cubic-bezier(.22,1,.36,1);
        }
        .message-wrapper.user { align-items: flex-end; }
        .message-wrapper.bot  { align-items: flex-start; }

        @keyframes msgIn {
            from { opacity: 0; transform: translateY(8px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        .msg-bubble {
            max-width: 82%;
            padding: 0.85rem 1.1rem;
            border-radius: 18px;
            line-height: 1.7;
            font-size: 0.97rem;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .msg-bubble.bot {
            background: var(--bg-card);
            border: 1.5px solid var(--border);
            border-bottom-left-radius: 4px;
            color: var(--text-body);
            box-shadow: var(--shadow);
        }
        .msg-bubble.user {
            background: linear-gradient(135deg, #F4880A, #E07A0A);
            border-bottom-right-radius: 4px;
            color: #fff;
            box-shadow: 0 2px 10px rgba(244,136,10,0.3);
        }
        .msg-bubble.error {
            background: var(--danger-pale);
            border: 1.5px solid rgba(220,38,38,0.25);
            color: var(--danger);
            border-radius: 14px;
        }
        .msg-time {
            font-size: 0.68rem;
            color: var(--text-hint);
            padding: 0 0.3rem;
        }

        /* ── Result cards (inside bot bubble) ───────── */
        .result-card {
            margin-top: 0.6rem;
            border-radius: 12px;
            border: 1.5px solid;
            padding: 0.75rem 1rem;
            font-size: 0.88rem;
            position: relative;
        }
        .result-card.eligible {
            border-color: rgba(19,136,8,0.3);
            background: var(--success-pale);
            color: #0F5E08;
        }
        .result-card.near-miss {
            border-color: rgba(217,119,6,0.3);
            background: var(--warning-pale);
            color: #92400E;
        }
        .result-card.ineligible {
            border-color: rgba(220,38,38,0.2);
            background: var(--danger-pale);
            color: #991B1B;
        }
        .result-card.needs-info {
            border-color: rgba(29,78,216,0.2);
            background: var(--info-pale);
            color: var(--info);
        }
        .result-card-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 700;
            margin-bottom: 0.3rem;
            font-size: 0.92rem;
        }
        .result-scheme-name { flex: 1; }
        .conf-badge {
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.15rem 0.5rem;
            border-radius: 20px;
            background: rgba(0,0,0,0.08);
        }
        .result-action {
            font-size: 0.82rem;
            margin-top: 0.35rem;
            line-height: 1.5;
        }

        /* ── Typing indicator ────────────────────────── */
        .typing-wrap {
            align-self: flex-start;
            background: var(--bg-card);
            border: 1.5px solid var(--border);
            border-radius: 18px;
            border-bottom-left-radius: 4px;
            padding: 0.75rem 1rem;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .typing-dot {
            width: 7px; height: 7px;
            background: var(--saffron);
            border-radius: 50%;
            animation: bounce 1.1s infinite;
        }
        .typing-dot:nth-child(2) { animation-delay: 0.18s; }
        .typing-dot:nth-child(3) { animation-delay: 0.36s; }
        @keyframes bounce {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-5px); }
        }

        /* ── Quick reply chips ───────────────────────── */
        #quick-replies {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            padding: 0.6rem 1rem;
            flex-shrink: 0;
        }
        .chip {
            background: var(--bg-raised);
            border: 1.5px solid var(--border);
            border-radius: 20px;
            padding: 0.35rem 0.9rem;
            font-size: 0.82rem;
            font-weight: 600;
            font-family: var(--font);
            color: var(--text-body);
            cursor: pointer;
            transition: all 0.15s;
        }
        .chip:hover {
            border-color: var(--saffron);
            color: var(--saffron);
            background: var(--saffron-pale);
        }

        /* ── Input area ──────────────────────────────── */
        #input-area {
            border-top: 1px solid var(--border);
            padding: 0.85rem 1rem;
            display: flex;
            gap: 0.6rem;
            background: var(--bg-card);
            flex-shrink: 0;
            align-items: flex-end;
        }
        #user-input {
            flex: 1;
            background: var(--bg-raised);
            border: 1.5px solid var(--border);
            border-radius: var(--radius);
            padding: 0.7rem 1rem;
            color: var(--text-dark);
            font-family: var(--font);
            font-size: 0.97rem;
            outline: none;
            resize: none;
            min-height: 44px;
            max-height: 120px;
            transition: border-color 0.2s, box-shadow 0.2s;
            line-height: 1.5;
            vertical-align: middle;
            display: block;
        }
        #user-input:focus {
            border-color: var(--saffron);
            box-shadow: 0 0 0 3px rgba(244,136,10,0.15);
            background: var(--bg-card);
        }
        #user-input::placeholder { color: var(--text-hint); }
        #send-btn {
            background: linear-gradient(135deg, #F4880A, #E07A0A);
            color: #fff;
            border: none;
            border-radius: var(--radius);
            width: 44px; height: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s;
            flex-shrink: 0;
            align-self: flex-end;
            box-shadow: 0 2px 10px rgba(244,136,10,0.3);
            font-size: 1.2rem;
        }
        #send-btn:hover { background: linear-gradient(135deg, #E07A0A, #CC6A00); transform: scale(1.05); }
        #send-btn:active { transform: scale(0.96); }
        #send-btn:disabled { opacity: 0.45; cursor: not-allowed; transform: none; box-shadow: none; }

        /* ── Onboarding / welcome card ───────────────── */
        .welcome-card {
            background: linear-gradient(135deg, var(--saffron-pale), var(--green-pale));
            border: 1.5px solid var(--saffron-mid);
            border-radius: 16px;
            padding: 1.25rem;
            margin-bottom: 0.5rem;
        }
        .welcome-card h2 {
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--text-dark);
            margin-bottom: 0.4rem;
        }
        .welcome-card p {
            font-size: 0.88rem;
            color: var(--text-body);
            line-height: 1.6;
        }
        .welcome-card .schemes-count {
            display: inline-block;
            background: var(--saffron);
            color: #fff;
            font-weight: 700;
            font-size: 0.8rem;
            padding: 0.15rem 0.6rem;
            border-radius: 12px;
            margin-top: 0.5rem;
        }

        /* ── Result summary card (in chat after matching) ── */
        .result-summary-card {
            margin-top: 0.5rem;
            border-radius: 14px;
            background: linear-gradient(135deg, #FFF9F2, #F0FBF0);
            border: 1.5px solid var(--saffron-mid);
            overflow: hidden;
        }
        .result-summary-top {
            padding: 1rem 1.1rem 0.7rem;
        }
        .result-summary-top h3 {
            font-size: 1rem;
            font-weight: 800;
            color: var(--text-dark);
            margin-bottom: 0.4rem;
        }
        .result-stats-row {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-bottom: 0.7rem;
        }
        .stat-pill {
            display: flex;
            align-items: center;
            gap: 0.3rem;
            padding: 0.3rem 0.75rem;
            border-radius: 20px;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .stat-pill.eligible   { background: var(--success-pale); color: var(--success); }
        .stat-pill.near-miss  { background: var(--warning-pale); color: var(--warning); }
        .stat-pill.ineligible { background: var(--bg-raised); color: var(--text-soft); }

        .top-scheme-preview {
            padding: 0.4rem 1.1rem;
            font-size: 0.8rem;
            color: var(--text-soft);
            font-weight: 600;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            border-top: 1px solid var(--border);
        }
        .preview-scheme-list {
            padding: 0 1.1rem 0.5rem;
        }
        .preview-scheme-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.45rem 0;
            border-bottom: 1px solid var(--border);
            font-size: 0.86rem;
        }
        .preview-scheme-item:last-child { border-bottom: none; }
        .preview-scheme-name { flex: 1; font-weight: 600; color: var(--text-body); }
        .conf-pill {
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.1rem 0.45rem;
            border-radius: 20px;
            background: rgba(19,136,8,0.12);
            color: var(--success);
        }
        .view-all-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.4rem;
            width: 100%;
            padding: 0.85rem 1rem;
            background: linear-gradient(135deg, var(--saffron), #E07A0A);
            color: #fff;
            font-family: var(--font);
            font-size: 0.95rem;
            font-weight: 800;
            border: none;
            cursor: pointer;
            transition: opacity 0.2s;
            letter-spacing: 0.02em;
        }
        .view-all-btn:hover { opacity: 0.9; }

        /* ── Right panel (shared by audit / results / scheme-detail) ── */
        #right-panel {
            position: absolute;
            top: 0; right: 0;
            width: var(--panel-width);
            height: 100%;
            background: var(--bg-card);
            border-left: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            transform: translateX(100%);
            transition: transform 0.32s cubic-bezier(.22,1,.36,1);
            z-index: 100;
            box-shadow: -4px 0 28px rgba(60,40,0,0.12);
        }
        #right-panel.open { transform: translateX(0); }

        .panel-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--border);
            background: var(--bg-raised);
            flex-shrink: 0;
        }
        .panel-title {
            font-size: 0.88rem;
            font-weight: 800;
            color: var(--text-body);
            flex: 1;
        }
        .panel-back-btn {
            background: none;
            border: 1.5px solid var(--border);
            color: var(--text-soft);
            cursor: pointer;
            border-radius: 8px;
            padding: 0.25rem 0.55rem;
            font-size: 0.78rem;
            font-family: var(--font);
            transition: all 0.15s;
        }
        .panel-back-btn:hover { border-color: var(--saffron); color: var(--saffron); }
        .panel-close-btn {
            background: none;
            border: 1.5px solid var(--border);
            color: var(--text-soft);
            cursor: pointer;
            border-radius: 8px;
            padding: 0.25rem 0.55rem;
            font-size: 0.82rem;
            font-family: var(--font);
            transition: all 0.15s;
        }
        .panel-close-btn:hover { color: var(--danger); border-color: var(--danger); }

        .panel-body {
            flex: 1;
            overflow-y: auto;
            padding: 0;
        }
        .panel-body::-webkit-scrollbar { width: 4px; }
        .panel-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
        .panel-padded { padding: 0.85rem; }

        /* ── Results panel content ─── */
        .results-stats-bar {
            display: flex;
            border-bottom: 1px solid var(--border);
            flex-shrink: 0;
        }
        .results-stat-cell {
            flex: 1;
            text-align: center;
            padding: 0.75rem 0.5rem;
            border-right: 1px solid var(--border);
        }
        .results-stat-cell:last-child { border-right: none; }
        .results-stat-num {
            font-size: 1.4rem;
            font-weight: 900;
            line-height: 1.1;
        }
        .results-stat-num.eligible   { color: var(--success); }
        .results-stat-num.near-miss  { color: var(--warning); }
        .results-stat-num.ineligible { color: var(--text-hint); }
        .results-stat-label {
            font-size: 0.68rem;
            font-weight: 700;
            color: var(--text-soft);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-top: 0.1rem;
        }

        /* Tabs */
        .tab-bar {
            display: flex;
            border-bottom: 2px solid var(--border);
            background: var(--bg-raised);
            flex-shrink: 0;
            overflow-x: auto;
        }
        .tab-bar::-webkit-scrollbar { display: none; }
        .tab-btn {
            flex: 1;
            min-width: 70px;
            padding: 0.7rem 0.3rem;
            font-family: var(--font);
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--text-soft);
            background: none;
            border: none;
            border-bottom: 2.5px solid transparent;
            cursor: pointer;
            transition: all 0.15s;
            text-align: center;
            white-space: nowrap;
            margin-bottom: -2px;
        }
        .tab-btn.active {
            color: var(--saffron);
            border-bottom-color: var(--saffron);
        }
        .tab-btn:hover:not(.active) { color: var(--text-body); }

        /* Apply-all bar */
        .apply-all-bar {
            padding: 0.75rem 0.85rem;
            border-bottom: 1px solid var(--border);
            background: var(--success-pale);
            flex-shrink: 0;
            display: none;
        }
        .apply-all-bar.visible { display: block; }
        .apply-all-btn {
            width: 100%;
            background: linear-gradient(135deg, var(--success), #0f6e08);
            color: #fff;
            border: none;
            border-radius: 10px;
            padding: 0.65rem 1rem;
            font-family: var(--font);
            font-size: 0.88rem;
            font-weight: 800;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .apply-all-btn:hover { opacity: 0.88; }

        /* Scheme cards in results panel */
        .scheme-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 0.8rem 0.9rem;
            margin-bottom: 0.6rem;
            cursor: pointer;
            transition: all 0.15s;
            position: relative;
        }
        .scheme-card:hover {
            border-color: var(--saffron);
            box-shadow: 0 2px 12px rgba(244,136,10,0.12);
        }
        .scheme-card-header {
            display: flex;
            align-items: flex-start;
            gap: 0.5rem;
            margin-bottom: 0.35rem;
        }
        .scheme-status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
            margin-top: 0.35rem;
        }
        .dot-eligible   { background: var(--success); box-shadow: 0 0 6px rgba(19,136,8,0.4); }
        .dot-near-miss  { background: var(--warning); }
        .dot-ineligible { background: var(--text-hint); }
        .scheme-card-name {
            flex: 1;
            font-size: 0.88rem;
            font-weight: 700;
            color: var(--text-dark);
            line-height: 1.35;
        }
        .scheme-conf-badge {
            font-size: 0.7rem;
            font-weight: 800;
            padding: 0.12rem 0.45rem;
            border-radius: 20px;
            flex-shrink: 0;
        }
        .badge-eligible   { background: var(--success-pale); color: var(--success); }
        .badge-near-miss  { background: var(--warning-pale); color: var(--warning); }
        .badge-ineligible { background: var(--bg-raised); color: var(--text-hint); }
        .scheme-card-gap {
            font-size: 0.76rem;
            color: var(--warning);
            margin-top: 0.25rem;
            font-weight: 600;
        }
        .scheme-card-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 0.35rem;
        }
        .scheme-card-arrow {
            font-size: 0.75rem;
            color: var(--text-hint);
        }
        .apply-btn-sm {
            background: var(--success-pale);
            color: var(--success);
            border: 1px solid rgba(19,136,8,0.25);
            border-radius: 8px;
            padding: 0.2rem 0.6rem;
            font-size: 0.72rem;
            font-weight: 700;
            font-family: var(--font);
            cursor: pointer;
            transition: all 0.15s;
        }
        .apply-btn-sm:hover { background: var(--success); color: #fff; }
        .apply-btn-sm.applied { background: #e8f5e9; color: #2e7d32; border-color: #a5d6a7; cursor: default; }
        .apply-now-btn {
            width: 100%;
            background: linear-gradient(135deg, var(--success), #0f6e08);
            color: #fff;
            border: none;
            border-radius: 12px;
            padding: 0.75rem 1rem;
            font-family: var(--font);
            font-size: 0.95rem;
            font-weight: 800;
            cursor: pointer;
            transition: opacity 0.2s;
            letter-spacing: 0.02em;
        }
        .apply-now-btn:hover { opacity: 0.88; }
        .step-dep {
            font-size: 0.72rem;
            color: var(--warning);
            margin-top: 0.15rem;
            font-weight: 600;
        }
        /* Results chip in chat */
        .results-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--bg-card);
            border: 1.5px solid var(--border);
            border-radius: 20px;
            padding: 0.45rem 0.8rem;
            font-size: 0.78rem;
            flex-wrap: wrap;
        }
        .chip-eligible { color: var(--success); font-weight: 700; }
        .chip-near { color: var(--warning); font-weight: 700; }
        .chip-view-btn {
            background: var(--saffron);
            color: #fff;
            border: none;
            border-radius: 12px;
            padding: 0.22rem 0.7rem;
            font-size: 0.74rem;
            font-weight: 800;
            font-family: var(--font);
            cursor: pointer;
            margin-left: 0.25rem;
        }
        .chip-view-btn:hover { opacity: 0.85; }

        /* Scheme detail view */
        .scheme-detail-section {
            padding: 0.85rem;
            border-bottom: 1px solid var(--border);
        }
        .scheme-detail-section:last-child { border-bottom: none; }
        .detail-section-title {
            font-size: 0.72rem;
            font-weight: 800;
            color: var(--text-soft);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.6rem;
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }
        .scheme-eligibility-banner {
            border-radius: 10px;
            padding: 0.75rem 0.9rem;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }
        .banner-eligible   { background: var(--success-pale); color: #0a5c07; }
        .banner-near-miss  { background: var(--warning-pale); color: #7a3d00; }
        .banner-ineligible { background: var(--danger-pale); color: #7a0a0a; }
        .banner-icon { font-size: 1.4rem; }
        .banner-text h4 { font-size: 0.92rem; font-weight: 800; }
        .banner-text p  { font-size: 0.78rem; margin-top: 0.15rem; opacity: 0.85; }

        /* Confidence breakdown in scheme detail */
        .conf-breakdown-row {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.35rem 0;
        }
        .conf-breakdown-label {
            font-size: 0.76rem;
            color: var(--text-soft);
            width: 110px;
            flex-shrink: 0;
        }
        .conf-bar-wrap { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
        .conf-bar { height: 100%; border-radius: 3px; }
        .conf-bar.high   { background: var(--success); }
        .conf-bar.medium { background: var(--warning); }
        .conf-bar.low    { background: var(--danger); }
        .conf-val {
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--text-body);
            min-width: 2.5rem;
            text-align: right;
        }
        .conf-explanation {
            margin-top: 0.45rem;
            padding: 0.5rem 0.65rem;
            background: var(--bg-raised);
            border-radius: 8px;
            font-size: 0.76rem;
            color: var(--text-soft);
            line-height: 1.5;
        }
        .conf-explanation .bottleneck { color: var(--warning); font-weight: 700; }

        /* Rule trace rows */
        .rule-row {
            display: flex;
            align-items: flex-start;
            gap: 0.55rem;
            padding: 0.45rem 0;
            border-bottom: 1px solid var(--border);
            font-size: 0.8rem;
        }
        .rule-row:last-child { border-bottom: none; }
        .rule-icon { font-size: 0.9rem; flex-shrink: 0; margin-top: 0.05rem; }
        .rule-text { flex: 1; }
        .rule-desc { color: var(--text-body); font-weight: 600; line-height: 1.4; }
        .rule-values {
            font-size: 0.72rem;
            color: var(--text-hint);
            margin-top: 0.15rem;
            font-family: var(--font-mono);
        }
        .rule-values .your { color: var(--saffron); font-weight: 700; }
        .rule-values .required { color: var(--text-soft); }

        /* Document checklist */
        .doc-item {
            display: flex;
            align-items: flex-start;
            gap: 0.6rem;
            padding: 0.55rem 0;
            border-bottom: 1px solid var(--border);
            font-size: 0.82rem;
        }
        .doc-item:last-child { border-bottom: none; }
        .doc-num {
            width: 1.5rem;
            height: 1.5rem;
            border-radius: 50%;
            background: var(--saffron);
            color: #fff;
            font-weight: 800;
            font-size: 0.72rem;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            margin-top: 0.05rem;
        }
        .doc-name { font-weight: 700; color: var(--text-dark); }
        .doc-count { font-size: 0.72rem; color: var(--text-soft); margin-top: 0.1rem; }

        /* Application sequence steps */
        .step-item {
            display: flex;
            gap: 0.7rem;
            padding: 0.65rem 0;
            border-bottom: 1px solid var(--border);
        }
        .step-item:last-child { border-bottom: none; }
        .step-num {
            width: 1.8rem;
            height: 1.8rem;
            border-radius: 50%;
            background: var(--saffron-mid);
            color: var(--saffron);
            font-weight: 800;
            font-size: 0.78rem;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }
        .step-scheme-name { font-weight: 700; font-size: 0.85rem; color: var(--text-dark); }
        .step-action { font-size: 0.75rem; color: var(--text-soft); margin-top: 0.15rem; }

        /* Accordion (for audit panel) */
        .audit-section {
            margin-bottom: 0.6rem;
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            overflow: hidden;
        }
        .audit-section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.65rem 0.9rem;
            background: var(--bg-raised);
            cursor: pointer;
            user-select: none;
            transition: background 0.15s;
        }
        .audit-section-header:hover { background: var(--saffron-pale); }
        .audit-section-title {
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--text-body);
            display: flex; align-items: center; gap: 0.4rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .sect-count {
            background: rgba(244,136,10,0.15);
            color: var(--saffron);
            font-size: 0.68rem;
            font-weight: 700;
            padding: 0.1rem 0.4rem;
            border-radius: 8px;
        }
        .chevron { color: var(--text-hint); font-size: 0.7rem; transition: transform 0.2s; }
        .audit-section.collapsed .chevron { transform: rotate(-90deg); }
        .audit-section-body {
            padding: 0.65rem;
            background: var(--bg-card);
            border-top: 1px solid var(--border);
        }
        .audit-section.collapsed .audit-section-body { display: none; }

        .audit-card {
            background: var(--bg-raised);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.6rem 0.8rem;
            margin-bottom: 0.45rem;
            font-size: 0.78rem;
        }
        .audit-card:last-child { margin-bottom: 0; }
        .field-row {
            display: flex;
            gap: 0.45rem;
            margin-bottom: 0.25rem;
            flex-wrap: wrap;
            align-items: flex-start;
        }
        .fl { color: var(--text-hint); font-size: 0.7rem; min-width: 80px; flex-shrink: 0; padding-top: 0.05rem; }
        .fv { color: var(--text-body); font-size: 0.78rem; word-break: break-word; }
        .fv.mono { font-family: var(--font-mono); font-size: 0.73rem; color: var(--saffron); }

        /* Status chips */
        .chip-ok    { background: var(--success-pale); color: var(--success); border: 1px solid rgba(19,136,8,0.2); padding: 0.1rem 0.4rem; border-radius: 6px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; }
        .chip-warn  { background: var(--warning-pale); color: var(--warning); border: 1px solid rgba(217,119,6,0.25); padding: 0.1rem 0.4rem; border-radius: 6px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; }
        .chip-fail  { background: var(--danger-pale);  color: var(--danger);  border: 1px solid rgba(220,38,38,0.2); padding: 0.1rem 0.4rem; border-radius: 6px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; }
        .chip-info  { background: var(--info-pale);    color: var(--info);    border: 1px solid rgba(29,78,216,0.2); padding: 0.1rem 0.4rem; border-radius: 6px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; }

        /* ── Details audit trigger ───────────────────── */
        .audit-trigger {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            font-size: 0.73rem;
            color: var(--text-hint);
            background: none;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.2rem 0.5rem;
            cursor: pointer;
            font-family: var(--font);
            transition: all 0.15s;
            margin-top: 0.25rem;
        }
        .audit-trigger:hover { color: var(--saffron); border-color: var(--saffron); background: var(--saffron-pale); }
        .audit-trigger.active { color: var(--saffron); border-color: var(--saffron); background: var(--saffron-pale); }

        /* Empty state */
        .empty-state { color: var(--text-hint); font-size: 0.78rem; text-align: center; padding: 1.5rem 0.75rem; }

        /* ── Mobile responsive ───────────────────────── */
        @media (max-width: 640px) {
            html { font-size: 16px; }
            :root { --panel-width: 100vw; }
            #chat-area.panel-open { margin-right: 0; }
            .msg-bubble { max-width: 90%; }
        }
    </style>
</head>
<body>
    <!-- Language selection modal (shown on first visit) -->
    <div class="lang-modal-overlay" id="lang-modal" style="display:none">
      <div class="lang-modal">
        <div class="lang-modal-flag">🇮🇳</div>
        <h2>Welcome / स्वागत है</h2>
        <div class="sub">सहायक — सरकारी योजना खोजें</div>
        <p class="hint">Choose your preferred language for the interface.<br>अपनी पसंदीदा भाषा चुनें।<br><span style="font-size:0.72rem;opacity:0.7">(The bot will also adapt to the language you type in.)</span></p>
        <div class="lang-modal-btns">
          <button class="lang-modal-btn" onclick="chooseLang(\'en\')"><span class="lmb-flag">🇬🇧</span><span class="lmb-label">English</span><span class="lmb-sub">English interface</span></button>
          <button class="lang-modal-btn" onclick="chooseLang(\'hi\')"><span class="lmb-flag">🇮🇳</span><span class="lmb-label">हिंदी</span><span class="lmb-sub">Hindi interface</span></button>
        </div>
      </div>
    </div>

    <!-- Applied schemes modal -->
    <div class="applied-modal-overlay" id="applied-modal" style="display:none" onclick="if(event.target===this)closeAppliedModal()">
      <div class="applied-modal">
        <div class="applied-modal-header">
          <span class="applied-modal-title" id="applied-modal-title">📋 Applied Schemes</span>
          <button class="applied-modal-close" onclick="closeAppliedModal()">✕</button>
        </div>
        <div class="applied-scheme-list" id="applied-scheme-list"></div>
        <div class="applied-modal-footer">
          <span class="applied-modal-count" id="applied-modal-count"></span>
          <button class="clear-all-btn" onclick="clearAllApplied()">Clear all</button>
        </div>
      </div>
    </div>

    <div class="stripe"></div>

    <header>
        <div class="logo-mark">🇮🇳</div>
        <div class="header-text">
            <h1>Sahayak — Welfare Finder
                <span class="hi">सहायक — सरकारी योजना खोजें</span>
            </h1>
        </div>
        <button id="view-results-btn" class="view-results-header-btn" style="display:none" onclick="openResultsPanel('eligible')">📊 View Results</button>
        <button id="applied-btn" class="view-results-header-btn" style="display:none;background:#e8f5e9;color:#2e7d32;border-color:rgba(46,125,50,0.3)" onclick="openAppliedModal()">📋 Applied (<span id="applied-count-hdr">0</span>)</button>
        <button id="analysis-toggle-btn" class="view-results-header-btn" style="background:var(--saffron,#FF9933)" onclick="toggleAnalysisPanel()">🔬 Analysis</button>
        <button id="reset-session-btn" class="view-results-header-btn" style="background:transparent;color:var(--text-soft);border-color:var(--border)" onclick="confirmResetSession()" title="Start a new conversation">↺ New Chat</button>
        <div class="lang-toggle">
            <button class="lang-btn active" id="btn-en" onclick="setLang('en')">EN</button>
            <button class="lang-btn" id="btn-hi" onclick="setLang('hi')">हिं</button>
        </div>
        <div class="status-pip" id="status-pip" title="Connection status"></div>
    </header>

    <div id="profile-progress">
        <span class="progress-label" id="prog-label">Profile: 0%</span>
        <div class="progress-track"><div class="progress-fill" id="prog-fill"></div></div>
        <span class="progress-pct" id="prog-pct">0%</span>
    </div>

    <div class="main-layout">
        <div id="chat-area">
            <div id="chat-container"></div>
            <div id="quick-replies"></div>
            <div id="input-area">
                <textarea id="user-input" rows="1"
                    placeholder="Tell me about yourself… (e.g. I am 42 years old, farmer from UP)"></textarea>
                <button id="send-btn" title="Send message">➤</button>
            </div>
        </div>

        <!-- Single right panel — mode controlled by JS (audit | results | scheme) -->
        <div id="right-panel">
            <!-- Audit mode header -->
            <div class="panel-header" id="audit-header">
                <span class="panel-title">🔬 How I understand this</span>
                <button class="panel-close-btn" onclick="closePanel()">✕</button>
            </div>
            <!-- Results mode header -->
            <div class="panel-header" id="results-header" style="display:none">
                <span class="panel-title">🎯 Your Eligibility Report</span>
                <button class="panel-back-btn" onclick="openFullPageReport()" title="Open full page view">⛶</button>
                <button class="panel-close-btn" onclick="closePanel()">✕</button>
            </div>
            <!-- Scheme detail mode header -->
            <div class="panel-header" id="scheme-header" style="display:none">
                <button class="panel-back-btn" onclick="backToResults()">← Back</button>
                <span class="panel-title" id="scheme-header-title">Scheme Details</span>
                <button class="panel-close-btn" onclick="closePanel()">✕</button>
            </div>

            <!-- Panel body (content changes per mode) -->
            <div id="panel-body-audit" class="panel-body panel-padded">
                <div class="empty-state">Analysis will appear here as the conversation progresses.</div>
            </div>
            <div id="panel-body-results" style="display:flex;flex-direction:column;flex:1;overflow:hidden">
                <!-- Stats bar -->
                <div class="results-stats-bar" id="results-stats-bar"></div>
                <!-- Apply-all bar -->
                <div class="apply-all-bar" id="apply-all-bar">
                    <button class="apply-all-btn" onclick="applyAllEligible()">✅ Apply for All Eligible</button>
                    <button class="apply-all-btn" style="background:var(--navy,#1a2940);color:#fff;border-color:var(--navy)" onclick="openAppliedModal()">📋 Applied (<span id="applied-count-bar">0</span>)</button>
                </div>
                <!-- Tabs -->
                <div class="tab-bar" id="results-tab-bar">
                    <button class="tab-btn active" onclick="switchTab('eligible')">✅ Eligible</button>
                    <button class="tab-btn" onclick="switchTab('near-miss')">🔶 Almost</button>
                    <button class="tab-btn" onclick="switchTab('docs')">📋 Documents</button>
                    <button class="tab-btn" onclick="switchTab('steps')">🗺️ How to Apply</button>
                </div>
                <!-- Tab content -->
                <div id="results-tab-content" class="panel-body panel-padded"></div>
            </div>
            <div id="panel-body-scheme" class="panel-body" style="display:none"></div>
        </div>
    </div>

    <style>
        /* Extra header button for View Results */
        .view-results-header-btn {
            background: var(--success-pale);
            color: var(--success);
            border: 1.5px solid rgba(19,136,8,0.25);
            border-radius: 20px;
            padding: 0.3rem 0.75rem;
            font-size: 0.78rem;
            font-weight: 700;
            font-family: var(--font);
            cursor: pointer;
            transition: all 0.15s;
            flex-shrink: 0;
        }
        .view-results-header-btn:hover { background: var(--success); color: #fff; }

        /* ── Language Modal ──────────────────────────────────────────────── */
        .lang-modal-overlay {
            position: fixed; inset: 0; z-index: 2000;
            background: rgba(26,41,64,0.72); backdrop-filter: blur(6px);
            display: flex; align-items: center; justify-content: center;
            padding: 1rem;
        }
        .lang-modal {
            background: var(--cream); border-radius: 20px;
            padding: 2.5rem 2rem 2rem;
            max-width: 440px; width: 100%;
            box-shadow: 0 24px 80px rgba(26,41,64,0.28);
            text-align: center;
            animation: fadeUp 0.35s cubic-bezier(0.22,1,0.36,1);
        }
        @keyframes fadeUp {
            from { opacity:0; transform: translateY(24px) scale(0.96); }
            to   { opacity:1; transform: translateY(0) scale(1); }
        }
        .lang-modal-flag { font-size: 2.5rem; margin-bottom: 0.75rem; }
        .lang-modal h2 { font-family: var(--font-display); font-size: 1.7rem; color: var(--navy); margin-bottom: 0.25rem; }
        .lang-modal .sub { font-family: var(--font-deva); font-size: 1.05rem; color: var(--navy); margin-bottom: 0.15rem; opacity: 0.8; }
        .lang-modal .hint { font-size: 0.78rem; color: var(--text-soft); margin-bottom: 1.6rem; line-height: 1.5; }
        .lang-modal-btns { display: flex; gap: 0.75rem; justify-content: center; }
        .lang-modal-btn {
            flex: 1; max-width: 160px;
            border: 2px solid var(--border); border-radius: 14px;
            padding: 1rem 0.5rem; cursor: pointer;
            background: #fff; transition: all 0.18s;
            display: flex; flex-direction: column; align-items: center; gap: 0.35rem;
        }
        .lang-modal-btn:hover { border-color: var(--saffron); background: #fff8f0; transform: translateY(-2px); box-shadow: 0 6px 20px rgba(232,117,10,0.12); }
        .lang-modal-btn .lmb-flag { font-size: 1.6rem; }
        .lang-modal-btn .lmb-label { font-weight: 700; font-size: 1rem; color: var(--navy); }
        .lang-modal-btn .lmb-sub { font-size: 0.72rem; color: var(--text-soft); }

        /* ── Applied Schemes Modal ───────────────────────────────────────── */
        .applied-modal-overlay {
            position: fixed; inset: 0; z-index: 1900;
            background: rgba(26,41,64,0.6); backdrop-filter: blur(4px);
            display: flex; align-items: center; justify-content: center;
            padding: 1rem;
        }
        .applied-modal {
            background: var(--cream); border-radius: 16px;
            padding: 1.5rem 1.5rem 1rem;
            max-width: 500px; width: 100%;
            max-height: 80vh; display: flex; flex-direction: column;
            box-shadow: 0 20px 60px rgba(26,41,64,0.25);
        }
        .applied-modal-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
        .applied-modal-title { font-family: var(--font-display); font-size: 1.25rem; font-weight: 700; color: var(--navy); }
        .applied-modal-close { background: none; border: none; font-size: 1.1rem; cursor: pointer; color: var(--text-soft); padding: 0.25rem 0.5rem; }
        .applied-scheme-list { overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 0.5rem; }
        .applied-scheme-row {
            display: flex; align-items: center; gap: 0.75rem;
            padding: 0.6rem 0.75rem; border-radius: 10px;
            background: #fff; border: 1px solid var(--border);
        }
        .applied-scheme-row .asr-icon { font-size: 1.1rem; }
        .applied-scheme-row .asr-name { flex: 1; font-size: 0.83rem; font-weight: 600; color: var(--navy); }
        .applied-scheme-row .asr-remove { background: none; border: none; color: var(--text-soft); font-size: 0.78rem; cursor: pointer; padding: 0.2rem 0.5rem; border-radius: 6px; }
        .applied-scheme-row .asr-remove:hover { background: #fee; color: var(--danger); }
        .applied-modal-empty { text-align: center; padding: 2rem; color: var(--text-soft); font-size: 0.85rem; }
        .applied-modal-footer { margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .applied-modal-count { font-size: 0.78rem; color: var(--text-soft); }
        .clear-all-btn { font-size: 0.75rem; color: var(--danger); background: none; border: none; cursor: pointer; }
    </style>

    <script>
    'use strict';

    /* ── State ─────────────────────────────────────────────────────────── */
    let ws = null;
    // Restore session token from previous visit so conversation is resumed
    let sessionToken = localStorage.getItem('cbc_session_token') || '';
    // Guard: discard oversized tokens from previous versions
    if (sessionToken.length > 30000) {
        sessionToken = '';
        localStorage.removeItem('cbc_session_token');
    }
    let turnCount = 0;
    let currentLang = localStorage.getItem('cbc_lang_pref') || 'en';
    let auditStore = {};          // turnId → turn_audit payload
    // Cumulative audit — merges data across all turns for the analysis panel
    let cumulativeAudit = { extraction_trace: [], ner_rejections: [], contradictions: [], gap_analysis: [], per_rule_trace: [], ambiguity_flags: [], confidence_breakdown: {} };
    let appliedSchemes = new Set(JSON.parse(localStorage.getItem('cbc_applied') || '[]'));
    let currentResult = null;    // latest matching_result
    let currentTab = 'eligible'; // active results tab
    let panelMode = null;        // null | 'audit' | 'results' | 'scheme'
    let activeTurnBtn = null;
    let profilePct = 0;
    let matchingDone = false;    // whether matching has been triggered once

    /* ── i18n labels ────────────────────────────────────────────────────── */
    const I18N = {
        en: {
            extracted: 'What I Extracted', factCheck: 'Fact Check', factIssues: 'Fact Check Issues',
            consistency: 'Consistency Check', consistencyIssues: 'Consistency Issues',
            missing: 'Missing Info', confidence: 'Confidence', rules: 'Rule Check',
            ambiguity: 'Ambiguities', matchSummary: 'Matching Summary', sampleRules: 'Sample Rule Evaluations',
            analysis: '🔬 How I understand this', appliedTitle: '📋 Applied Schemes',
            appliedEmpty: 'No schemes applied yet. Click "Apply →" on any eligible scheme.',
            appliedCount: n => `${n} scheme${n!==1?'s':''} applied (demo)`,
            clearAll: 'Clear all', refinePrompt: 'Results are ready! You can continue sharing more details to refine your eligibility, or ask me about any specific scheme.',
        },
        hi: {
            extracted: 'मैंने क्या समझा', factCheck: 'तथ्य जाँच', factIssues: 'तथ्य जाँच समस्याएं',
            consistency: 'संगति जाँच', consistencyIssues: 'संगति समस्याएं',
            missing: 'अधूरी जानकारी', confidence: 'विश्वसनीयता', rules: 'नियम जाँच',
            ambiguity: 'अस्पष्टताएं', matchSummary: 'मिलान सारांश', sampleRules: 'नमूना नियम मूल्यांकन',
            analysis: '🔬 मैंने कैसे समझा', appliedTitle: '📋 आवेदित योजनाएं',
            appliedEmpty: 'अभी तक कोई योजना नहीं चुनी। किसी भी पात्र योजना पर "आवेदन करें →" दबाएं।',
            appliedCount: n => `${n} योजना${n!==1?'एं':''} आवेदित (डेमो)`,
            clearAll: 'सब हटाएं', refinePrompt: 'परिणाम तैयार हैं! आप अधिक जानकारी देकर अपनी पात्रता सुधार सकते हैं, या किसी योजना के बारे में पूछ सकते हैं।',
        },
    };
    function t(key) { return (I18N[currentLang] || I18N.en)[key] || key; }

    const chatContainer = document.getElementById('chat-container');
    const userInput     = document.getElementById('user-input');
    const sendBtn       = document.getElementById('send-btn');
    const statusPip     = document.getElementById('status-pip');
    const progFill      = document.getElementById('prog-fill');
    const progPct       = document.getElementById('prog-pct');
    const progLabel     = document.getElementById('prog-label');
    const quickReplies  = document.getElementById('quick-replies');
    const rightPanel    = document.getElementById('right-panel');
    const chatArea      = document.getElementById('chat-area');

    /* ── Helpers ────────────────────────────────────────────────────────── */
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;')
            .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function now() {
        return new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    }
    function setStatus(online) {
        statusPip.className = 'status-pip' + (online ? ' online' : '');
        statusPip.title = online ? 'Connected' : 'Reconnecting…';
    }
    function showToast(msg, durationMs = 3000) {
        const existing = document.getElementById('ui-toast');
        if (existing) existing.remove();
        const el = document.createElement('div');
        el.id = 'ui-toast';
        el.textContent = msg;
        el.style.cssText = 'position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%);'
            + 'background:#333;color:#fff;padding:0.65rem 1.2rem;border-radius:20px;'
            + 'font-size:0.82rem;z-index:3000;pointer-events:none;'
            + 'animation:msgIn 0.22s cubic-bezier(.22,1,.36,1)';
        document.body.appendChild(el);
        setTimeout(() => { if (el.parentNode) el.remove(); }, durationMs);
    }
    function setLang(l) {
        currentLang = l;
        document.getElementById('btn-en').classList.toggle('active', l === 'en');
        document.getElementById('btn-hi').classList.toggle('active', l === 'hi');
        // Update analysis panel header label
        const ah = document.querySelector('#audit-header .panel-title');
        if (ah) ah.textContent = t('analysis');
        userInput.placeholder = l === 'hi'
            ? 'अपने बारे में बताएं… (जैसे मैं 42 साल का किसान हूँ, UP से)'
            : 'Tell me about yourself… (e.g. I am 42 years old, farmer from UP)';
        localStorage.setItem('cbc_lang_pref', l);
    }

    /* ── Language modal ─────────────────────────────────────────────────── */
    function chooseLang(l) {
        document.getElementById('lang-modal').style.display = 'none';
        setLang(l);
        localStorage.setItem('cbc_lang_pref', l);
    }

    /* ── Client-side Hinglish/Hindi auto-detect ─────────────────────────── */
    const _HINGLISH_MARKERS = new Set([
        'mera','meri','mere','main','mai','hoon','hun','hai','hain','nahi','nahin',
        'kya','kaise','kitna','kitni','kitne','aur','lekin','agar','toh','se','ka',
        'ki','ke','ko','mein','par','woh','yeh','hum','tum','aap','sala','saal',
        'rupaye','paisa','kisan','gaon','shahar','zamin','zameen','ghar',
        'parivar','sarkar','sarkari','yojana','hu','ho','hau','bata',
        'naam','nahi','rehta','rehti','rehte','tha','thi','the','hua','hui',
        'raha','rahi','rahte','batao','bataye','chahiye','milta','milti',
        'karta','karti','karte','khata','khati','baara','bara','barah',
        'unka','unki','inhe','mujhe','tumhe','aapko','hame','hamara',
        'wala','wali','wale','sabse','bahut','thoda','zyada','kam',
    ]);
    function _autoDetectLang(text) {
        // If text contains Devanagari → Hindi
        if (/[\u0900-\u097F]/.test(text)) return 'hi';
        // Count Hinglish markers
        const words = text.toLowerCase().match(/[a-z]+/g) || [];
        let hits = 0;
        for (const w of words) { if (_HINGLISH_MARKERS.has(w)) hits++; }
        // Short messages (≤7 words): 1 hit is enough; longer messages need 2
        if (hits >= 1 && words.length <= 7) return 'hi';
        if (hits >= 2) return 'hi';
        return 'en';
    }
    function updateProgress(pct) {
        profilePct = pct;
        progFill.style.width = pct + '%';
        progPct.textContent = pct + '%';
        progLabel.textContent = (currentLang === 'hi' ? 'प्रोफ़ाइल: ' : 'Profile: ') + pct + '%';
    }
    function schemeStatusClass(status) {
        if (status === 'ELIGIBLE' || status === 'ELIGIBLE_WITH_CAVEATS') return 'eligible';
        if (status === 'NEAR_MISS') return 'near-miss';
        return 'ineligible';
    }
    function confBarClass(pct) {
        if (pct >= 65) return 'high';
        if (pct >= 40) return 'medium';
        return 'low';
    }

    /* ── Quick reply chips ──────────────────────────────────────────────── */
    const QUICK_EN = ["Tell me about PM Kisan","What is MGNREGA?","Check my eligibility","I don't know my income","Skip this question"];
    const QUICK_HI = ['पीएम किसान के बारे में बताएं','मनरेगा क्या है?','मेरी पात्रता जांचें','आय नहीं पता','यह छोड़ें'];
    function showQuickReplies(items) {
        quickReplies.innerHTML = '';
        items.forEach(text => {
            const btn = document.createElement('button');
            btn.className = 'chip';
            btn.textContent = text;
            btn.onclick = () => { sendText(text); quickReplies.innerHTML = ''; };
            quickReplies.appendChild(btn);
        });
    }

    /* ── Panel management ───────────────────────────────────────────────── */
    function setPanelMode(mode) {
        panelMode = mode;
        document.getElementById('audit-header').style.display   = mode === 'audit'   ? '' : 'none';
        document.getElementById('results-header').style.display  = mode === 'results' ? '' : 'none';
        document.getElementById('scheme-header').style.display   = mode === 'scheme'  ? '' : 'none';
        document.getElementById('panel-body-audit').style.display    = mode === 'audit'   ? '' : 'none';
        document.getElementById('panel-body-results').style.display  = mode === 'results' ? 'flex' : 'none';
        document.getElementById('panel-body-scheme').style.display   = mode === 'scheme'  ? '' : 'none';
        if (mode) {
            rightPanel.classList.add('open');
            chatArea.classList.add('panel-open');
        }
    }
    function closePanel() {
        rightPanel.classList.remove('open');
        chatArea.classList.remove('panel-open');
        panelMode = null;
        if (activeTurnBtn) { activeTurnBtn.classList.remove('active'); activeTurnBtn = null; }
    }
    function toggleAnalysisPanel() {
        if (rightPanel.classList.contains('open') && panelMode === 'audit') {
            closePanel();
        } else {
            setPanelMode('audit');
        }
    }
    function openResultsPanel(tab) {
        tab = tab || currentTab || 'eligible';
        setPanelMode('results');
        renderResultsStats();
        switchTab(tab);
    }
    function backToResults() {
        setPanelMode('results');
        document.getElementById('panel-body-results').style.display = 'flex';
    }

    /* ── Results panel rendering ─────────────────────────────────────────── */
    function switchTab(tab) {
        currentTab = tab;
        document.querySelectorAll('#results-tab-bar .tab-btn').forEach((btn, i) => {
            const tabs = ['eligible','near-miss','docs','steps'];
            btn.classList.toggle('active', tabs[i] === tab);
        });
        const content = document.getElementById('results-tab-content');
        if (!currentResult) { content.innerHTML = '<div class="empty-state">No results yet.</div>'; return; }
        const schemes = currentResult.scheme_results || [];
        if (tab === 'eligible') {
            const el = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS');
            content.innerHTML = el.length
                ? el.map(s => renderSchemeCard(s)).join('')
                : '<div class="empty-state">No fully eligible schemes found yet. Try adding more profile details.</div>';
        } else if (tab === 'near-miss') {
            const nm = schemes.filter(s => {
                if (s.status !== 'NEAR_MISS') return false;
                // Only show near-miss schemes that have meaningful gap content
                const ga = s.gap_analysis || {};
                const hasFailedRules = (ga.failed_rules || []).length > 0;
                const hasRemediations = (ga.remediation_actions || []).length > 0;
                const hasGapText = !!(s.gap && s.gap.trim());
                return hasFailedRules || hasRemediations || hasGapText;
            });
            content.innerHTML = nm.length
                ? nm.map(s => renderSchemeCard(s)).join('')
                : '<div class="empty-state">No near-miss schemes found.</div>';
        } else if (tab === 'docs') {
            content.innerHTML = renderDocumentChecklist();
        } else if (tab === 'steps') {
            content.innerHTML = renderApplicationSteps();
        }
        // Attach click handlers to scheme cards
        content.querySelectorAll('.scheme-card[data-scheme-idx]').forEach(card => {
            card.addEventListener('click', () => {
                const idx = parseInt(card.dataset.schemeIdx, 10);
                showSchemeDetail(currentResult.scheme_results[idx]);
            });
        });
    }

    function renderResultsStats() {
        if (!currentResult) return;
        const schemes = currentResult.scheme_results || [];
        const nEligible  = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS').length;
        const nNearMiss  = schemes.filter(s => s.status === 'NEAR_MISS').length;
        const nIneligible = schemes.filter(s => !['ELIGIBLE','ELIGIBLE_WITH_CAVEATS','NEAR_MISS'].includes(s.status)).length;
        document.getElementById('results-stats-bar').innerHTML = `
          <div class="results-stat-cell">
            <div class="results-stat-num eligible">${nEligible}</div>
            <div class="results-stat-label">Eligible</div>
          </div>
          <div class="results-stat-cell">
            <div class="results-stat-num near-miss">${nNearMiss}</div>
            <div class="results-stat-label">Almost</div>
          </div>
          <div class="results-stat-cell">
            <div class="results-stat-num ineligible">${nIneligible}</div>
            <div class="results-stat-label">Not eligible</div>
          </div>`;
        // Show apply-all bar if there are eligible schemes
        const applyBar = document.getElementById('apply-all-bar');
        applyBar.classList.toggle('visible', nEligible > 0);
    }

    function renderSchemeCard(scheme) {
        const schemes = currentResult.scheme_results || [];
        const idx = schemes.indexOf(scheme);
        const cls = schemeStatusClass(scheme.status);
        const confPct = scheme.confidence_breakdown
            ? scheme.confidence_breakdown.composite_pct
            : Math.round((scheme.confidence || 0) * 100);
        // Build gap text: prefer derived gap from failed_rules, fall back to generic gap field
        let gap = scheme.gap || '';
        const ga = scheme.gap_analysis || {};
        const failedRulesList = ga.failed_rules || [];
        if (!gap && failedRulesList.length) {
            gap = failedRulesList.slice(0, 2).map(fr => {
                const field = fr.display_text || fr.field || '';
                const required = fr.required_value != null ? String(fr.required_value) : '';
                return field + (required ? ': needs ' + required : '');
            }).join('; ');
        }
        const isEligible = scheme.status === 'ELIGIBLE' || scheme.status === 'ELIGIBLE_WITH_CAVEATS';
        return `<div class="scheme-card" data-scheme-idx="${idx}">
          <div class="scheme-card-header">
            <div class="scheme-status-dot dot-${cls}"></div>
            <span class="scheme-card-name">${esc(scheme.name || scheme.scheme_name || '')}</span>
            <span class="scheme-conf-badge badge-${cls}">${confPct}%</span>
          </div>
          ${gap ? `<div class="scheme-card-gap">⚠ ${esc(gap)}</div>` : ''}
          <div class="scheme-card-footer">
            ${isEligible ? `<button class="apply-btn-sm ${appliedSchemes.has(scheme.name||scheme.scheme_name||'') ? 'applied' : ''}" onclick="event.stopPropagation();applyScheme(${JSON.stringify(scheme.name||scheme.scheme_name||'')})">${appliedSchemes.has(scheme.name||scheme.scheme_name||'') ? 'Applied ✓' : 'Apply →'}</button>` : ''}
            <div class="scheme-card-arrow">›</div>
          </div>
        </div>`;
    }

    function renderDocumentChecklist() {
        const docs = (currentResult.document_checklist || []);
        const schemes = (currentResult.scheme_results || [])
            .filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS');
        // If no checklist from backend, try to derive common documents from eligible schemes
        let docList = docs;
        if (!docList.length && schemes.length) {
            // Default essential documents based on common scheme requirements
            docList = [
                { name: 'Aadhaar Card', required_by: schemes.map(s => s.name || s.scheme_name), mandatory: true },
                { name: 'Bank Account Passbook / Details', required_by: schemes.map(s => s.name || s.scheme_name), mandatory: true },
                { name: 'Income Certificate', required_by: schemes.slice(0,5).map(s => s.name || s.scheme_name), mandatory: true },
                { name: 'Caste Certificate (if applicable)', required_by: schemes.slice(0,3).map(s => s.name || s.scheme_name), mandatory: false },
                { name: 'Passport-size photograph', required_by: schemes.map(s => s.name || s.scheme_name), mandatory: true },
            ];
        }
        if (!docList.length) return '<div class="empty-state">Document checklist will appear after eligibility check.</div>';
        // Sort by number of schemes that require each document (most needed first)
        const sorted = docList.slice().sort((a,b) => (b.required_by||[]).length - (a.required_by||[]).length);
        const applyOnceNote = `<div style="background:var(--info-pale);border-radius:8px;padding:0.6rem 0.75rem;margin-bottom:0.75rem;font-size:0.75rem;color:var(--info)">
          💡 <strong>Apply Once:</strong> Gather these documents once — they work across all eligible schemes. Prioritised by how many schemes need each.
        </div>`;
        return applyOnceNote + '<div>' + sorted.slice(0,20).map((d, i) => `
          <div class="doc-item">
            <div class="doc-num">${i+1}</div>
            <div>
              <div class="doc-name">${esc(d.name || d.document_name || '')}</div>
              <div class="doc-count">Needed by ${(d.required_by||[]).length || '?'} scheme(s)${d.mandatory===false?' — optional':' — required'}</div>
            </div>
          </div>`).join('') + '</div>';
    }

    function renderApplicationSteps() {
        const schemes = (currentResult.scheme_results || [])
            .filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS');
        if (!schemes.length) return '<div class="empty-state">No eligible schemes to apply for yet.</div>';
        // Use application_sequence if available (has prerequisite ordering)
        const seqSteps = (currentResult.application_sequence || []).filter(step =>
            step.status === 'ELIGIBLE' || step.status === 'ELIGIBLE_WITH_CAVEATS'
        );
        // Build name→scheme lookup for detail click
        const nameMap = {};
        schemes.forEach(s => { nameMap[s.name || s.scheme_name] = s; });

        const items = seqSteps.length ? seqSteps.map((step, i) => ({
            num: step.order || (i + 1),
            name: step.scheme_name || step.scheme_id || '',
            deps: step.depends_on || [],
        })) : schemes.map((s, i) => ({
            num: i + 1,
            name: s.name || s.scheme_name || '',
            deps: [],
        }));

        return `<div style="margin-bottom:0.5rem;font-size:0.75rem;color:var(--text-hint)">Apply in this order — schemes listed first have no prerequisites.</div>` +
            '<div>' + items.map(step => `
              <div class="step-item">
                <div class="step-num">${step.num}</div>
                <div style="flex:1">
                  <div class="step-scheme-name">${esc(step.name)}</div>
                  ${step.deps.length
                    ? `<div class="step-dep">⚠ Complete first: ${step.deps.map(d => esc(d)).join(', ')}</div>`
                    : '<div class="step-action">No prerequisites — apply anytime</div>'}
                  <button class="apply-btn-sm" onclick="applyScheme(${JSON.stringify(step.name)})">Apply →</button>
                </div>
              </div>`).join('') + '</div>';
    }

    function applyScheme(schemeName) {
        // Find scheme in current results and show detail view
        const schemes = currentResult.scheme_results || [];
        const scheme = schemes.find(s => (s.name || s.scheme_name) === schemeName);
        if (scheme) { showSchemeDetail(scheme); return; }
        window.open('https://www.india.gov.in/search-schemes?q=' + encodeURIComponent(schemeName), '_blank');
    }

    function applyNowExternal(schemeId, schemeName) {
        // Known flagship schemes → direct portal links
        const portals = {
            'pmjdy': 'https://pmjdy.gov.in/',
            'pmkisan': 'https://pmkisan.gov.in/',
            'pmgsy': 'https://pmgsy.nic.in/',
            'mgnrega': 'https://nrega.nic.in/',
            'pmaay': 'https://pmaay.gov.in/',
            'ayushman': 'https://pmjay.gov.in/',
            'ujjwala': 'https://pmuy.gov.in/',
            'mudra': 'https://www.mudra.org.in/',
            'apy': 'https://npscra.nsdl.co.in/scheme-details.php',
        };
        const key = (schemeId || schemeName || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        for (const [k, url] of Object.entries(portals)) {
            if (key.includes(k) || (schemeName||'').toLowerCase().includes(k)) {
                window.open(url, '_blank');
                return;
            }
        }
        // Generic fallback
        window.open('https://www.india.gov.in/search-schemes?q=' + encodeURIComponent(schemeName || schemeId || ''), '_blank');
    }



    function showApplicationSteps() {
        switchTab('steps');
    }

    /* ── Scheme detail view ────────────────────────────────────────────── */
    function showSchemeDetail(scheme) {
        const title = scheme.name || scheme.scheme_name || 'Scheme Details';
        document.getElementById('scheme-header-title').textContent = title.length > 30
            ? title.substring(0,28) + '…' : title;
        setPanelMode('scheme');

        const cls = schemeStatusClass(scheme.status);
        const confBreakdown = scheme.confidence_breakdown || {};
        const confPct = confBreakdown.composite_pct || Math.round((scheme.confidence || 0) * 100);
        const rules = scheme.rule_evaluations || [];
        const passedRules = rules.filter(r => r.outcome === 'PASS' || r.outcome === 'UNVERIFIED_PASS').length;
        const failedRules = rules.filter(r => r.outcome === 'FAIL').length;
        const undetermined = rules.filter(r => r.outcome !== 'PASS' && r.outcome !== 'UNVERIFIED_PASS' && r.outcome !== 'FAIL').length;

        // Status banner
        const bannerMap = {
            'eligible': { cls: 'banner-eligible', icon: '✅', h: 'You qualify!', p: 'You meet all known criteria for this scheme.' },
            'near-miss': { cls: 'banner-near-miss', icon: '🔶', h: 'Almost there!', p: 'You are close — see the gaps below to qualify.' },
            'ineligible': { cls: 'banner-ineligible', icon: '❌', h: 'Not eligible currently', p: 'You do not meet the current criteria for this scheme.' },
        };
        let banner = bannerMap[cls] || bannerMap['ineligible'];
        // If marked ELIGIBLE but no rules actually passed (low evidence), temper the banner
        if (cls === 'eligible' && passedRules === 0 && undetermined > 0) {
            banner = { cls: 'banner-eligible', icon: '🔍', h: 'Appears eligible — verify details', p: "You may qualify, but we couldn't confirm all criteria. Review requirements before applying." };
        }

        // Build sections
        let html = '';

        // 0. Apply Now bar (for eligible schemes)
        if (cls === 'eligible') {
            html += `<div class="scheme-detail-section" style="padding-bottom:0.5rem">
              <button class="apply-now-btn" onclick="applyNowExternal('${esc(scheme.scheme_id||'')}', '${esc(title).replace(/'/g, '\\&#39;')}')">
                ✅ Apply Now →
              </button>
              <div style="font-size:0.72rem;color:var(--text-hint);margin-top:0.35rem;text-align:center">Opens official portal or guidance</div>
            </div>`;
        }

        // 1. Status banner
        html += `<div class="scheme-detail-section">
          <div class="scheme-eligibility-banner ${banner.cls}">
            <div class="banner-icon">${banner.icon}</div>
            <div class="banner-text"><h4>${banner.h}</h4><p>${banner.p}</p></div>
          </div>
        </div>`;

        // 2. Confidence breakdown
        html += `<div class="scheme-detail-section">
          <div class="detail-section-title">📊 Confidence Score — ${confPct}%</div>`;
        if (confBreakdown.composite_pct !== undefined) {
            const scores = [
                { label: 'Overall match', val: confBreakdown.composite_pct, key: 'composite_pct' },
                { label: 'Rules passed', val: Math.round((confBreakdown.rule_match_score||0)*100), key: 'rule_match_score' },
                { label: 'Data quality', val: Math.round((confBreakdown.data_confidence||0)*100), key: 'data_confidence' },
                { label: 'Profile completeness', val: Math.round((confBreakdown.profile_completeness||0)*100), key: 'profile_completeness' },
            ];
            html += scores.map(s => `
              <div class="conf-breakdown-row">
                <span class="conf-breakdown-label">${esc(s.label)}</span>
                <div class="conf-bar-wrap"><div class="conf-bar ${confBarClass(s.val)}" style="width:${s.val||0}%"></div></div>
                <span class="conf-val">${s.val||0}%</span>
              </div>`).join('');
            if (confBreakdown.explanation || confBreakdown.bottleneck) {
                const bottleneckLabels = {
                    'data_confidence': 'unverified data',
                    'profile_completeness': 'incomplete profile',
                    'rule_match_score': 'rules not met',
                };
                const bLabel = bottleneckLabels[confBreakdown.bottleneck] || confBreakdown.bottleneck;
                html += `<div class="conf-explanation">
                  ${confBreakdown.explanation ? esc(confBreakdown.explanation) : ''}
                  ${bLabel ? `<br><span class="bottleneck">Main limitation: ${esc(bLabel)}</span>` : ''}
                </div>`;
            }
            html += `<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--text-soft)">
              ✅ ${passedRules} rules passed &nbsp; ❌ ${failedRules} rules failed &nbsp; ❓ ${undetermined} undetermined
            </div>`;
        }
        html += '</div>';

        // 3. Rule-by-rule trace
        if (rules.length) {
            html += `<div class="scheme-detail-section">
              <div class="detail-section-title">⚖️ Why This Score? (${rules.length} rules checked)</div>`;
            rules.slice(0,15).forEach(r => {
                const passed = r.outcome === 'PASS' || r.outcome === 'UNVERIFIED_PASS';
                const undet  = !passed && r.outcome !== 'FAIL';
                const icon = passed ? '✅' : undet ? '❓' : '❌';
                const userVal = r.user_value != null ? String(r.user_value) : '';
                const ruleVal = r.rule_value != null ? String(r.rule_value) : '';
                html += `<div class="rule-row">
                  <span class="rule-icon">${icon}</span>
                  <div class="rule-text">
                    <div class="rule-desc">${esc(r.display_text || r.description || r.rule_id || '')}</div>
                    ${(userVal || ruleVal) ? `<div class="rule-values">
                      ${userVal ? `Your value: <span class="your">${esc(userVal)}</span>` : '<span style="color:var(--text-hint)">your value: unknown</span>'}
                      ${ruleVal ? ` &nbsp;·&nbsp; Required: <span class="required">${esc(ruleVal)}</span>` : ''}
                    </div>` : ''}
                    ${undet ? `<div style="font-size:0.7rem;color:var(--warning);margin-top:0.1rem">${r.undetermined_reason === 'Field not provided' ? 'We don\'t have this information yet' : 'Rule value not specified in scheme data — cannot evaluate automatically'}</div>` : ''}
                    ${r.outcome === 'UNVERIFIED_PASS' ? '<div style="font-size:0.7rem;color:var(--success);margin-top:0.1rem">✓ Matches (unverified data)</div>' : ''}
                  </div>
                </div>`;
            });
            if (rules.length > 15) {
                html += `<div style="text-align:center;font-size:0.74rem;color:var(--text-hint);padding:0.5rem">+ ${rules.length-15} more rules</div>`;
            }
            html += '</div>';
        }

        // 4. Gap analysis (for near-miss / ineligible)
        const ga = scheme.gap_analysis || {};
        const failedRulesList = ga.failed_rules || [];
        const remediations = ga.remediation_actions || [];
        if (failedRulesList.length || remediations.length) {
            html += `<div class="scheme-detail-section">
              <div class="detail-section-title">🔍 What You Need to Qualify</div>`;
            failedRulesList.slice(0,5).forEach(fr => {
                html += `<div class="rule-row">
                  <span class="rule-icon">❌</span>
                  <div class="rule-text">
                    <div class="rule-desc">${esc(fr.display_text || fr.field || '')}</div>
                    <div class="rule-values">
                      Your value: <span class="your">${esc(fr.user_value != null ? String(fr.user_value) : 'unknown')}</span>
                      &nbsp;·&nbsp; Required: <span class="required">${esc(fr.required_value != null ? String(fr.required_value) : '?')}</span>
                    </div>
                  </div>
                </div>`;
            });
            remediations.slice(0,3).forEach(ra => {
                html += `<div style="background:var(--info-pale);border-radius:8px;padding:0.55rem 0.7rem;margin-top:0.4rem;font-size:0.78rem;color:var(--info)">
                  💡 ${esc(ra.description || '')}
                  ${ra.urgency ? `<span style="opacity:0.7"> (${esc(ra.urgency)} priority)</span>` : ''}
                </div>`;
            });
            html += '</div>';
        }

        // 5. Ambiguity warnings
        const ambs = scheme.ambiguity_flags || [];
        if (ambs.length) {
            html += `<div class="scheme-detail-section">
              <div class="detail-section-title">⚠️ Notes & Cautions (${ambs.length})</div>`;
            ambs.slice(0,5).forEach(a => {
                html += `<div style="padding:0.45rem 0;border-bottom:1px solid var(--border);font-size:0.78rem;color:var(--text-body)">
                  ⚠ ${esc(a.description || a.type_name || '')}
                </div>`;
            });
            html += '</div>';
        }

        document.getElementById('panel-body-scheme').innerHTML = html;
    }

    /* ── Chat message rendering ─────────────────────────────────────────── */
    function renderMd(text) {
        if (!text) return '';
        // Escape HTML first
        let s = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        // Simple bold: **text**
        s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Simple italic: *text* (just wrap in em tags)
        s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
        // Double newlines = paragraph break
        s = s.replace(/\n\n+/g, '</p><p>');
        // Single newlines = line break
        s = s.replace(/\n/g, '<br>');
        return '<p>' + s + '</p>';
    }

    function addMessage(text, role, turnId) {
        if (!text || !String(text).trim()) return;  // guard empty bubbles
        const wrapper = document.createElement('div');
        wrapper.className = 'message-wrapper ' + (role === 'user' ? 'user' : 'bot');
        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble ' + (role === 'user' ? 'user' : (role === 'error' ? 'error' : 'bot'));
        if (role === 'bot') {
            bubble.innerHTML = renderMd(text);
        } else {
            bubble.textContent = text;
        }
        wrapper.appendChild(bubble);
        const timeEl = document.createElement('span');
        timeEl.className = 'msg-time';
        timeEl.textContent = now();
        wrapper.appendChild(timeEl);
        chatContainer.appendChild(wrapper);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function addResultsChip(result) {
        const schemes = result.scheme_results || [];
        const nEligible = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS').length;
        const nNearMiss = schemes.filter(s => s.status === 'NEAR_MISS').length;

        const wrapper = document.createElement('div');
        wrapper.className = 'message-wrapper bot';
        const chip = document.createElement('div');
        chip.className = 'results-chip';
        chip.innerHTML = `
          <span class="chip-eligible">✅ ${nEligible} eligible</span>
          ${nNearMiss ? `<span class="chip-near">🔶 ${nNearMiss} almost</span>` : ''}
          <button class="chip-view-btn" onclick="openResultsPanel('eligible')">View Details →</button>`;
        wrapper.appendChild(chip);
        chatContainer.appendChild(wrapper);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function addResultsCard(result) {
        const schemes = result.scheme_results || [];
        const nEligible = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS').length;
        const nNearMiss = schemes.filter(s => s.status === 'NEAR_MISS').length;
        const total = result.total_evaluated || schemes.length;
        const top3 = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS').slice(0,3);

        const wrapper = document.createElement('div');
        wrapper.className = 'message-wrapper bot';
        wrapper.style.alignItems = 'flex-start';

        const card = document.createElement('div');
        card.className = 'result-summary-card';
        card.style.maxWidth = '82%';

        const topSection = document.createElement('div');
        topSection.className = 'result-summary-top';
        topSection.innerHTML = `
          <h3>🎯 Eligibility Report — ${total.toLocaleString()} schemes checked</h3>
          <div class="result-stats-row">
            <span class="stat-pill eligible">✅ ${nEligible} Eligible</span>
            <span class="stat-pill near-miss">🔶 ${nNearMiss} Almost</span>
          </div>`;
        card.appendChild(topSection);

        if (top3.length) {
            const previewLabel = document.createElement('div');
            previewLabel.className = 'top-scheme-preview';
            previewLabel.textContent = 'Your Top Matches';
            card.appendChild(previewLabel);

            const list = document.createElement('div');
            list.className = 'preview-scheme-list';
            top3.forEach(s => {
                const confPct = s.confidence_breakdown
                    ? s.confidence_breakdown.composite_pct
                    : Math.round((s.confidence||0)*100);
                const item = document.createElement('div');
                item.className = 'preview-scheme-item';
                item.innerHTML = `
                  <span>✅</span>
                  <span class="preview-scheme-name">${esc(s.name||s.scheme_name||'')}</span>
                  <span class="conf-pill">${confPct}%</span>`;
                list.appendChild(item);
            });
            card.appendChild(list);
        }

        const viewBtn = document.createElement('button');
        viewBtn.className = 'view-all-btn';
        viewBtn.innerHTML = '📊 View All Results & Apply →';
        viewBtn.onclick = () => openResultsPanel('eligible');
        card.appendChild(viewBtn);

        const timeEl = document.createElement('span');
        timeEl.className = 'msg-time';
        timeEl.textContent = now();

        wrapper.appendChild(card);
        wrapper.appendChild(timeEl);
        chatContainer.appendChild(wrapper);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function showWelcomeCard() {
        const card = document.createElement('div');
        card.className = 'welcome-card';
        card.innerHTML = `
          <h2>🙏 Welcome! Let's find your benefits.</h2>
          <p>Tell me a little about yourself — your age, where you live, your income, and what work you do. I'll check which government schemes you qualify for.</p>
          <p style="margin-top:0.5rem;font-family:var(--font-deva)">बस अपने बारे में बताएं — मैं सारे सरकारी फ़ायदे ढूंढूंगा।</p>
          <span class="schemes-count">✓ 3,397 schemes checked</span>
        `;
        chatContainer.appendChild(card);
    }

    const _STATUS_MSGS_EN = [
        'Thinking…',
        'Understanding your message…',
        'Checking our records…',
        'Analysing your profile…',
    ];
    const _STATUS_MSGS_MATCH_EN = [
        'Running eligibility check across 3,397 schemes…',
        'Checking rules for each scheme…',
        'Building your personalised report…',
        'Almost there — wrapping up…',
    ];
    const _STATUS_MSGS_HI = [
        'सोच रहा हूँ…',
        'आपकी जानकारी समझ रहा हूँ…',
        'जाँच हो रही है…',
        'प्रोफ़ाइल का विश्लेषण हो रहा है…',
    ];
    const _STATUS_MSGS_MATCH_HI = [
        '3,397 योजनाओं की जाँच हो रही है…',
        'हर योजना के नियम देख रहा हूँ…',
        'आपकी रिपोर्ट तैयार हो रही है…',
        'लगभग हो गया…',
    ];
    let _typingTimer = null;

    function showTyping(isMatching) {
        const div = document.createElement('div');
        div.className = 'typing-wrap message-wrapper bot';
        div.id = 'typing';
        const msgs = isMatching
            ? (currentLang === 'hi' ? _STATUS_MSGS_MATCH_HI : _STATUS_MSGS_MATCH_EN)
            : (currentLang === 'hi' ? _STATUS_MSGS_HI : _STATUS_MSGS_EN);
        div.innerHTML = `
          <div style="display:flex;align-items:center;gap:0.5rem">
            <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
            <span id="typing-status" style="font-size:0.78rem;color:var(--text-soft);margin-left:0.3rem">${msgs[0]}</span>
          </div>`;
        chatContainer.appendChild(div);
        chatContainer.scrollTop = chatContainer.scrollHeight;
        // Cycle through status messages
        let idx = 0;
        _typingTimer = setInterval(() => {
            idx = (idx + 1) % msgs.length;
            const el = document.getElementById('typing-status');
            if (el) el.textContent = msgs[idx];
        }, isMatching ? 1800 : 2500);
    }
    function hideTyping() {
        if (_typingTimer) { clearInterval(_typingTimer); _typingTimer = null; }
        const el = document.getElementById('typing');
        if (el) el.remove();
    }

    /* ── Audit panel (existing turn explainability) ─────────────────────── */
    function openAuditPanel(turnId, btn) {
        const audit = auditStore[turnId];
        const body = document.getElementById('panel-body-audit');
        body.innerHTML = audit ? renderAudit(audit)
            : '<div class="empty-state">No analysis data for this message.</div>';
        body.querySelectorAll('.audit-section-header').forEach(h => {
            h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
        });
        if (activeTurnBtn) activeTurnBtn.classList.remove('active');
        activeTurnBtn = btn;
        if (btn) btn.classList.add('active');
        setPanelMode('audit');
    }

    // Auto-refresh the audit panel with cumulative turn data (called on every bot response)
    function refreshAuditPanel(audit) {
        // Merge new audit data into cumulative store
        if (audit.extraction_trace) cumulativeAudit.extraction_trace.push(...audit.extraction_trace);
        if (audit.ner_rejections) cumulativeAudit.ner_rejections.push(...audit.ner_rejections);
        if (audit.contradictions) cumulativeAudit.contradictions.push(...audit.contradictions);
        if (audit.gap_analysis) cumulativeAudit.gap_analysis = audit.gap_analysis; // always use latest gaps
        if (audit.per_rule_trace) cumulativeAudit.per_rule_trace = audit.per_rule_trace; // always replace — reflects current profile
        if (audit.ambiguity_flags) cumulativeAudit.ambiguity_flags.push(...audit.ambiguity_flags);
        if (audit.confidence_breakdown && Object.keys(audit.confidence_breakdown).length)
            cumulativeAudit.confidence_breakdown = audit.confidence_breakdown;
        if (audit.matching_result) cumulativeAudit.matching_result = audit.matching_result;

        // Deduplicate extraction_trace by field_path+value
        const seen = new Set();
        cumulativeAudit.extraction_trace = cumulativeAudit.extraction_trace.filter(e => {
            const key = (e.field_path||'') + '|' + (e.value||'');
            if (seen.has(key)) return false;
            seen.add(key); return true;
        });

        const body = document.getElementById('panel-body-audit');
        // If this is a fresh matching turn, show matching view; otherwise show regular audit
        // even if a prior match exists (so new extractions are visible after re-match)
        const viewAudit = audit.matching_result ? cumulativeAudit : { ...cumulativeAudit, matching_result: null };
        body.innerHTML = renderAudit(viewAudit);
        body.querySelectorAll('.audit-section-header').forEach(h => {
            h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed'));
        });
        // Auto-open the panel if not showing results/scheme
        const panel = document.getElementById('right-panel');
        if (!panel.classList.contains('open') || panelMode === null) {
            setPanelMode('audit');
        } else if (panelMode === 'audit') {
            setPanelMode('audit');
        }
    }

    function accordion(icon, title, count, body, open) {
        const badge = count > 0 ? `<span class="sect-count">${count}</span>` : '';
        return `<div class="audit-section ${open ? '' : 'collapsed'}">
          <div class="audit-section-header">
            <span class="audit-section-title">${icon} ${title} ${badge}</span>
            <span class="chevron">▼</span>
          </div>
          <div class="audit-section-body">${body || '<div class="empty-state">None</div>'}</div>
        </div>`;
    }
    function statusChip(v) {
        const l = (v||'').toLowerCase();
        const cls = l === 'high' || l === 'pass' ? 'chip-ok'
                  : l === 'medium' || l === 'warn' ? 'chip-warn'
                  : l === 'low' || l === 'reject' || l === 'fail' ? 'chip-fail'
                  : 'chip-info';
        return `<span class="${cls}">${esc(v)}</span>`;
    }

    function renderAudit(a) {
        // If this is a matching turn, show matching-specific audit
        if (a.matching_result) {
            return renderMatchingAudit(a);
        }
        return [
            renderExtraction(a.extraction_trace || []),
            renderNER(a.ner_rejections || []),
            renderContradictions(a.contradictions || []),
            renderGaps(a.gap_analysis || []),
            renderConfidence(a.confidence_breakdown || {}),
            renderRules(a.per_rule_trace || []),
            renderAmbiguity(a.ambiguity_flags || []),
        ].join('');
    }

    function renderMatchingAudit(a) {
        const mr = a.matching_result;
        const schemes = mr.scheme_results || [];
        const eligible = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS');
        const nearMiss = schemes.filter(s => s.status === 'NEAR_MISS');

        // Show rule trace from top eligible schemes
        const ruleRows = (a.per_rule_trace || []).map(r => {
            const icon = r.passed === true ? '✅' : r.passed === false ? '❌' : '❓';
            return `<div class="audit-card" style="border-left:3px solid ${r.passed===true?'var(--success)':r.passed===false?'var(--danger)':'var(--border)'}">
              <div class="field-row">
                <span style="font-weight:700;font-size:0.8rem">${icon} ${esc(r.scheme_name)}</span>
              </div>
              <div style="color:var(--text-body);font-size:0.76rem;margin-top:0.2rem">${esc(r.description || r.rule_id || '')}</div>
              ${r.user_value != null ? `<div class="field-row" style="margin-top:0.3rem"><span class="fl">Your value</span><span class="fv mono">${esc(String(r.user_value))}</span></div>` : ''}
              ${r.rule_value != null ? `<div class="field-row"><span class="fl">Required</span><span class="fv mono">${esc(String(r.rule_value))}</span></div>` : ''}
            </div>`;
        }).join('');

        const confBody = `<div style="padding:0.3rem;font-size:0.78rem">
          <div>Total evaluated: <strong>${mr.total_evaluated || schemes.length}</strong></div>
          <div>Eligible: <strong style="color:var(--success)">${eligible.length}</strong></div>
          <div>Almost eligible: <strong style="color:var(--warning)">${nearMiss.length}</strong></div>
          <div style="margin-top:0.5rem;color:var(--text-soft)">Click 'View Results' to see all scheme details with full rule traces.</div>
        </div>`;

        return [
            accordion('📊', t('matchSummary'), 0, confBody, true),
            renderGaps(a.gap_analysis || []),
            ruleRows.length ? accordion('⚖️', t('sampleRules'), a.per_rule_trace.length, ruleRows, true) : '',
            renderExtraction(a.extraction_trace || []),
            renderNER(a.ner_rejections || []),
        ].join('');
    }

    function renderExtraction(items) {
        const body = items.map(e => `
          <div class="audit-card">
            <div class="field-row"><span class="fl">Source</span><span class="fv mono">"${esc(e.source_span)}"</span></div>
            <div class="field-row"><span class="fl">Field</span><span class="fv">${esc(e.field_label)} <span style="color:var(--text-hint);font-size:0.7rem">(${esc(e.field_path)})</span></span></div>
            <div class="field-row"><span class="fl">Value</span><span class="fv mono">${esc(e.value)}</span></div>
            <div class="field-row"><span class="fl">Confidence</span>${statusChip(e.confidence)}</div>
            ${e.reasoning ? `<div style="color:var(--text-soft);font-size:0.74rem;margin-top:0.3rem;line-height:1.4">${esc(e.reasoning)}</div>` : ''}
          </div>`).join('');
        return accordion('📥', t('extracted'), items.length, body, items.length > 0);
    }
    function renderNER(items) {
        if (!items.length) return accordion('✅', t('factCheck'), 0, '<div class="empty-state">All values passed verification.</div>', true);
        const body = items.map(r => `
          <div class="audit-card" style="border-left:3px solid var(--danger)">
            <div class="field-row"><span class="fl">Field</span><span class="fv mono">${esc(r.field_path)}</span></div>
            <div class="field-row"><span class="fl">Rejected</span><span class="fv" style="color:var(--danger)">${esc(r.rejected_value)}</span></div>
            <div class="field-row"><span class="fl">Reason</span><span class="fv" style="color:var(--text-soft)">${esc(r.reason)}</span></div>
          </div>`).join('');
        return accordion('⚠️', t('factIssues'), items.length, body, true);
    }
    function renderContradictions(items) {
        if (!items.length) return accordion('✅', t('consistency'), 0, '<div class="empty-state">No contradictions found.</div>', false);
        const body = items.map(c => `
          <div class="audit-card" style="border-left:3px solid ${c.severity === 'blocking' ? 'var(--danger)' : 'var(--warning)'}">
            <div class="field-row"><span class="fl">Field</span><span class="fv">${esc(c.field)}</span></div>
            <div class="field-row"><span class="fl">Conflict</span><span class="fv">${esc(c.existing_value)} → ${esc(c.new_value)}</span></div>
            <div class="field-row"><span class="fl">Severity</span>${statusChip(c.severity)}</div>
          </div>`).join('');
        return accordion('⚠️', t('consistencyIssues'), items.length, body, true);
    }
    function schemeGapsHtml(arr) {
        const gaps = (arr||[]).filter(function(g){ return g && g.trim(); });
        if (!gaps.length) return '';
        return '<div style="color:var(--warning);font-size:0.73rem;margin-top:0.25rem">Gaps: ' + gaps.map(function(g){ return esc(g); }).join(', ') + '</div>';
    }
    function renderSchemeCtx(items) {
        if (!items.length) return accordion('🏛️', 'Relevant Schemes', 0, '', false);
        const body = items.map(s => `
          <div class="audit-card">
            <div class="field-row">
              <span class="fv" style="font-weight:700">${esc(s.scheme_name)}</span>
              <span style="margin-left:auto">${statusChip(s.relevance)}</span>
            </div>
            <div style="color:var(--text-soft);font-size:0.74rem;margin-top:0.3rem">${esc(s.why_relevant)}</div>
            ${schemeGapsHtml(s.profile_gaps)}
          </div>`).join('');
        return accordion('🏛️', 'Relevant Schemes', items.length, body, false);
    }
    function renderGaps(items) {
        if (!Array.isArray(items) || !items.length) return accordion('📋', 'Missing Info', 0,
            '<div class="empty-state">All essential info collected! Run eligibility check to see results.</div>', false);
        // Filter out items with no actual impact (affects_schemes=0 or no field_label)
        const filtered = items.filter(g => (g.affects_schemes || 0) > 0 && (g.field_label || g.field_path));
        if (!filtered.length) return accordion('📋', 'Missing Info', 0,
            '<div class="empty-state">All essential info collected! Run eligibility check to see results.</div>', false);
        const sorted = filtered.slice().sort((a,b) => (b.affects_schemes||0) - (a.affects_schemes||0));
        const body = sorted.map((g, i) => {
            const n = g.affects_schemes || 0;
            return `<div class="audit-card" style="border-left:3px solid var(--saffron)">
              <div class="field-row" style="align-items:center">
                <span class="doc-num" style="flex-shrink:0">${i+1}</span>
                <span class="fv" style="font-weight:700">${esc(g.field_label || g.field_path)}</span>
              </div>
              <div style="font-size:0.73rem;color:var(--warning);margin-top:0.2rem">
                ⚠ Needed by ${n} scheme${n!==1?'s':''}
              </div>
              ${g.fix_instruction ? `<div style="color:var(--text-soft);font-size:0.73rem;margin-top:0.2rem">💡 ${esc(g.fix_instruction)}</div>` : ''}
            </div>`;
        }).join('');
        return accordion('📋', 'Missing Info', filtered.length, body, true);
    }
    function renderConfidence(cb) {
        if (!Object.keys(cb).length) return accordion('📊', 'Confidence', 0, '', false);
        const pc = Math.round((cb.profile_completeness || 0) * 100);
        const eq = Math.round((cb.extraction_quality || 0) * 100);
        const cf = cb.contradiction_free;
        const pcHint = pc < 40 ? 'Share more details to improve accuracy'
                      : pc < 70 ? 'Good start — a few more answers help'
                      : 'Profile well filled — results will be accurate';
        const body = `<div style="padding:0.3rem">
          <div class="conf-breakdown-row">
            <span class="conf-breakdown-label" title="How much of your profile is filled in">Profile filled</span>
            <div class="conf-bar-wrap"><div class="conf-bar ${confBarClass(pc)}" style="width:${pc}%"></div></div>
            <span class="conf-val">${pc}%</span>
          </div>
          <div style="font-size:0.7rem;color:var(--text-hint);margin:0.15rem 0 0.4rem">${pcHint}</div>
          <div class="conf-breakdown-row">
            <span class="conf-breakdown-label" title="How accurately I understood what you said">Accuracy</span>
            <div class="conf-bar-wrap"><div class="conf-bar ${confBarClass(eq)}" style="width:${eq}%"></div></div>
            <span class="conf-val">${eq}%</span>
          </div>
          <div class="conf-breakdown-row" style="margin-top:0.4rem">
            <span class="conf-breakdown-label">No contradictions</span>
            <div style="flex:1"></div>
            <span style="color:${cf ? 'var(--success)' : 'var(--danger)'};font-weight:700;font-size:0.8rem">${cf ? '✓ All consistent' : '✗ Conflict found'}</span>
          </div>
        </div>`;
        return accordion('📊', t('confidence'), 0, body, true);
    }
    function renderRules(items) {
        if (!items.length) return accordion('⚖️', t('rules'), 0,
            '<div class="empty-state">I check eligibility rules as you share information. Rules will appear here as they are evaluated.</div>', false);
        // Group by scheme_name
        const byScheme = {};
        items.forEach(r => {
            const k = r.scheme_name || r.scheme_id || 'Unknown';
            if (!byScheme[k]) byScheme[k] = [];
            byScheme[k].push(r);
        });
        const body = Object.entries(byScheme).map(([schemeName, rules]) => {
            const passed = rules.filter(r => r.passed === true).length;
            const failed = rules.filter(r => r.passed === false).length;
            const undet = rules.length - passed - failed;
            const ruleRows = rules.map(r => {
                const icon = r.passed === true ? '✅' : r.passed === false ? '❌' : '❓';
                return `<div style="display:flex;gap:0.5rem;align-items:flex-start;padding:0.3rem 0;border-bottom:1px solid var(--border)">
                  <span style="flex-shrink:0">${icon}</span>
                  <div style="flex:1">
                    <div style="font-size:0.76rem;color:var(--text-body)">${esc(r.description || r.rule_id || '')}</div>
                    ${r.user_value != null ? `<div style="font-size:0.7rem;color:var(--text-hint)">Your value: <span style="color:var(--text-body);font-family:var(--font-mono)">${esc(String(r.user_value))}</span></div>` : 
                      '<div style="font-size:0.7rem;color:var(--text-hint)">Not yet provided</div>'}
                  </div>
                </div>`;
            }).join('');
            return `<div class="audit-card">
              <div style="font-weight:700;font-size:0.8rem;margin-bottom:0.35rem">${esc(schemeName)}</div>
              <div style="font-size:0.71rem;color:var(--text-hint);margin-bottom:0.4rem">✅ ${passed} passed &nbsp; ❌ ${failed} failed &nbsp; ❓ ${undet} unknown</div>
              ${ruleRows}
            </div>`;
        }).join('');
        return accordion('⚖️', t('rules'), items.length, body, true);
    }
    function renderAmbiguity(items) {
        if (!items.length) return accordion('🔮', t('ambiguity'), 0, '<div class="empty-state">None identified</div>', false);
        const body = items.map(a => `
          <div class="audit-card">
            <div class="field-row">
              <span class="fv mono" style="color:var(--saffron)">${esc(a.amb_id || '')}</span>
              ${statusChip(a.severity || '')}
            </div>
            <div style="font-size:0.76rem;color:var(--text-body);margin-top:0.2rem">${esc(a.type_name || '')}: ${esc(a.description || '')}</div>
          </div>`).join('');
        return accordion('🔮', t('ambiguity'), items.length, body, false);
    }

    /* ── Applied schemes helpers ─────────────────────────────────────────── */
    function _saveApplied() {
        localStorage.setItem('cbc_applied', JSON.stringify([...appliedSchemes]));
        const n = appliedSchemes.size;
        document.getElementById('applied-count-hdr').textContent = n;
        document.getElementById('applied-count-bar').textContent = n;
        const btn = document.getElementById('applied-btn');
        btn.style.display = n > 0 ? '' : 'none';
    }
    function applyScheme(schemeName) {
        if (appliedSchemes.has(schemeName)) {
            // Already applied — show detail instead
            const schemes = currentResult && currentResult.scheme_results || [];
            const scheme = schemes.find(s => (s.name || s.scheme_name) === schemeName);
            if (scheme) { showSchemeDetail(scheme); return; }
        }
        appliedSchemes.add(schemeName);
        _saveApplied();
        // Refresh the current tab to update button states
        if (currentResult) switchTab(currentTab);
    }
    function applyAllEligible() {
        if (!currentResult) return;
        const eligible = (currentResult.scheme_results || [])
            .filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS')
            .map(s => s.name || s.scheme_name);
        eligible.forEach(n => appliedSchemes.add(n));
        _saveApplied();
        if (currentResult) switchTab(currentTab);
        showToast(`✅ ${eligible.length} scheme${eligible.length !== 1 ? 's' : ''} marked in your applied list`);
    }
    function openAppliedModal() {
        const modal = document.getElementById('applied-modal');
        document.getElementById('applied-modal-title').textContent = t('appliedTitle');
        const list = document.getElementById('applied-scheme-list');
        if (appliedSchemes.size === 0) {
            list.innerHTML = `<div class="applied-modal-empty">${t('appliedEmpty')}</div>`;
        } else {
            list.innerHTML = [...appliedSchemes].map(name => `
              <div class="applied-scheme-row">
                <span class="asr-icon">✅</span>
                <span class="asr-name">${esc(name)}</span>
                <button class="asr-remove" onclick="removeApplied(${JSON.stringify(name)})">✕</button>
              </div>`).join('');
        }
        document.getElementById('applied-modal-count').textContent = t('appliedCount')(appliedSchemes.size);
        modal.style.display = 'flex';
    }
    function closeAppliedModal() {
        document.getElementById('applied-modal').style.display = 'none';
    }
    function removeApplied(name) {
        appliedSchemes.delete(name);
        _saveApplied();
        openAppliedModal();
        if (currentResult) switchTab(currentTab);
    }
    function clearAllApplied() {
        appliedSchemes.clear();
        _saveApplied();
        openAppliedModal();
        if (currentResult) switchTab(currentTab);
    }

    /* ── HTTP communication ────────────────────────────────────────────── */
    function handleResponse(data) {
        const tid = turnCount++;
        hideTyping();
        sendBtn.disabled = false;
        sessionToken = data.session_token || sessionToken;
        // Persist token so session survives page reload
        if (data.session_token) {
            localStorage.setItem('cbc_session_token', data.session_token);
        }

        const audit = data.turn_audit || {};
        // Always refresh panel on resume so analysis is restored, even if audit is sparse
        if (Object.keys(audit).length || data.is_resume) {
            auditStore[tid] = audit;
            // Auto-refresh the shared analysis panel with cumulative data
            refreshAuditPanel(audit);
        }

        setStatus(true);

        // Matching result → open results panel (no bloated card in chat)
        const matchResult = audit.matching_result || null;
        const isResume = !!data.is_resume;
        if (matchResult && data.matching_triggered) {
            currentResult = matchResult;
            renderResultsStats();
            // Show brief conversational text in chat only
            // On resume: skip the "Welcome back!" if chat already has messages
            const text = data.text || data.response || '';
            const chatIsEmpty = chatContainer.querySelectorAll('.message-wrapper').length === 0;
            if (text && (!isResume || chatIsEmpty)) addMessage(text, 'bot', tid);
            // Show View Results button in header always
            document.getElementById('view-results-btn').style.display = '';
            if (isResume) {
                // On resume: just show a "tap to view" notice, don't auto-open panel
                const chip = document.createElement('div');
                chip.className = 'results-chip';
                chip.innerHTML = `<span>📊 Previous results restored — <button class="chip-view-btn" onclick="openResultsPanel('eligible')">View Report →</button></span>`;
                if (chatContainer) chatContainer.appendChild(chip);
                matchingDone = true;
            } else {
                // First match: add chip + auto-open
                addResultsChip(matchResult);
                openResultsPanel('eligible');
                if (!matchingDone) {
                    matchingDone = true;
                    setTimeout(() => {
                        addMessage(t('refinePrompt'), 'bot', null);
                    }, 800);
                }
            }
        } else {
            const text = data.text || data.response || '';
            // On resume: skip the "Welcome back!" greeting if chat already has messages
            const chatIsEmpty2 = chatContainer.querySelectorAll('.message-wrapper').length === 0;
            if (text && (!isResume || chatIsEmpty2)) addMessage(text, 'bot', tid);
        }

        // Update profile progress
        const extractions = data.extractions || [];
        if (extractions.length > 0) {
            if (!window._totalFields) window._totalFields = new Set();
            extractions.forEach(e => { if (e.field_path) window._totalFields.add(e.field_path); });
            const pct = Math.min(100, Math.round((window._totalFields.size / 10) * 100));
            if (pct > profilePct) updateProgress(pct);
        }

        // Quick replies (only early in conversation)
        if (!data.matching_triggered && turnCount <= 2) {
            showQuickReplies(currentLang === 'hi' ? QUICK_HI : QUICK_EN);
        } else {
            quickReplies.innerHTML = '';
        }
    }

    async function startHTTP() {
        try {
            const r = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: '', session_token: sessionToken }),
            });
            handleResponse(await r.json());
        } catch { addMessage('Connection failed. Please refresh the page.', 'error'); }
    }

    // Simple keywords that suggest the user is about to trigger matching
    const _MATCH_HINTS = ['check','eligib','verify','run','recheck','apply','result',
        'yojana','jaanch','patra','patrata','dekhna','dekho'];
    function _isMatchingHint(text) {
        const lower = text.toLowerCase();
        if (matchingDone) return false; // already matched — next turn is just chat
        // If profile is >40% filled and message is short, it's likely a trigger
        if (profilePct >= 40 && text.split(/\s+/).length <= 4) return true;
        return _MATCH_HINTS.some(k => lower.includes(k));
    }

    async function sendText(text, detectedLang) {
        if (!text) return;
        const lang = detectedLang || currentLang;
        addMessage(text, 'user');
        sendBtn.disabled = true;
        const isMatchingMsg = _isMatchingHint(text);
        showTyping(isMatchingMsg);
        // Guard: if session token is too large, trim it to prevent 413
        if (sessionToken.length > 2000000) {
            sessionToken = '';
            localStorage.removeItem('cbc_session_token');
            addMessage('Session was getting too large — starting fresh context. Your results are still visible above.', 'system');
        }
        try {
            const r = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, session_token: sessionToken, language: lang }),
            });
            handleResponse(await r.json());
        } catch {
            hideTyping(); sendBtn.disabled = false;
            addMessage('Could not reach the server. Please try again.', 'error');
        }
    }

    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;
        userInput.value = '';
        userInput.style.height = 'auto';
        quickReplies.innerHTML = '';
        // Auto-detect language from typed text; pass directly to server with the message
        const detectedLang = _autoDetectLang(text);
        await sendText(text, detectedLang);
    }

    /* ── Events ─────────────────────────────────────────────────────────── */
    userInput.addEventListener('input', () => {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
    });
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    sendBtn.addEventListener('click', sendMessage);

    /* ── Init ─────────────────────────────────────────────────────────── */
    setStatus(true);
    showWelcomeCard();
    startHTTP();
    // Apply stored lang pref to UI
    setLang(currentLang);
    // Init applied schemes button visibility
    _saveApplied();
    // Show language selection modal on first visit
    if (!localStorage.getItem('cbc_lang_pref')) {
        document.getElementById('lang-modal').style.display = 'flex';
    }

    /* ── Reset Session ────────────────────────────────────────────────── */
    function confirmResetSession() {
        if (confirm('Start a new conversation? Your current session and results will be cleared.')) {
            localStorage.removeItem('cbc_session_token');
            localStorage.removeItem('cbc_applied');
            location.reload();
        }
    }

    /* ── Full-Page Report ─────────────────────────────────────────────── */
    function openFullPageReport() {
        if (!currentResult) return;
        const schemes = currentResult.scheme_results || [];
        const eligible = schemes.filter(s => s.status === 'ELIGIBLE' || s.status === 'ELIGIBLE_WITH_CAVEATS');
        const nearMiss = schemes.filter(s => s.status === 'NEAR_MISS');
        const reqPre   = schemes.filter(s => s.status === 'REQUIRES_PREREQUISITE');
        const totalEval = currentResult.total_evaluated || schemes.length;

        function esc2(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

        function ruleRows(evals) {
            if (!evals || !evals.length) return '<p style="color:#999;font-size:0.8rem">No rule details available.</p>';
            return evals.map(r => {
                const ic = r.outcome === 'PASS' ? '✅' : r.outcome === 'FAIL' ? '❌' : '❓';
                const clr = r.outcome === 'PASS' ? '#2e7d32' : r.outcome === 'FAIL' ? '#c62828' : '#888';
                return `<div style="padding:0.5rem;border-left:3px solid ${clr};margin-bottom:0.4rem;background:#fafafa;border-radius:0 6px 6px 0">
                  <div style="font-size:0.78rem;font-weight:600">${ic} ${esc2(r.display_text||r.rule_id||'Rule')}</div>
                  ${r.user_value!=null?`<div style="font-size:0.72rem;color:#666;margin-top:0.2rem">Your value: <strong>${esc2(r.user_value)}</strong></div>`:''}
                  ${r.rule_value!=null?`<div style="font-size:0.72rem;color:#666">Required: <strong>${esc2(r.rule_value)}</strong></div>`:''}
                  ${r.source_quote?`<div style="font-size:0.68rem;color:#aaa;margin-top:0.2rem;font-style:italic">"${esc2(r.source_quote)}"</div>`:''}
                </div>`;
            }).join('');
        }

        function schemeCard(s, expanded) {
            const pct = s.confidence_breakdown ? (s.confidence_breakdown.composite_pct||0) : Math.round((s.confidence||0)*100);
            const barClr = pct >= 65 ? '#2e7d32' : pct >= 40 ? '#e65100' : '#999';
            const statusBadge = s.status === 'ELIGIBLE' ? '<span style="background:#e8f5e9;color:#2e7d32;padding:2px 8px;border-radius:6px;font-size:0.68rem;font-weight:700">ELIGIBLE</span>'
                : s.status === 'ELIGIBLE_WITH_CAVEATS' ? '<span style="background:#fff8e1;color:#f57f17;padding:2px 8px;border-radius:6px;font-size:0.68rem;font-weight:700">ELIGIBLE*</span>'
                : s.status === 'NEAR_MISS' ? '<span style="background:#fff3e0;color:#e65100;padding:2px 8px;border-radius:6px;font-size:0.68rem;font-weight:700">ALMOST</span>'
                : '<span style="background:#f5f5f5;color:#888;padding:2px 8px;border-radius:6px;font-size:0.68rem;font-weight:700">${esc2(s.status)}</span>';
            const id = 'sc-' + esc2(s.id||s.name||Math.random());
            return `<div class="scheme-card" id="${id}">
              <div class="scheme-header" onclick="toggleCard('${id}')">
                <div style="flex:1">
                  <div style="font-weight:700;font-size:0.9rem;margin-bottom:0.3rem">${esc2(s.name)}</div>
                  <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
                    ${statusBadge}
                    <div style="flex:1;min-width:80px;max-width:140px">
                      <div style="background:#eee;border-radius:4px;height:5px;overflow:hidden">
                        <div style="background:${barClr};width:${pct}%;height:100%"></div>
                      </div>
                    </div>
                    <span style="font-size:0.72rem;font-weight:700;color:${barClr}">${pct}%</span>
                    ${s.ministry ? `<span style="font-size:0.68rem;color:#999">${esc2(s.ministry)}</span>` : ''}
                  </div>
                  ${s.gap?`<div style="font-size:0.75rem;color:#666;margin-top:0.3rem">${esc2(s.gap)}</div>`:''}
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.4rem;margin-left:0.8rem">
                  <a href="#" onclick="applyScheme(event,'${esc2(s.id||s.name)}')" style="background:#FF9933;color:#fff;padding:0.3rem 0.9rem;border-radius:8px;text-decoration:none;font-size:0.75rem;font-weight:700;white-space:nowrap">Apply →</a>
                  <span style="font-size:0.7rem;color:#aaa">${s.rule_evaluations&&s.rule_evaluations.length?s.rule_evaluations.length+' rules':''}</span>
                </div>
              </div>
              <div class="scheme-detail ${expanded?'':'collapsed'}" id="${id}-detail">
                <hr style="border:none;border-top:1px solid #eee;margin:0.8rem 0">
                <div style="font-size:0.8rem;font-weight:700;color:#555;margin-bottom:0.5rem">Rule Evaluations</div>
                ${ruleRows(s.rule_evaluations)}
                ${s.caveats&&s.caveats.length?`<div style="margin-top:0.6rem;font-size:0.75rem;color:#e65100"><strong>⚠️ Caveats:</strong> ${s.caveats.map(c=>esc2(c)).join('; ')}</div>`:''}
              </div>
            </div>`;
        }

        function tabContent(list, emptyMsg) {
            if (!list.length) return `<div style="text-align:center;padding:3rem;color:#aaa">${emptyMsg}</div>`;
            return list.map(s => schemeCard(s, false)).join('');
        }

        const docItems = [];
        (currentResult.document_checklist||[]).forEach(d => {
            docItems.push(`<div style="background:#fff;border:1px solid #e0d8cc;border-radius:8px;padding:0.8rem 1rem;margin-bottom:0.5rem">
              <div style="font-weight:700;font-size:0.85rem">${esc2(d.name||d.document_name||'Document')}</div>
              ${d.required_by&&d.required_by.length?`<div style="font-size:0.72rem;color:#888;margin-top:0.2rem">Required by: ${d.required_by.slice(0,3).map(n=>esc2(n)).join(', ')}${d.required_by.length>3?' +more':''}</div>`:''}
              ${d.mandatory===false?'<span style="color:#888;font-size:0.68rem">Optional</span>':'<span style="color:#c62828;font-size:0.68rem">Mandatory</span>'}
            </div>`);
        });

        const fullHtml = `<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Eligibility Report — Sahayak</title>
<style>
  *{box-sizing:border-box}
  body{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:0;background:#f8f6f1;color:#1a1a1a}
  header{background:linear-gradient(135deg,#FF9933,#e07800);color:#fff;padding:1rem 2rem;display:flex;align-items:center;gap:1rem;position:sticky;top:0;z-index:10;box-shadow:0 2px 8px rgba(0,0,0,.15)}
  header h1{margin:0;font-size:1.2rem;font-weight:800}
  .stats{display:grid;grid-template-columns:repeat(3,1fr);background:#fff;border-bottom:2px solid #e0d8cc}
  .stat{text-align:center;padding:1rem;border-right:1px solid #e0d8cc}
  .stat:last-child{border-right:none}
  .stat-num{font-size:2.2rem;font-weight:900;line-height:1}
  .stat-num.e{color:#2e7d32}.stat-num.n{color:#e65100}.stat-num.i{color:#999}
  .stat-lbl{font-size:0.65rem;font-weight:700;letter-spacing:.05em;color:#888;margin-top:0.2rem}
  .tabs{display:flex;background:#fff;border-bottom:2px solid #e0d8cc;position:sticky;top:57px;z-index:9}
  .tab-btn{flex:1;padding:0.8rem 0.5rem;background:none;border:none;border-bottom:3px solid transparent;cursor:pointer;font-size:0.8rem;font-weight:700;color:#888;transition:.2s}
  .tab-btn.active{color:#FF9933;border-bottom-color:#FF9933}
  .tab-panel{display:none;padding:1.2rem 1.5rem}
  .tab-panel.active{display:block}
  .search-bar{padding:0 1.5rem;margin:0.8rem 0}
  .search-bar input{width:100%;padding:0.5rem 0.8rem;border:1.5px solid #ddd;border-radius:8px;font-size:0.85rem;outline:none}
  .search-bar input:focus{border-color:#FF9933}
  .scheme-card{background:#fff;border:1.5px solid #e0d8cc;border-radius:12px;padding:0.9rem 1rem;margin-bottom:0.6rem;transition:.15s}
  .scheme-card:hover{border-color:#FF9933;box-shadow:0 2px 8px rgba(255,153,51,.15)}
  .scheme-header{display:flex;align-items:flex-start;cursor:pointer;user-select:none}
  .scheme-detail{overflow:hidden}.scheme-detail.collapsed{display:none}
  .apply-all{display:block;width:calc(100% - 3rem);margin:0.5rem 1.5rem;padding:0.8rem;background:#2e7d32;color:#fff;border:none;border-radius:10px;font-size:0.9rem;font-weight:700;cursor:pointer;text-align:center}
  .apply-all:hover{background:#1b5e20}
  @media(max-width:600px){.stats{grid-template-columns:repeat(3,1fr)}.tab-btn{font-size:0.7rem;padding:0.6rem 0.3rem}}
  @media print{.tabs,.search-bar{display:none!important}.tab-panel{display:block!important}}
</style>
</head><body>
<header><span style="font-size:1.8rem">🇮🇳</span><div><h1>Sahayak — Your Eligibility Report</h1><div style="font-size:0.75rem;opacity:.85">${totalEval.toLocaleString()} schemes evaluated</div></div></header>
<div class="stats">
  <div class="stat"><div class="stat-num e">${eligible.length}</div><div class="stat-lbl">ELIGIBLE</div></div>
  <div class="stat"><div class="stat-num n">${nearMiss.length}</div><div class="stat-lbl">ALMOST</div></div>
  <div class="stat"><div class="stat-num i">${totalEval-eligible.length-nearMiss.length}</div><div class="stat-lbl">NOT ELIGIBLE</div></div>
</div>
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('eligible',this)">✅ Eligible (${eligible.length})</button>
  <button class="tab-btn" onclick="switchTab('near',this)">🔶 Almost (${nearMiss.length})</button>
  <button class="tab-btn" onclick="switchTab('docs',this)">📄 Documents</button>
  <button class="tab-btn" onclick="switchTab('apply',this)">🚀 How to Apply</button>
</div>
<div class="search-bar"><input type="search" id="scheme-search" placeholder="Search schemes…" oninput="filterSchemes(this.value)"></div>
<button class="apply-all" onclick="alert('Portal link integration coming soon. Download this report and visit myscheme.gov.in')">⚡ Apply for All Eligible Schemes</button>
<div id="tab-eligible" class="tab-panel active">${tabContent(eligible,'No eligible schemes found with the current profile.')}</div>
<div id="tab-near" class="tab-panel">${tabContent(nearMiss,'No near-miss schemes found.')}</div>
<div id="tab-docs" class="tab-panel">${docItems.length?docItems.join(''):'<p style="color:#999;text-align:center;padding:2rem">Document checklist not available. Complete more profile fields.</p>'}</div>
<div id="tab-apply" class="tab-panel">
  <div style="background:#fff;border-radius:12px;padding:1.2rem;border:1.5px solid #e0d8cc">
    <h3 style="margin:0 0 0.8rem;font-size:0.95rem">How to Apply for Government Schemes</h3>
    <ol style="font-size:0.85rem;line-height:1.8;color:#444;margin:0;padding-left:1.2rem">
      <li>Visit <a href="https://myscheme.gov.in" target="_blank" style="color:#FF9933">myscheme.gov.in</a> — India's official scheme portal</li>
      <li>Search for each eligible scheme by name</li>
      <li>Check the "Apply" button on the scheme page for the official portal link</li>
      <li>Keep your Aadhaar, bank account passbook, and income certificate ready</li>
      <li>State-level schemes: visit your district collectorate or CSC (Common Service Centre)</li>
    </ol>
    <div style="background:#fff3e0;border-radius:8px;padding:0.8rem;margin-top:0.8rem;font-size:0.78rem;color:#e65100">
      ⚠️ This report is generated based on the profile you provided. Always verify eligibility on the official scheme portal before applying.
    </div>
  </div>
  <div style="margin-top:1rem">
    <h3 style="font-size:0.9rem;padding:0 0 0.3rem;margin:0 0 0.8rem">Your Eligible Schemes — Quick Reference</h3>
    ${eligible.map(s=>`<div style="background:#fff;border:1px solid #e8f5e9;border-left:4px solid #2e7d32;border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.5rem;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:0.85rem;font-weight:600">${esc2(s.name)}</span>
      <a href="https://myscheme.gov.in/search?q=${encodeURIComponent(s.name)}" target="_blank" style="background:#FF9933;color:#fff;padding:0.25rem 0.7rem;border-radius:6px;text-decoration:none;font-size:0.72rem;font-weight:700;white-space:nowrap">Find →</a>
    </div>`).join('')}
  </div>
</div>
<script>
function switchTab(id, btn) {
    document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.getElementById('tab-'+id).classList.add('active');
    btn.classList.add('active');
}
function toggleCard(id) {
    const detail = document.getElementById(id+'-detail');
    if (detail) detail.classList.toggle('collapsed');
}
function filterSchemes(q) {
    const lower = q.toLowerCase();
    document.querySelectorAll('.scheme-card').forEach(card => {
        const name = card.querySelector('[style*="font-weight:700"]');
        const matches = !q || (name && name.textContent.toLowerCase().includes(lower));
        card.style.display = matches ? '' : 'none';
    });
}
function applyScheme(e, schemeId) {
    e.preventDefault();
    const url = 'https://myscheme.gov.in/search?q=' + encodeURIComponent(schemeId);
    window.open(url, '_blank');
}
// Expand all on print
window.onbeforeprint = () => document.querySelectorAll('.scheme-detail').forEach(d=>d.classList.remove('collapsed'));
<\/script>
</body></html>`;
        const w = window.open('', '_blank');
        if (w) { w.document.write(fullHtml); w.document.close(); }
    }
    </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes — updated to pass turn_audit in every response
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the chat interface."""
    return HTMLResponse(content=_CHAT_HTML)


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """Handle WebSocket-based conversation.

    Security controls applied:
      - Origin header checked (rejects cross-site WebSocket hijacking)
      - Per-IP connection limit enforced
      - All incoming messages sanitised and length-capped
      - Errors counted per IP; alert sent on repeated abuse patterns

    Protocol:
      Client → { action: "start", language: "en"|"hi" }
      Client → { action: "message", message: "...", token: "..." }
      Server → { text, session_token, state, extractions,
                 matching_triggered, turn_audit }
    """
    # --- Cross-Site WebSocket Hijacking (CSWSH) prevention ---
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    allowed_origins = {
        f"http://{host}",
        f"https://{host}",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    }
    if origin and origin not in allowed_origins:
        logger.warning("Rejected WS from disallowed origin: %s", origin)
        await websocket.close(code=1008)  # Policy Violation
        return

    # --- Per-IP connection limit ---
    client_ip = getattr(websocket.client, "host", "unknown")
    if _ws_connections[client_ip] >= _RATE_LIMIT_WS_PER_IP:
        logger.warning("WS connection limit exceeded for %s", client_ip)
        await websocket.close(code=1008)
        return

    _ws_connections[client_ip] += 1
    await websocket.accept()
    session_token = ""

    try:
        while True:
            raw = await websocket.receive_text()

            # Reject oversized frames
            if len(raw) > _MAX_BODY_BYTES:
                await websocket.send_json({"error": "Message too large."})
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"action": "message", "message": raw}

            action = data.get("action", "message")
            is_resume = False  # flag: this response is a session restore

            if action == "start":
                language = data.get("language", "en")
                if language not in ("en", "hi", "hinglish"):
                    language = "en"
                # Get token from client (if resuming an existing session)
                existing_token = data.get("token", "")
                # For stateless sessions, just try to decode the token
                # If it's valid, resume; if not or invalid, start new session
                if existing_token:
                    try:
                        from src.conversation.session import ConversationSession
                        sess = ConversationSession.from_token(existing_token)
                        if sess.current_state != "ENDED":
                            # Use resume_session with language override if provided
                            response = await _engine.resume_session(
                                existing_token, language=language
                            )
                            is_resume = True
                        else:
                            # Session ended, start fresh
                            response = await _engine.start_session(language=language)
                            is_resume = False
                    except Exception:
                        # Token invalid/expired, start fresh
                        response = await _engine.start_session(language=language)
                        is_resume = False
                else:
                    response = await _engine.start_session(language=language)
                    is_resume = False
            elif action == "set_language":
                # Language toggle — update session language without a new turn
                language = data.get("language", "en")
                if language not in ("en", "hi", "hinglish"):
                    language = "en"
                # For stateless sessions, we don't persist language preference across turns
                # It's sent with each message if needed
                await websocket.send_json({"ack": "language_set", "language": language})
                continue
            else:
                # Sanitise user input before passing to the engine
                message = _sanitise_input(str(data.get("message", "")))
                token = data.get("token", session_token)
                # Client-side language hint (for new sessions only)
                client_lang = data.get("language")
                # Send a quick "thinking" hint before the full LLM pipeline
                await websocket.send_json({"type": "thinking", "text": _get_thinking_hint(message)})
                if not token:
                    response = await _engine.start_session(language=client_lang or "en")
                else:
                    response = await _engine.process_message(
                        session_token=token,
                        user_message=message,
                    )

            session_token = response.session_token

            await websocket.send_json({
                "text": response.text,
                "text_en": response.text_en,
                "state": response.state_after,
                "session_token": response.session_token,
                "extractions": response.extractions,
                "matching_triggered": response.matching_triggered,
                "turn_audit": _trim_audit_for_wire(response.turn_audit),
                "is_resume": is_resume,
            })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected (%s)", client_ip)
    except Exception as exc:
        _ws_errors[client_ip] += 1
        logger.exception("WebSocket error from %s: %s", client_ip, exc)
        if _ws_errors[client_ip] >= 10:
            asyncio.ensure_future(
                alert_repeated_ws_failure(client_ip, _ws_errors[client_ip])
            )
        try:
            await websocket.send_json({"error": "An error occurred. Please reload."})
        except Exception:
            pass
    finally:
        _ws_connections[client_ip] = max(0, _ws_connections[client_ip] - 1)


@app.post("/api/chat")
async def http_chat(request: Request) -> dict[str, Any]:
    """HTTP fallback for environments without WebSocket.

    Request:  ``{"message": str, "session_token": str | null}``
    Response: ``{"response": str, "session_token": str, "state": str,
                  "turn_audit": dict}``

    Security: body size capped by RateLimitMiddleware; message sanitised here.
    """
    try:
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            return JSONResponse({"error": "Request body too large."}, status_code=413)
        data = json.loads(body)
    except (json.JSONDecodeError, Exception):
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    # Sanitise inputs
    message = _sanitise_input(str(data.get("message", "")))
    session_token = str(data.get("session_token", "") or "")

    if not session_token:
        response = await _engine.start_session()
    else:
        response = await _engine.process_message(
            session_token=session_token,
            user_message=message,
        )

    return {
        "response": response.text,
        "text_en": response.text_en,
        "session_token": response.session_token,
        "state": response.state_after,
        "extractions": response.extractions,
        "matching_triggered": response.matching_triggered,
        "turn_audit": response.turn_audit,
    }


@app.get("/debug/public-files")
async def debug_public_files():
    """Debug: show loaded public files and path resolution."""
    return {
        "public_dir": str(_public_dir),
        "public_dir_exists": _public_dir.exists() if _public_dir else False,
        "loaded_files": {k: len(v) for k, v in _PUBLIC_FILES.items()},
        "cwd": str(Path.cwd()),
        "file": str(Path(__file__).resolve()),
    }


# Serve public HTML/PDF files at root level for backward compatibility
@app.get("/{filename:path}", response_class=Response)
async def serve_public_files(filename: str) -> Response:
    """Serve HTML, PDF, and JS files from pre-loaded memory cache."""
    if not filename:
        return Response(status_code=404)
    
    # Serve from memory cache (loaded at startup)
    if filename in _PUBLIC_FILES:
        suffix = Path(filename).suffix
        content_type = _PUBLIC_TYPES.get(suffix, "application/octet-stream")
        return Response(content=_PUBLIC_FILES[filename], media_type=content_type)
    
    return Response(status_code=404)
