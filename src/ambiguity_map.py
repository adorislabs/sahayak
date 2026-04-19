"""Ambiguity detection, taxonomy, severity assignment, and export for CBC Part 1.

Implements the 30-type ambiguity taxonomy from Spec 05. Every ambiguity detected
during parsing is tagged with a type code (1–30), a severity, and a resolution status.

Why explicit ambiguity tracking: Policy ambiguities (undefined terms, discretionary
clauses, contradictory rules) cause eligibility errors that harm vulnerable beneficiaries.
Explicit tracking forces policy teams to resolve or accept each ambiguity.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from src.schema import AmbiguityFlag, AmbiguitySeverity, Rule

# Lazy import — only loaded when LLM-assisted detection is requested
_gemini_enhancer: "GeminiEnhancer | None" = None  # type: ignore[name-defined]


def _get_gemini_enhancer() -> "GeminiEnhancer | None":  # type: ignore[name-defined]
    """Return a shared GeminiEnhancer instance, or None if unavailable."""
    global _gemini_enhancer
    if _gemini_enhancer is not None:
        return _gemini_enhancer
    try:
        from src.gemini_enhancer import GeminiEnhancer
        _gemini_enhancer = GeminiEnhancer()
        return _gemini_enhancer
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 30-type ambiguity taxonomy
# ---------------------------------------------------------------------------

AMBIGUITY_TAXONOMY: dict[int, str] = {
    1: "Semantic Vagueness",
    2: "Undefined Term",
    3: "Conflicting Criteria",
    4: "Discretionary Clause",
    5: "Temporal Ambiguity",
    6: "Mutual Exclusion Conflict",
    7: "Portability Gap",
    8: "Eligibility Threshold Overlap",
    9: "Prerequisite Chaining / Circular Dependency",
    10: "Financial Threshold Flux",
    11: "Categorical Boundary Ambiguity",
    12: "Documentation Requirement Ambiguity",
    13: "Benefit Duplication Risk",
    14: "Administrative Boundary Conflict",
    15: "Implementation Gap",
    16: "Targeting Inconsistency",
    17: "Appeal Mechanism Vagueness",
    18: "Grievance Redressal Specificity",
    19: "Linguistic Translation Delta",
    20: "Infrastructure Precondition",
    21: "Life-Event Transition Ambiguity",
    22: "Household Definition Inconsistency",
    23: "Residency Requirement Vagueness",
    24: "Income Computation Method Ambiguity",
    25: "Caste Certificate Jurisdiction Conflict",
    26: "Gender Eligibility Gap",
    27: "Age Calculation Method Ambiguity",
    28: "Land Record Jurisdiction Conflict",
    29: "Disability Certification Ambiguity",
    30: "Aadhaar Linkage Requirement Gap",
}


# ---------------------------------------------------------------------------
# Pattern matchers: (type_code, pattern) — order matters; first match wins
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    # Type 9: Prerequisite chaining / circular dependency (must check before mutual exclusion)
    (9, re.compile(r'\bcircular|prerequisite.*prerequisite|depends on.*depends on\b', re.I)),
    # Type 6: Mutual exclusion (explicit disqualification from another scheme)
    (6, re.compile(r'\bnot eligible.*member|must not.*be.*member|not a member|enrolled in.*not eligible\b', re.I)),
    # Type 19: Linguistic translation delta (English/Hindi divergence)
    (19, re.compile(r'\bhindu|hindi\b.*\bsays|english\b.*\bhindi|tamil.*version|language.*version|version.*says\b', re.I)),
    # Type 10: Financial threshold flux (poverty line without numeric)
    (10, re.compile(r'\bbelow (?:the )?poverty line\b(?!.*[\d₹])', re.I)),
    # Type 21: Life-event transition (widow, remarriage, death event)
    (21, re.compile(r'\bwid(?:ow|ower)|remarri|upon death|after (?:spouse|husband|wife) dies?\b', re.I)),
    # Type 7: Portability gap (ration card, state-bound without portability clause)
    (7, re.compile(r'\bration card|inter.?state portability|within the state of registration|state[\s-]bound|applicable.*only.*within\b', re.I)),
    # Type 4: Discretionary clause
    (4, re.compile(r'\bat the discretion of|subject to.*approval|as determined by|may be selected\b', re.I)),
    # Type 2: Undefined Term / Evidence Gap (document gaps, cannot prove ownership)
    (2, re.compile(r'\bcannot prove|lease.*land|land.*lease|cannot.*document|documentation.*gap|cultivation|ownership.*document|proof of.*ownership\b', re.I)),
    # Type 1: Semantic vagueness — general undefined terms (BEFORE Type 23 to match "resident" first)
    (1, re.compile(r'\bresident|weaker section|rural poor|needy|deserving|suitable|appropriate\b', re.I)),
    # Type 23: Residency vagueness ("resident" undefined — more specific pattern checked after Type 1)
    (23, re.compile(r'\bresident of the state|permanent resident|domicile\b(?!.*\d)', re.I)),
    # Type 27: Age calculation ambiguity
    (27, re.compile(r'\bas on date of|age as on|completed.*years|attained.*age\b', re.I)),
    # Type 30: Aadhaar linkage gap
    (30, re.compile(r'\baadhaar\b.*\bnot mandatory|without aadhaar\b', re.I)),
    # Type 20: Infrastructure precondition (bank account, DBT, Aadhaar-linked)
    (20, re.compile(r'\bbank account|direct benefit transfer|dbt\b|aadhaar.linked bank|subject to.*availability|if.*infrastructure|depending on.*facility\b', re.I)),
    # Type 3: Conflicting criteria (simultaneous contradictory requirements)
    (3, re.compile(r'\bcontradicts|simultaneously requires|mutually exclusive criteria|conflicting requirement\b', re.I)),
    # Type 5: Temporal ambiguity (time window without reference point)
    (5, re.compile(r'\bwithin \d+ (?:days?|months?|years?) of|before the due date|time.?limit|application window|validity period\b', re.I)),
    # Type 8: Eligibility threshold overlap (income bands overlap)
    (8, re.compile(r'\bincome between|income from.*to|threshold overlap|falling under.*category|borderline income\b', re.I)),
    # Type 11: Categorical boundary ambiguity (caste/category boundary)
    (11, re.compile(r'\bboundary.*caste|caste.*boundary|other backward class|OBC boundary|category overlap|SC.ST.OBC.*ambiguous\b', re.I)),
    # Type 12: Documentation requirement ambiguity (varies by state/district)
    (12, re.compile(r'\bdocument.*varies|varies by state|documents required.*different|certificate.*accepted.*only|list of acceptable documents\b', re.I)),
    # Type 13: Benefit duplication risk (overlapping benefits from multiple schemes)
    (13, re.compile(r'\bbenefit.*overlap|double.*benefit|simultaneous.*claim|already.*receiving.*benefit|same benefit.*another scheme\b', re.I)),
    # Type 14: Administrative boundary conflict (gram panchayat, block, district gaps)
    (14, re.compile(r'\bgram panchayat|block level|district boundary|administrative.*conflict|jurisdiction.*overlap|panchayat.*limit\b', re.I)),
    # Type 15: Implementation gap (policy exists but system not ready)
    (15, re.compile(r'\bimplementation pending|not yet operational|rollout incomplete|pilot.*phase|infrastructure not yet|yet to be notified\b', re.I)),
    # Type 16: Targeting inconsistency (household vs family definitions differ)
    (16, re.compile(r'\bhousehold.*definition|family.*composition|son.*government job|member.*income.*excluded|family income.*includes\b', re.I)),
    # Type 17: Appeal mechanism vagueness
    (17, re.compile(r'\bmay appeal|right to appeal|appeal.*within|appellate authority|no appeal mechanism|grievance.*appeal\b', re.I)),
    # Type 18: Grievance redressal specificity
    (18, re.compile(r'\bgrievance redressal|complaint.*mechanism|toll.?free|helpline|ombudsman|nodal officer.*grievance\b', re.I)),
    # Type 22: Household definition inconsistency (joint vs nuclear family)
    (22, re.compile(r'\bjoint family|nuclear family|household.*split|separate household|living separately|married daughter.*household\b', re.I)),
    # Type 24: Income computation method ambiguity
    (24, re.compile(r'\bfamily income|combined income|per capita income|individual income|income.*computation|income.*calculation method\b', re.I)),
    # Type 25: Caste certificate jurisdiction conflict
    (25, re.compile(r'\bcaste certificate.*state|OBC certificate.*central|SC certificate.*different|caste.*jurisdiction|backward class.*list\b', re.I)),
    # Type 26: Gender eligibility gap
    (26, re.compile(r'\bwomen only|only female|male applicants excluded|gender.*eligibility|unmarried woman|married woman\b', re.I)),
    # Type 28: Land record jurisdiction conflict
    (28, re.compile(r'\bland record|patta|khata|khatauni|jamabandi|land.*registry|revenue record\b', re.I)),
    # Type 29: Disability certification ambiguity
    (29, re.compile(r'\bdisability certificate|PwD|percentage.*disability|benchmark disability|disability.*threshold|differently abled\b', re.I)),
]


# ---------------------------------------------------------------------------
# DeterminationResult (returned by apply_partial_determination)
# ---------------------------------------------------------------------------


@dataclass
class DeterminationResult:
    """Result of partial determination — separates unambiguous from ambiguous rules.

    Why: CRITICAL ambiguities must never be silently suppressed. By separating
    determined and undetermined rules, the evaluation engine can return a partial
    answer rather than a misleading definitive one.
    """

    status: str  # "FULL" | "PARTIAL"
    determined_rules: List[str]  # rule_ids that can be evaluated normally
    undetermined_rules: List[str]  # rule_ids blocked by CRITICAL ambiguities
    human_review_signal: bool  # True if any CRITICAL ambiguity is present
    ambiguity_flags: List[AmbiguityFlag] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_ambiguity_type(
    text: str,
    rule: Optional[Rule] = None,
    use_llm: bool = False,
) -> List[AmbiguityFlag]:
    """Scan text (and optionally a rule object) for patterns matching the 30-type taxonomy.

    Why: Ambiguity detection must be exhaustive — any ambiguity missed here will
    silently propagate to eligibility decisions.

    Args:
        text: The eligibility clause or rule text to analyse.
        rule: Optional Rule object for richer context in flags.
        use_llm: When True, calls Gemini Flash 2.5 for the full 30-type detection if
                 regex finds nothing. Requires GEMINI_API_KEY in environment. If the
                 API is unavailable the function degrades gracefully to regex-only.

    Returns: List of AmbiguityFlag records; returns empty list if none found (never raises).
    """
    if not text:
        return []

    flags: list[AmbiguityFlag] = []
    seen_codes: set[int] = set()

    for type_code, pattern in _PATTERNS:
        if type_code in seen_codes:
            continue
        if pattern.search(text):
            severity = assign_severity(type_code, {"rule": rule, "text": text})
            flag_id = f"AMB-{uuid.uuid4().hex[:6].upper()}"
            flags.append(
                AmbiguityFlag(
                    ambiguity_id=flag_id,
                    scheme_id=rule.scheme_id if rule else "UNKNOWN",
                    rule_id=rule.rule_id if rule else None,
                    ambiguity_type_code=type_code,
                    ambiguity_type_name=AMBIGUITY_TAXONOMY[type_code],
                    description=_describe(type_code, text),
                    severity=severity,
                )
            )
            seen_codes.add(type_code)

    # LLM-assisted detection: call Gemini when regex found nothing (or always if use_llm=True)
    # and the caller explicitly opted in.  Results are cached on disk so repeated calls
    # for the same text cost zero tokens.
    if use_llm:
        enhancer = _get_gemini_enhancer()
        if enhancer is not None:
            try:
                [detection] = enhancer.detect_ambiguities_batch([text])
                llm_types: list[int] = detection.get("detected_types", [])
                descriptions: dict[str, str] = detection.get("descriptions", {})
                for type_code in llm_types:
                    if type_code in seen_codes:
                        continue
                    if type_code not in AMBIGUITY_TAXONOMY:
                        continue
                    severity = assign_severity(type_code, {"rule": rule, "text": text})
                    flag_id = f"AMB-{uuid.uuid4().hex[:6].upper()}"
                    desc = descriptions.get(str(type_code), _describe(type_code, text))
                    flags.append(
                        AmbiguityFlag(
                            ambiguity_id=flag_id,
                            scheme_id=rule.scheme_id if rule else "UNKNOWN",
                            rule_id=rule.rule_id if rule else None,
                            ambiguity_type_code=type_code,
                            ambiguity_type_name=AMBIGUITY_TAXONOMY[type_code],
                            description=desc,
                            severity=severity,
                        )
                    )
                    seen_codes.add(type_code)
            except Exception:
                pass  # Gemini failure is non-fatal — regex flags still returned

    return flags


def _describe(type_code: int, text: str) -> str:
    """Generate a concise description for a detected ambiguity."""
    name = AMBIGUITY_TAXONOMY.get(type_code, "Unknown")
    snippet = text[:200].replace("\n", " ")
    return f"{name} detected in: '{snippet}...'" if len(text) > 200 else f"{name} detected in: '{text}'"


def assign_severity(ambiguity_type_code: int, context: dict) -> AmbiguitySeverity:  # type: ignore[type-arg]
    """Determine severity (CRITICAL / HIGH / MEDIUM / LOW) for an ambiguity type.

    Why: Not all ambiguities are equally harmful. CRITICAL ambiguities (circular
    prerequisites, infrastructure preconditions) can completely block eligibility
    determination and require immediate human intervention.

    Args:
        ambiguity_type_code: Integer 1–30 from AMBIGUITY_TAXONOMY.
        context: Dict with optional keys: 'scheme_id', 'field_affected', 'rule'.
    """
    # CRITICAL: types that can completely block determination
    critical_types = {9, 3, 20}

    # HIGH: types that affect major eligibility fields
    high_types = {1, 6, 7, 10, 14, 16, 19, 23, 25, 28, 29}

    # MEDIUM: types that affect process but not core eligibility
    medium_types = {4, 5, 8, 11, 12, 13, 15, 17, 21, 24, 26, 27, 30}

    # LOW: informational / minor process ambiguity
    low_types = {2, 18, 22}

    # Context-sensitive upgrades
    field_affected = context.get("field_affected", "")
    scheme_id = context.get("scheme_id", "")

    if ambiguity_type_code in critical_types:
        return AmbiguitySeverity.CRITICAL

    if ambiguity_type_code in high_types:
        # Upgrade to CRITICAL if affecting income or land (core eligibility fields)
        if field_affected and any(
            kw in field_affected for kw in ("income", "land", "age", "caste")
        ):
            return AmbiguitySeverity.CRITICAL
        return AmbiguitySeverity.HIGH

    if ambiguity_type_code in medium_types:
        # Infrastructure preconditions for flagship schemes → HIGH
        if ambiguity_type_code == 20 and scheme_id in ("AYUSHMAN", "PMAY"):
            return AmbiguitySeverity.HIGH
        return AmbiguitySeverity.MEDIUM

    return AmbiguitySeverity.LOW


def export_ambiguity_map(flags: List[AmbiguityFlag], format: str) -> str:
    """Export the full ambiguity map as 'json', 'csv', or 'markdown'.

    Why: Different consumers need different formats — APIs need JSON, spreadsheets
    need CSV, and policy wikis need Markdown.

    Raises:
        ValueError: If format is not one of the three accepted values.
    """
    if format == "json":
        return json.dumps(
            [f.model_dump() for f in flags],
            indent=2,
            default=str,
        )

    if format == "csv":
        if not flags:
            return "ambiguity_id,scheme_id,rule_id,ambiguity_type_code,ambiguity_type_name,severity,resolution_status\n"
        buf = io.StringIO()
        fieldnames = [
            "ambiguity_id",
            "scheme_id",
            "rule_id",
            "ambiguity_type_code",
            "ambiguity_type_name",
            "description",
            "severity",
            "resolution_status",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for flag in flags:
            writer.writerow(flag.model_dump())
        return buf.getvalue()

    if format == "markdown":
        if not flags:
            return "| ambiguity_id | scheme_id | type_code | severity | status |\n|---|---|---|---|---|\n"
        columns = ["ambiguity_id", "scheme_id", "ambiguity_type_name", "severity", "resolution_status"]
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join("---" for _ in columns) + " |"
        rows = [
            "| " + " | ".join(str(getattr(f, col, "")) for col in columns) + " |"
            for f in flags
        ]
        return "\n".join([header, sep] + rows)

    raise ValueError(
        f"Unknown export format '{format}'. Must be one of: 'json', 'csv', 'markdown'"
    )


def apply_partial_determination(
    rules: List[Rule], flags: List[AmbiguityFlag]
) -> DeterminationResult:
    """For CRITICAL ambiguities: evaluate non-CRITICAL rules normally;
    mark CRITICAL-flagged rules as UNDETERMINED; emit human_review_signal=True.

    Never silently suppresses ambiguities.

    Why: Partial determination is safer than refusing to answer or giving a wrong
    definitive answer. Users get partial eligibility information plus a human
    review trigger.
    """
    # Find rule_ids blocked by CRITICAL ambiguities
    critical_rule_ids: set[str] = {
        f.rule_id
        for f in flags
        if f.severity == AmbiguitySeverity.CRITICAL and f.rule_id is not None
    }

    determined: list[str] = []
    undetermined: list[str] = []

    for rule in rules:
        if rule.rule_id in critical_rule_ids:
            undetermined.append(rule.rule_id)
        else:
            determined.append(rule.rule_id)

    has_critical = len(undetermined) > 0
    status = "PARTIAL" if has_critical else "FULL"

    return DeterminationResult(
        status=status,
        determined_rules=determined,
        undetermined_rules=undetermined,
        human_review_signal=has_critical,
        ambiguity_flags=flags,
    )
