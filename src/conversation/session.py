"""Session management for CBC Part 5 — Conversational Interface.

Manages conversation state, profile accumulation, turn history, and
client-side session tokens (base64-encoded, zlib-compressed JSON). No
server-side persistence of user data — all state travels with the token.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Set

from src.conversation.config import (
    SESSION_MAX_TOKEN_SIZE_KB,
    SESSION_TTL_HOURS,
)
from src.conversation.exceptions import SessionError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provenance & change tracking
# ---------------------------------------------------------------------------


@dataclass
class FieldProvenance:
    """Tracks where a profile field value came from."""

    field_path: str
    value: Any
    source_turn: int
    source_text: str
    confidence: str  # HIGH / MEDIUM / LOW
    was_corrected: bool = False
    correction_turn: Optional[int] = None


@dataclass
class ProfileChange:
    """Record of a single profile field change within a turn."""

    field_path: str
    old_value: Any
    new_value: Any
    change_type: str  # "set" / "update" / "correct" / "what_if"
    source_turn: int


@dataclass
class ContradictionRecord:
    """Logged contradiction (resolved or pending) for audit trail."""

    contradiction_id: str
    field_path: str
    existing_value: Any
    new_value: Any
    resolution: str  # "pending" / "user_chose_new" / "user_chose_existing" / "auto_resolved"
    resolution_turn: Optional[int]
    severity: str


# ---------------------------------------------------------------------------
# Conversation turn
# ---------------------------------------------------------------------------


@dataclass
class ConversationTurn:
    """One user↔system exchange in the conversation."""

    turn_number: int
    timestamp: str
    user_message: str
    detected_language: str
    detected_intent: str

    # Extraction results
    extractions: list[dict] = field(default_factory=list)
    profile_changes: list[dict] = field(default_factory=list)

    # System response
    system_response: str = ""
    system_response_en: str = ""  # Always English (for audit)
    state_before: str = ""
    state_after: str = ""


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

# Valid conversation states
VALID_STATES: frozenset[str] = frozenset({
    "GREETING",
    "GATHERING",
    "CLARIFYING",
    "MATCHING",
    "PRESENTING",
    "EXPLORING",
    "CORRECTING",
    "ENDED",
})


@dataclass
class ConversationSession:
    """Complete state of one conversation session.

    Designed to be serialised to a client-side encrypted token so that
    no user data is persisted server-side.
    """

    session_id: str
    created_at: str
    updated_at: str
    current_state: str  # one of VALID_STATES
    previous_state: str

    # Profile being built — stored as flat dict for easy serialisation.
    # Converted to UserProfile only when calling the matching engine.
    profile_data: dict[str, Any] = field(default_factory=dict)
    field_provenance: dict[str, dict] = field(default_factory=dict)

    # Conversation history
    turns: list[dict] = field(default_factory=list)
    turn_count: int = 0

    # Matching results (serialised as dict for token portability)
    latest_result: Optional[dict] = None
    what_if_results: list[dict] = field(default_factory=list)

    # Tracking
    detected_language: str = "en"
    asked_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    contradiction_log: list[dict] = field(default_factory=list)
    # Fields inferred (not directly stated) — tracked for Type 3 contradiction detection
    # Format: {field_path: {"value": v, "inferred_from": "widow", "source_turn": 2}}
    inferred_fields: dict[str, dict] = field(default_factory=dict)
    # The last set of numbered questions shown to the user (for contextual extraction)
    # Format: [{"field_path": "applicant.age", "question": "How old are you?", "index": 1}, ...]
    last_bot_questions: list[dict] = field(default_factory=list)

    # When a blocking contradiction puts the session in CLARIFYING state, this
    # stores the pending resolution so the next turn can route correctly.
    # Format: {"field_path": str, "existing_value": str, "new_value": str, "field_label": str}
    pending_contradiction: Optional[dict] = None

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def new(cls) -> ConversationSession:
        """Create a fresh session in GREETING state."""
        now = datetime.now(tz=timezone.utc).isoformat()
        return cls(
            session_id=uuid.uuid4().hex[:16],
            created_at=now,
            updated_at=now,
            current_state="GREETING",
            previous_state="GREETING",
        )

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def transition(self, new_state: str) -> None:
        """Transition to a new conversation state.

        Raises:
            ValueError: If *new_state* is not in ``VALID_STATES``.
        """
        if new_state not in VALID_STATES:
            raise ValueError(
                f"Invalid state '{new_state}'. Must be one of {sorted(VALID_STATES)}"
            )
        self.previous_state = self.current_state
        self.current_state = new_state
        self.updated_at = datetime.now(tz=timezone.utc).isoformat()

    def add_turn(self, turn: ConversationTurn) -> None:
        """Append a completed turn to the history."""
        self.turns.append(asdict(turn))
        self.turn_count = len(self.turns)
        self.updated_at = datetime.now(tz=timezone.utc).isoformat()

    def update_profile_field(
        self,
        field_path: str,
        value: Any,
        turn_number: int,
        source_text: str = "",
        confidence: str = "HIGH",
    ) -> ProfileChange:
        """Set or overwrite a profile field and record provenance.

        Returns:
            ``ProfileChange`` describing the mutation.
        """
        old_value = self.profile_data.get(field_path)
        change_type = "set" if old_value is None else "update"

        self.profile_data[field_path] = value
        self.field_provenance[field_path] = asdict(
            FieldProvenance(
                field_path=field_path,
                value=value,
                source_turn=turn_number,
                source_text=source_text,
                confidence=confidence,
            )
        )
        self.updated_at = datetime.now(tz=timezone.utc).isoformat()

        return ProfileChange(
            field_path=field_path,
            old_value=old_value,
            new_value=value,
            change_type=change_type,
            source_turn=turn_number,
        )

    def mark_field_asked(self, field_path: str) -> None:
        """Record that we've asked the user about *field_path*."""
        if field_path not in self.asked_fields:
            self.asked_fields.append(field_path)

    def mark_field_skipped(self, field_path: str) -> None:
        """Record that the user explicitly skipped *field_path*."""
        if field_path not in self.skipped_fields:
            self.skipped_fields.append(field_path)

    def get_populated_field_paths(self) -> Set[str]:
        """Return the set of field paths that currently have values."""
        return {k for k, v in self.profile_data.items() if v is not None}

    def is_minimum_viable(self) -> bool:
        """Check whether the profile meets minimum viability for matching."""
        from src.conversation.config import MINIMUM_VIABLE_FIELDS

        populated = self.get_populated_field_paths()
        return MINIMUM_VIABLE_FIELDS.issubset(populated)

    # ------------------------------------------------------------------
    # Serialisation — client-side encrypted token
    # ------------------------------------------------------------------

    @staticmethod
    def _slim_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
        """Strip heavy fields from matching result to keep token small.
        
        Keeps scheme names and statuses (for post-results chat LLM context)
        but drops rule_evaluations, confidence_breakdown, gap_analysis, etc.
        Full results are already sent to the client via turn_audit.
        """
        if not result:
            return result
        slim_schemes = []
        for s in result.get("scheme_results", []):
            slim_schemes.append({
                "scheme_id": s.get("scheme_id"),
                "name": s.get("name"),
                "status": s.get("status"),
            })
        return {"scheme_results": slim_schemes}

    def _to_dict(self) -> dict[str, Any]:
        """Convert session to a JSON-serialisable dict.
        
        Strips heavy fields (matching results, what-if) to keep token small.
        These are already sent to the client via turn_audit and can be
        re-computed from profile_data if needed.
        """
        return {
            "v": 1,  # schema version
            "sid": self.session_id,
            "cat": self.created_at,
            "uat": self.updated_at,
            "cs": self.current_state,
            "ps": self.previous_state,
            "pd": self.profile_data,
            "fp": self.field_provenance,
            "ts": self.turns,
            "tc": self.turn_count,
            "lr": self._slim_result(self.latest_result),
            "wir": None,  # stripped — what-if results re-computed if needed
            "dl": self.detected_language,
            "af": self.asked_fields,
            "sf": self.skipped_fields,
            "cl": self.contradiction_log,
            "if": self.inferred_fields,
            "lbq": self.last_bot_questions,
            "pc": self.pending_contradiction,
            "exp": (
                datetime.now(tz=timezone.utc)
                + timedelta(hours=SESSION_TTL_HOURS)
            ).isoformat(),
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> ConversationSession:
        """Restore a session from a deserialised dict.

        Raises:
            SessionError: If the dict is missing required keys or has
                an unsupported schema version.
        """
        version = data.get("v", 0)
        if version != 1:
            raise SessionError(
                reason=f"Unsupported session schema version: {version}",
                session_id=data.get("sid"),
            )

        # Check expiry
        exp_str = data.get("exp")
        if exp_str:
            try:
                exp_dt = datetime.fromisoformat(exp_str)
                if datetime.now(tz=timezone.utc) > exp_dt:
                    raise SessionError(
                        reason="Session token has expired",
                        session_id=data.get("sid"),
                    )
            except (ValueError, TypeError):
                pass  # Non-fatal — proceed without expiry enforcement

        return cls(
            session_id=data.get("sid", uuid.uuid4().hex[:16]),
            created_at=data.get("cat", ""),
            updated_at=data.get("uat", ""),
            current_state=data.get("cs", "GREETING"),
            previous_state=data.get("ps", "GREETING"),
            profile_data=data.get("pd", {}),
            field_provenance=data.get("fp", {}),
            turns=data.get("ts", []),
            turn_count=data.get("tc", 0),
            latest_result=data.get("lr"),
            what_if_results=data.get("wir", []),
            detected_language=data.get("dl", "en"),
            asked_fields=data.get("af", []),
            skipped_fields=data.get("sf", []),
            contradiction_log=data.get("cl", []),
            inferred_fields=data.get("if", {}),
            last_bot_questions=data.get("lbq", []),
            pending_contradiction=data.get("pc"),
        )

    def to_token(self) -> str:
        """Serialise session state to a portable token.

        The payload is JSON → zlib-compressed → base64url-encoded.
        Token travels to the client (cookie or CLI file) and back.
        This is not encrypted — do not store sensitive PII in the token;
        all profile data should be treated as opaque by the transport layer.

        Raises:
            SessionError: If the serialised payload exceeds
                ``SESSION_MAX_TOKEN_SIZE_KB``.
        """
        payload = json.dumps(self._to_dict(), separators=(",", ":"), default=str)
        compressed = zlib.compress(payload.encode("utf-8"), level=6)

        # Guard against oversized tokens
        size_kb = len(compressed) / 1024
        if size_kb > SESSION_MAX_TOKEN_SIZE_KB:
            # Trim conversation history to keep the token small
            logger.warning(
                "Session payload %.1f KB exceeds limit %d KB — "
                "trimming oldest turns",
                size_kb,
                SESSION_MAX_TOKEN_SIZE_KB,
            )
            self._trim_history()
            payload = json.dumps(
                self._to_dict(), separators=(",", ":"), default=str
            )
            compressed = zlib.compress(payload.encode("utf-8"), level=6)

        return base64.urlsafe_b64encode(compressed).decode("ascii")

    @classmethod
    def from_token(cls, token: str) -> ConversationSession:
        """Restore a session from a base64url token.

        Raises:
            SessionError: If the token cannot be decoded or the payload
                cannot be parsed.
        """
        try:
            compressed = base64.urlsafe_b64decode(token.encode("ascii") + b"==")
            payload = zlib.decompress(compressed).decode("utf-8")
            data = json.loads(payload)
        except (ValueError, zlib.error, json.JSONDecodeError) as exc:
            raise SessionError(reason=f"Session token corrupt or invalid: {exc}")

        return cls._from_dict(data)

    def _trim_history(self) -> None:
        """Remove oldest turns to reduce serialised size.

        Keeps the most recent 6 turns plus the first turn (greeting).
        """
        if len(self.turns) <= 7:
            return
        first = self.turns[0]
        recent = self.turns[-6:]
        self.turns = [first] + recent
        self.turn_count = len(self.turns)
