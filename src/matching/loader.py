"""DMN Decision Table loader for the CBC matching engine.

Loads scheme rule sets from JSON fixture files. Handles:
- DISPUTED rule exclusion
- Review queue exclusion
- State override resolution (supersedes_rule_id chain)
- Inactive scheme filtering
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.exceptions import RuleBaseError
from src.schema import (
    AmbiguityFlag,
    AuditStatus,
    Rule,
    Scheme,
    SchemeRelationship,
    SchemeStatus,
    SourceAnchor,
)

logger = logging.getLogger(__name__)


@dataclass
class SchemeRuleSet:
    """A loaded and filtered scheme with its active rules.

    active_rules excludes DISPUTED and review-queue rules.
    state_overrides_applied records which central rules were replaced.
    """

    scheme: Scheme
    active_rules: list[Rule]
    excluded_rules_count: int
    state_overrides_applied: list[str]
    data_source_tier: int = 2  # Default Tier-2 (PDF-verified)


def _normalize_batch_rule(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a batch-format rule dict (PascalCase keys) to the snake_case
    format expected by ``_parse_rule``.

    Batch files use keys like ``Rule_ID``, ``Scheme_ID``, ``Source_URL``,
    etc. while the internal schema uses ``rule_id``, ``scheme_id``, and a
    nested ``source_anchor`` sub-dict.
    """
    # Simple lowercase pass covers most keys: Rule_ID→rule_id, Rule_Type→rule_type …
    norm: dict[str, Any] = {k.lower(): v for k, v in raw.items()}

    # Build source_anchor sub-dict from top-level source fields when absent
    if "source_anchor" not in norm:
        norm["source_anchor"] = {
            "source_url": norm.pop("source_url", ""),
            "source_quote": norm.pop("source_quote", ""),
            "document_title": norm.pop("document_title", ""),
            "notification_date": norm.pop("notification_date", "2024-01-01"),
        }
    else:
        # Remove stray top-level source keys to avoid confusion
        for k in ("source_url", "source_quote", "document_title"):
            norm.pop(k, None)

    # Batch field name aliases
    for old, new in (
        ("rule_id",    "rule_id"),
        ("scheme_id",  "scheme_id"),
        ("rule_type",  "rule_type"),
        ("condition",  "condition_type"),   # Batch uses "Condition" for condition_type
        ("data_source_tier", None),          # Extra field — drop it
        ("audit_status", "audit_status"),
    ):
        if new is None:
            norm.pop(old, None)
        elif old != new and old in norm and new not in norm:
            norm[new] = norm.pop(old)

    # Map operator aliases to canonical enum values
    op = norm.get("operator", "")
    if isinstance(op, str):
        op_upper = op.upper()
        _OP_MAP = {
            "EXISTS": "IS_NOT_NULL",
            "NOT_EXISTS": "IS_NULL",
            "NOT_EQ": "NEQ",           # non-standard alias found in some batches
        }
        if op_upper in _OP_MAP:
            norm["operator"] = _OP_MAP[op_upper]
        elif op_upper == "NOT_BETWEEN":
            # No direct inverse operator — drop the rule entirely so it
            # doesn't cause a Pydantic validation error and counts as skipped.
            norm["operator"] = "__SKIP__"

    # Drop rules with BETWEEN but missing numeric bounds (data quality issue)
    if norm.get("operator") == "BETWEEN":
        vm, vx = norm.get("value_min"), norm.get("value_max")
        # If either bound is a non-numeric string, the rule is unusable
        def _is_numeric(v: Any) -> bool:
            if v is None:
                return False
            try:
                float(v)
                return True
            except (TypeError, ValueError):
                return False
        if not _is_numeric(vm) or not _is_numeric(vx):
            norm["operator"] = "__SKIP__"

    # Batch ambiguity_flags is sometimes:
    #   - a plain string (scheme ID shorthand) → discard
    #   - a list of plain strings (flag IDs only, no structured dict) → discard
    # Only keep entries that are already dicts with the required keys.
    af_raw = norm.get("ambiguity_flags")
    if isinstance(af_raw, str):
        norm["ambiguity_flags"] = []
    elif isinstance(af_raw, list):
        norm["ambiguity_flags"] = [x for x in af_raw if isinstance(x, dict)]

    return norm


