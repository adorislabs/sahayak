"""Vercel serverless entry point for the CBC FastAPI application.

Vercel Python runtime wraps ASGI apps automatically when a file at api/index.py
exports an `app` (or `handler`) object.

Note: Vercel is a serverless platform — WebSocket connections are not supported.
The browser client will attempt WebSocket first, fail to connect, then
automatically fall back to the HTTP POST endpoint at /api/chat.
All functionality is preserved via the HTTP fallback.
"""
import os
import sys

# Make the project root importable so `src.*` imports resolve correctly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import the FastAPI app — this also loads the rule base from parsed_schemes/
from src.conversation.interfaces.web import app  # noqa: F401, E402

# `app` is the ASGI application. Vercel detects this automatically.
