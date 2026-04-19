"""CBC Part 5: Conversational Interface.

Bilingual (English + Hindi) conversational interface for welfare scheme
eligibility discovery. Accepts natural language input, extracts structured
profile data via LLM, runs the Part 3 matching engine, and presents
actionable results.

Public API:
    from src.conversation.engine import ConversationEngine
    from src.conversation.session import ConversationSession
"""

from __future__ import annotations