def _parse_rule(rule_dict: dict[str, Any]) -> "Rule | None":
    """Parse a single rule dict from JSON into a Rule Pydantic object.

    Returns None for rules that are intentionally skipped (e.g. unsupported
    operators, degenerate BETWEEN bounds) — caller must check for None.
    """
    anchor_dict = rule_dict.get("source_anchor", {})
    source_anchor = SourceAnchor(
        source_url=anchor_dict.get("source_url", ""),
        document_title=anchor_dict.get("document_title", ""),
        source_quote=anchor_dict.get("source_quote", ""),
        page_number=anchor_dict.get("page_number"),
        section=anchor_dict.get("section"),
        clause=anchor_dict.get("clause"),
        gazette_ref=anchor_dict.get("gazette_ref"),
        notification_date=anchor_dict.get("notification_date", "2024-01-01"),
        language=anchor_dict.get("language", "en"),
        alternate_language_ref=anchor_dict.get("alternate_language_ref"),
    )

    # Parse ambiguity flags
    ambiguity_flags: list[AmbiguityFlag] = []
    for af in rule_dict.get("ambiguity_flags", []):
        try:
            ambiguity_flags.append(
                AmbiguityFlag(
                    ambiguity_id=af["ambiguity_id"],
                    scheme_id=af["scheme_id"],
                    rule_id=af.get("rule_id"),
                    ambiguity_type_code=af["ambiguity_type_code"],
                    ambiguity_type_name=af["ambiguity_type_name"],
                    description=af["description"],
                    severity=af["severity"],
                    resolution_status=af.get("resolution_status", "OPEN"),
                )
            )
        except Exception as e:
            logger.warning("Could not parse ambiguity flag: %s — %s", af, e)

    # Rules marked __SKIP__ by normalisation (e.g. NOT_BETWEEN, degenerate BETWEEN)
    # are silently dropped here — they contribute no signal and would error Pydantic.
    if rule_dict.get("operator") == "__SKIP__":
        return None

    return Rule(
        rule_id=rule_dict["rule_id"],
        scheme_id=rule_dict["scheme_id"],
        rule_type=rule_dict["rule_type"],
        condition_type=rule_dict.get("condition_type", "unknown"),
        field=rule_dict["field"],
        operator=rule_dict["operator"],
        value=rule_dict.get("value"),
        value_min=rule_dict.get("value_min"),
        value_max=rule_dict.get("value_max"),
        values=rule_dict.get("values", []),
        unit=rule_dict.get("unit"),
        logic_group=rule_dict.get("logic_group"),
        logic_operator=rule_dict.get("logic_operator"),
        prerequisite_scheme_ids=rule_dict.get("prerequisite_scheme_ids", []),
        state_scope=rule_dict.get("state_scope", "central"),
        source_anchor=source_anchor,
        ambiguity_flags=ambiguity_flags,
        confidence=rule_dict.get("confidence", 0.5),
        audit_status=AuditStatus(rule_dict.get("audit_status", "PENDING")),
        verified_by=rule_dict.get("verified_by"),
        parse_run_id=rule_dict.get("parse_run_id", "RUN-LOAD-001"),
        version=rule_dict.get("version", "1.0.0"),
        effective_from=rule_dict.get("effective_from"),
        supersedes_rule_id=rule_dict.get("supersedes_rule_id"),
        display_text=rule_dict.get("display_text", ""),
        notes=rule_dict.get("notes"),
    )


def _parse_scheme(scheme_dict: dict[str, Any]) -> Scheme:
    """Parse a scheme metadata dict from JSON into a Scheme Pydantic object."""
    return Scheme(
        scheme_id=scheme_dict["scheme_id"],
        scheme_name=scheme_dict["scheme_name"],
        short_name=scheme_dict.get("short_name", scheme_dict["scheme_id"]),
        ministry=scheme_dict.get("ministry", ""),
        state_scope=scheme_dict.get("state_scope", "central"),
        status=SchemeStatus(scheme_dict.get("status", "active")),
        version=scheme_dict.get("version", "1.0.0"),
        last_verified=scheme_dict.get("last_verified", "2024-01-01"),
        source_urls=scheme_dict.get("source_urls", []),
        tags=scheme_dict.get("tags", []),
        created_at=scheme_dict.get("created_at", "2024-01-01"),
        updated_at=scheme_dict.get("updated_at", "2024-01-01"),
    )


def _apply_state_overrides(
    all_rules: list[Rule],
    user_state: Optional[str],
) -> tuple[list[Rule], list[str]]:
    """Apply state-specific rule overrides to the central rule set.

    For each state rule (state_scope == user_state) that has a supersedes_rule_id:
      1. Validate the superseded central rule exists
      2. Remove the central rule
      3. Add the state rule in its place
      4. Record the override

    Raises:
        RuleBaseError: If a supersedes_rule_id references a non-existent rule.

    Returns:
        (filtered_rules, list_of_applied_override_ids)
    """
    if not user_state:
        # Return only central rules when no state specified
        return [r for r in all_rules if r.state_scope == "central"], []

    central_rule_ids = {
        r.rule_id for r in all_rules if r.state_scope == "central"
    }
    state_rules = [r for r in all_rules if r.state_scope == user_state]
    overrides_applied: list[str] = []

    # Validate supersession chains
    for sr in state_rules:
        if sr.supersedes_rule_id and sr.supersedes_rule_id not in central_rule_ids:
            raise RuleBaseError(
                message=(
                    f"Broken supersession chain: rule '{sr.rule_id}' supersedes "
                    f"'{sr.supersedes_rule_id}' which does not exist in central rules"
                ),
                affected_schemes=[sr.scheme_id],
            )

    # Build superseded set
    superseded_ids = {sr.supersedes_rule_id for sr in state_rules if sr.supersedes_rule_id}

    # Build result: central rules not superseded + all state rules for user_state
    result: list[Rule] = []
    for r in all_rules:
        if r.state_scope == "central" and r.rule_id not in superseded_ids:
            result.append(r)
        elif r.state_scope == user_state:
            result.append(r)
            if r.supersedes_rule_id:
                overrides_applied.append(r.rule_id)

    return result, overrides_applied


async def load_rule_base(
    rule_base_path: Path,
    user_state: Optional[str] = None,
    review_queue_path: Optional[Path] = None,
) -> dict[str, "SchemeRuleSet"]:
    """Load DMN Decision Tables from rule_base_path.

    Reads .json files (DMN-shaped JSON). For each scheme:
      1. Parse rules into Rule objects
      2. Filter out DISPUTED rules
      3. Filter out review_queue rules
      4. Apply state overrides
      5. Skip inactive/discontinued schemes
      6. Log every exclusion

    Args:
        rule_base_path: Directory containing scheme JSON files.
        user_state: Optional state code for state-specific override resolution.
        review_queue_path: Optional path to review_queue.json.

    Returns:
        dict[str, SchemeRuleSet] keyed by scheme_id

    Raises:
        RuleBaseError: If directory is empty, no active schemes found,
                       or broken supersession chain detected.
    """
    if not rule_base_path.is_dir():
        raise RuleBaseError(
            message=f"Rule base path does not exist or is not a directory: {rule_base_path}",
            affected_schemes=[],
        )

    # Load review queue if specified
    review_queue: set[str] = set()
    if review_queue_path and review_queue_path.exists():
        try:
            review_queue = set(json.loads(review_queue_path.read_text()))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not load review queue: %s", e)
    else:
        # Check for review_queue.json in the rule_base_path directory
        default_rq = rule_base_path / "review_queue.json"
        if default_rq.exists():
            try:
                review_queue = set(json.loads(default_rq.read_text()))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load review queue from %s: %s", default_rq, e)

    json_files = sorted(
        f for f in rule_base_path.glob("*.json")
        if not f.name.startswith(".")
        and f.name != "review_queue.json"
        and f.name != "relationships.json"
        and f.name != "ambiguity_map.json"
        and f.name != "BATCH_INDEX.json"
    )

    if not json_files:
        raise RuleBaseError(
            message=f"No scheme JSON files found in {rule_base_path}",
            affected_schemes=[],
        )

    results: dict[str, SchemeRuleSet] = {}

    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            raise RuleBaseError(
                message=f"Failed to parse {json_file.name}: {e}",
                affected_schemes=[json_file.stem],
            ) from e

        # Normalise both single-scheme dicts and batch-format lists into a
        # common list of raw scheme dicts before processing.
        if isinstance(data, list):
            # Batch format: each item is a flat scheme dict with top-level keys
            raw_items: list[dict[str, Any]] = data
        elif isinstance(data, dict) and "scheme" in data:
            # Legacy single-scheme format: scheme metadata is nested under "scheme"
            raw_items = [{**data["scheme"], "rules": data.get("rules", [])}]
        else:
            # Flat single-scheme dict (scheme_id at top level, no wrapping key)
            raw_items = [data]

        for raw in raw_items:
            try:
                scheme = _parse_scheme(raw)
            except (KeyError, Exception) as e:
                logger.warning(
                    "Could not parse scheme in %s: %s — skipping",
                    json_file.name,
                    e,
                )
                continue

            # Skip inactive schemes
            if scheme.status not in (SchemeStatus.ACTIVE,):
                logger.info("Skipping inactive scheme: %s (status=%s)", scheme.scheme_id, scheme.status)
                continue

            # Parse all rules — batch files use PascalCase keys, single-scheme
            # files use snake_case; detect and normalise accordingly.
            all_rules: list[Rule] = []
            is_batch_format = raw.get("rules") and raw["rules"] and "Rule_ID" in raw["rules"][0]
            for rule_dict in raw.get("rules", []):
                try:
                    if is_batch_format:
                        rule_dict = _normalize_batch_rule(rule_dict)
                    rule = _parse_rule(rule_dict)
                    if rule is None:
                        # Silently skipped (e.g. NOT_BETWEEN, degenerate BETWEEN)
                        continue
                    all_rules.append(rule)
                except Exception as e:
                    logger.warning(
                        "Could not parse rule %s in %s: %s",
                        rule_dict.get("rule_id", rule_dict.get("Rule_ID", "?")),
                        json_file.name,
                        e,
                    )

            excluded_count = 0

            # Filter DISPUTED rules
            active_rules: list[Rule] = []
            for r in all_rules:
                if r.audit_status == AuditStatus.DISPUTED:
                    logger.info("Excluding DISPUTED rule: %s", r.rule_id)
                    excluded_count += 1
                else:
                    active_rules.append(r)

            # Filter review queue rules
            non_queue_rules: list[Rule] = []
            for r in active_rules:
                if r.rule_id in review_queue:
                    logger.info("Excluding review-queue rule: %s", r.rule_id)
                    excluded_count += 1
                else:
                    non_queue_rules.append(r)

            # Apply state overrides
            try:
                final_rules, overrides_applied = _apply_state_overrides(
                    non_queue_rules, user_state
                )
            except RuleBaseError:
                raise

            results[scheme.scheme_id] = SchemeRuleSet(
                scheme=scheme,
                active_rules=final_rules,
                excluded_rules_count=excluded_count,
                state_overrides_applied=overrides_applied,
            )

    if not results:
        raise RuleBaseError(
            message=f"No active schemes found in {rule_base_path}",
            affected_schemes=[],
        )

    return results


async def load_relationship_matrix(path: Path) -> list[SchemeRelationship]:
    """Load inter-scheme relationship matrix from a JSON file.

    Args:
        path: Path to relationships.json

    Returns:
        List of SchemeRelationship objects.

    Raises:
        RuleBaseError: On missing file or malformed JSON.
    """
    if not path.exists():
        raise RuleBaseError(
            message=f"Relationship matrix file not found: {path}",
            affected_schemes=[],
        )

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise RuleBaseError(
            message=f"Failed to parse relationship matrix {path}: {e}",
            affected_schemes=[],
        ) from e

    relationships: list[SchemeRelationship] = []
    for item in (data if isinstance(data, list) else data.get("relationships", [])):
        try:
            relationships.append(SchemeRelationship(**item))
        except Exception as e:
            logger.warning("Could not parse relationship: %s — %s", item, e)

    return relationships


async def load_ambiguity_map(path: Path) -> list[AmbiguityFlag]:
    """Load ambiguity flags from a JSON file.

    Args:
        path: Path to ambiguity_map.json

    Returns:
        List of AmbiguityFlag objects.

    Raises:
        RuleBaseError: On missing file or malformed JSON.
    """
    if not path.exists():
        raise RuleBaseError(
            message=f"Ambiguity map file not found: {path}",
            affected_schemes=[],
        )

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise RuleBaseError(
            message=f"Failed to parse ambiguity map {path}: {e}",
            affected_schemes=[],
        ) from e

    flags: list[AmbiguityFlag] = []
    for item in (data if isinstance(data, list) else data.get("flags", [])):
        try:
            flags.append(AmbiguityFlag(**item))
        except Exception as e:
            logger.warning("Could not parse ambiguity flag: %s — %s", item, e)

    return flags
