"""Output assembly and formatting for the CBC matching engine.

Assembles MatchingResult from SchemeDetermination objects and formats
results as JSON, CLI text, and Markdown.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from src.config import ENGINE_VERSION

logger = logging.getLogger(__name__)

# Status → bucket attribute name
_STATUS_BUCKET_MAP: dict[str, str] = {
    "ELIGIBLE": "eligible_schemes",
    "ELIGIBLE_WITH_CAVEATS": "eligible_schemes",
    "NEAR_MISS": "near_miss_schemes",
    "INELIGIBLE": "ineligible_schemes",
    "DISQUALIFIED": "ineligible_schemes",
    "REQUIRES_PREREQUISITE": "requires_prerequisite_schemes",
    "PARTIAL": "partial_schemes",
    "INSUFFICIENT_DATA": "insufficient_data_schemes",
}

# Summary text templates keyed by status
_SUMMARY_TEMPLATES: dict[str, str] = {
    "ELIGIBLE": (
        "{scheme_name} — You appear to be eligible. "
        "{rules_passed} eligibility rule(s) passed. Apply now to claim your benefit."
    ),
    "ELIGIBLE_WITH_CAVEATS": (
        "{scheme_name} — You appear eligible, but with caveats. "
        "Some rule interpretations are ambiguous; review guidance before applying."
    ),
    "NEAR_MISS": (
        "{scheme_name} — Near miss. You passed most criteria but did not meet "
        "{rules_failed} rule(s). Addressing these gaps may make you eligible."
    ),
    "INELIGIBLE": (
        "{scheme_name} — Not eligible at this time. "
        "{rules_failed} rule(s) could not be satisfied based on your profile."
    ),
    "DISQUALIFIED": (
        "{scheme_name} — You are disqualified from this scheme. "
        "A disqualifying condition was found in your profile."
    ),
    "REQUIRES_PREREQUISITE": (
        "{scheme_name} — Prerequisite not met. "
        "You need to enroll in a prerequisite scheme before applying."
    ),
    "PARTIAL": (
        "{scheme_name} — Partial determination. "
        "Ambiguity in some rules prevents a clear eligibility decision."
    ),
    "INSUFFICIENT_DATA": (
        "{scheme_name} — Insufficient data. "
        "Your profile is incomplete. Provide more information to get a complete evaluation."
    ),
}


@dataclass
class DocumentChecklistItem:
    """A single document required for a scheme."""

    document_field: str
    document_name: str
    required_by_schemes: list[str]
    is_mandatory: bool = True


@dataclass
class DocumentChecklist:
    """De-duplicated list of documents required across all eligible/near-miss schemes."""

    items: list[DocumentChecklistItem]
    total_documents: int


@dataclass
class SchemeResult:
    """Result for a single scheme evaluation, ready for output."""

    scheme_id: str
    scheme_name: str
    status: str
    ministry: str
    confidence: Any  # ConfidenceBreakdown
    rules_passed: int
    rules_failed: int
    rules_undetermined: int
    gap_analysis: Optional[Any]
    state_overrides_applied: list[str]
    excluded_rules_count: int
    discretion_warnings: list[str]
    summary_text: str
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serialisable dictionary."""
        return {
            "scheme_id": self.scheme_id,
            "scheme_name": self.scheme_name,
            "status": self.status,
            "ministry": self.ministry,
            "confidence": {
                "composite": getattr(self.confidence, "composite", 0),
                "composite_label": getattr(self.confidence, "composite_label", ""),
                "rule_match_score": getattr(self.confidence, "rule_match_score", 0),
                "data_confidence": getattr(self.confidence, "data_confidence", 0),
                "profile_completeness": getattr(self.confidence, "profile_completeness", 0),
                "bottleneck": getattr(self.confidence, "bottleneck", ""),
            },
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "rules_undetermined": self.rules_undetermined,
            "state_overrides_applied": self.state_overrides_applied,
            "excluded_rules_count": self.excluded_rules_count,
            "discretion_warnings": self.discretion_warnings,
            "summary_text": self.summary_text,
        }


@dataclass
class ResultSummary:
    """Aggregate statistics for a MatchingResult."""

    total_schemes_evaluated: int
    eligible_count: int
    near_miss_count: int
    ineligible_count: int
    requires_prerequisite_count: int
    partial_count: int
    insufficient_data_count: int
    top_recommendation: Optional[str]  # scheme_id of highest-confidence ELIGIBLE scheme
    overall_data_quality: str          # HIGH / MEDIUM / LOW


@dataclass
class MatchingResult:
    """The complete output of the CBC matching engine for one profile."""

    profile_id: str
    evaluation_timestamp: str
    engine_version: str
    state_applied: Optional[str]

    eligible_schemes: list[SchemeResult]
    near_miss_schemes: list[SchemeResult]
    ineligible_schemes: list[SchemeResult]
    requires_prerequisite_schemes: list[SchemeResult]
    partial_schemes: list[SchemeResult]
    insufficient_data_schemes: list[SchemeResult]

    application_sequence: Any
    document_checklist: DocumentChecklist
    summary: ResultSummary
    profile_warnings: list[str]

    # -----------------------------------------------------------------------
    # Output methods
    # -----------------------------------------------------------------------

    def _to_serializable_dict(self) -> dict[str, Any]:
        """Build a JSON-serialisable dictionary of the full result."""
        def _scheme_list(schemes: list[SchemeResult]) -> list[dict]:
            return [s.to_dict() for s in schemes]

        return {
            "profile_id": self.profile_id,
            "evaluation_timestamp": self.evaluation_timestamp,
            "engine_version": self.engine_version,
            "state_applied": self.state_applied,
            "eligible_schemes": _scheme_list(self.eligible_schemes),
            "near_miss_schemes": _scheme_list(self.near_miss_schemes),
            "ineligible_schemes": _scheme_list(self.ineligible_schemes),
            "requires_prerequisite_schemes": _scheme_list(self.requires_prerequisite_schemes),
            "partial_schemes": _scheme_list(self.partial_schemes),
            "insufficient_data_schemes": _scheme_list(self.insufficient_data_schemes),
            "document_checklist": {
                "total_documents": self.document_checklist.total_documents,
                "items": [
                    {
                        "document_field": i.document_field,
                        "document_name": i.document_name,
                        "required_by_schemes": i.required_by_schemes,
                        "is_mandatory": i.is_mandatory,
                    }
                    for i in self.document_checklist.items
                ],
            },
            "summary": {
                "total_schemes_evaluated": self.summary.total_schemes_evaluated,
                "eligible_count": self.summary.eligible_count,
                "near_miss_count": self.summary.near_miss_count,
                "ineligible_count": self.summary.ineligible_count,
                "top_recommendation": self.summary.top_recommendation,
            },
            "profile_warnings": self.profile_warnings,
        }

    def to_json(self) -> str:
        """Serialise to a JSON string."""
        try:
            return json.dumps(self._to_serializable_dict(), indent=2, ensure_ascii=False)
        except Exception as e:
            logger.exception("Error serialising MatchingResult to JSON: %s", e)
            return json.dumps({"error": str(e)})

    def to_cli_text(self) -> str:
        """Serialise to plain text suitable for CLI output."""
        try:
            lines: list[str] = [
                f"CBC Eligibility Report",
                f"======================",
                f"Profile ID:  {self.profile_id[:16]}...",
                f"State:       {self.state_applied or 'N/A'}",
                f"Timestamp:   {self.evaluation_timestamp}",
                f"Engine:      {self.engine_version}",
                "",
                f"ELIGIBLE ({len(self.eligible_schemes)}):",
            ]

            for s in self.eligible_schemes:
                lines.append(f"  ✓ {s.scheme_name} ({s.scheme_id}) — {s.summary_text}")

            if self.near_miss_schemes:
                lines.append(f"\nNEAR MISS ({len(self.near_miss_schemes)}):")
                for s in self.near_miss_schemes:
                    lines.append(f"  ~ {s.scheme_name} ({s.scheme_id}) — {s.summary_text}")

            if self.ineligible_schemes:
                lines.append(f"\nINELIGIBLE ({len(self.ineligible_schemes)}):")
                for s in self.ineligible_schemes:
                    lines.append(f"  ✗ {s.scheme_name} ({s.scheme_id})")

            if self.profile_warnings:
                lines.append("\nWARNINGS:")
                for w in self.profile_warnings:
                    lines.append(f"  ! {w}")

            return "\n".join(lines)
        except Exception as e:
            logger.exception("Error generating CLI text: %s", e)
            return f"CBC Eligibility Report\n[Error generating output: {e}]"

    def to_markdown(self) -> str:
        """Serialise to Markdown formatted report."""
        try:
            lines: list[str] = [
                "# CBC Eligibility Report",
                "",
                f"**Profile ID:** `{self.profile_id[:16]}...`  ",
                f"**State:** {self.state_applied or 'N/A'}  ",
                f"**Timestamp:** {self.evaluation_timestamp}  ",
                f"**Engine:** {self.engine_version}",
                "",
            ]

            if self.eligible_schemes:
                lines.append(f"## Eligible Schemes ({len(self.eligible_schemes)})")
                lines.append("")
                for s in self.eligible_schemes:
                    lines.append(f"### {s.scheme_name}")
                    lines.append(f"- **Status:** ELIGIBLE")
                    lines.append(f"- **Ministry:** {s.ministry}")
                    lines.append(f"- **Summary:** {s.summary_text}")
                    lines.append("")

            if self.near_miss_schemes:
                lines.append(f"## Near Miss Schemes ({len(self.near_miss_schemes)})")
                lines.append("")
                for s in self.near_miss_schemes:
                    lines.append(f"### {s.scheme_name}")
                    lines.append(f"- **Status:** NEAR_MISS")
                    lines.append(f"- **Summary:** {s.summary_text}")
                    lines.append("")

            if self.ineligible_schemes:
                lines.append(f"## Ineligible Schemes ({len(self.ineligible_schemes)})")
                lines.append("")
                for s in self.ineligible_schemes:
                    lines.append(f"- {s.scheme_name}: {s.summary_text}")
                lines.append("")

            if self.profile_warnings:
                lines.append("## Profile Warnings")
                lines.append("")
                for w in self.profile_warnings:
                    lines.append(f"- {w}")
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.exception("Error generating Markdown: %s", e)
            return f"# CBC Eligibility Report\n\n[Error: {e}]"


def generate_summary_text(scheme_result: Any) -> str:
    """Generate a natural-language summary for a SchemeResult.

    Args:
        scheme_result: SchemeResult or mock with .status and .scheme_name attributes.

    Returns:
        Non-empty string for any of the 8 supported statuses. Never raises.
    """
    try:
        status = getattr(scheme_result, "status", "ELIGIBLE")
        scheme_name = getattr(scheme_result, "scheme_name", "this scheme")
        rules_passed = getattr(scheme_result, "rules_passed", 0) or 0
        rules_failed = getattr(scheme_result, "rules_failed", 0) or 0

        template = _SUMMARY_TEMPLATES.get(status, "{scheme_name} — Status: {status}.")
        return template.format(
            scheme_name=scheme_name,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            status=status,
        )
    except Exception as e:
        logger.exception("Error generating summary text: %s", e)
        return f"{getattr(scheme_result, 'scheme_name', 'Scheme')}: status evaluation complete."


def _compute_profile_id(profile: Any) -> str:
    """Compute a deterministic SHA-256 hash of the profile.

    Uses model_dump() when available, else repr(). Never exposes raw PII.

    Args:
        profile: UserProfile or mock with model_dump().

    Returns:
        64-character hex SHA-256 digest.
    """
    try:
        if hasattr(profile, "model_dump"):
            raw = json.dumps(profile.model_dump(), sort_keys=True, default=str)
        else:
            raw = repr(profile)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(b"unknown-profile").hexdigest()


def _make_scheme_result(determination: Any) -> SchemeResult:
    """Build a SchemeResult from a SchemeDetermination (or mock)."""
    rule_evals = getattr(determination, "rule_evaluations", []) or []
    outcomes = [getattr(e, "outcome", "") for e in rule_evals]
    rules_passed = sum(1 for o in outcomes if o in ("PASS", "UNVERIFIED_PASS"))
    rules_failed = sum(1 for o in outcomes if o == "FAIL")
    rules_undetermined = sum(1 for o in outcomes if o == "UNDETERMINED")

    # Collect caveats from ambiguity notes on passing/caveated rules
    caveats: list[str] = []
    for e in rule_evals:
        notes = getattr(e, "ambiguity_notes", []) or []
        caveats.extend(notes)
    # Also include discretion warnings as caveats
    caveats.extend(getattr(determination, "discretion_warnings", []) or [])

    scheme = getattr(determination, "scheme", None)
    ministry = getattr(scheme, "ministry", "") or ""

    scheme_result = SchemeResult(
        scheme_id=getattr(determination, "scheme_id", ""),
        scheme_name=getattr(determination, "scheme_name", ""),
        status=getattr(determination, "status", "UNKNOWN"),
        ministry=ministry,
        confidence=getattr(determination, "confidence", None),
        rules_passed=rules_passed,
        rules_failed=rules_failed,
        rules_undetermined=rules_undetermined,
        gap_analysis=getattr(determination, "gap_analysis", None),
        state_overrides_applied=list(getattr(determination, "state_overrides_applied", []) or []),
        excluded_rules_count=int(getattr(determination, "excluded_rules_count", 0) or 0),
        discretion_warnings=list(getattr(determination, "discretion_warnings", []) or []),
        summary_text="",  # Filled in below
        caveats=caveats,
    )
    scheme_result.summary_text = generate_summary_text(scheme_result)
    return scheme_result


def _build_document_checklist(scheme_results: list[SchemeResult]) -> DocumentChecklist:
    """Build a de-duplicated document checklist from all scheme results.

    Returns a DocumentChecklist with items de-duplicated by document_field.
    """
    # Standard documents required by all CBC schemes
    standard_docs: dict[str, DocumentChecklistItem] = {}

    for sr in scheme_results:
        if sr.status not in ("ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS"):
            continue
        # Add standard required documents
        for doc_field, doc_name in _STANDARD_DOCS.items():
            if doc_field not in standard_docs:
                standard_docs[doc_field] = DocumentChecklistItem(
                    document_field=doc_field,
                    document_name=doc_name,
                    required_by_schemes=[sr.scheme_id],
                    is_mandatory=True,
                )
            else:
                existing = standard_docs[doc_field]
                if sr.scheme_id not in existing.required_by_schemes:
                    existing.required_by_schemes.append(sr.scheme_id)

    items = list(standard_docs.values())
    return DocumentChecklist(items=items, total_documents=len(items))


# Standard documents typically required across CBC schemes
_STANDARD_DOCS: dict[str, str] = {
    "documents.aadhaar": "Aadhaar Card",
    "documents.bank_account": "Bank Account (Jan Dhan or nationalised bank)",
}


def _build_summary(
    eligible: list[SchemeResult],
    near_miss: list[SchemeResult],
    ineligible: list[SchemeResult],
    requires_prereq: list[SchemeResult],
    partial: list[SchemeResult],
    insufficient_data: list[SchemeResult],
) -> ResultSummary:
    """Build the aggregate ResultSummary."""
    total = len(eligible) + len(near_miss) + len(ineligible) + len(requires_prereq) + len(partial) + len(insufficient_data)

    # Top recommendation: highest-confidence ELIGIBLE scheme
    top_rec: Optional[str] = None
    best_conf = -1.0
    for sr in eligible:
        conf = getattr(sr.confidence, "composite", 0) or 0
        if conf > best_conf:
            best_conf = conf
            top_rec = sr.scheme_id

    # Overall data quality heuristic
    if eligible and best_conf >= 0.80:
        quality = "HIGH"
    elif eligible or near_miss:
        quality = "MEDIUM"
    else:
        quality = "LOW"

    return ResultSummary(
        total_schemes_evaluated=total,
        eligible_count=len(eligible),
        near_miss_count=len(near_miss),
        ineligible_count=len(ineligible),
        requires_prerequisite_count=len(requires_prereq),
        partial_count=len(partial),
        insufficient_data_count=len(insufficient_data),
        top_recommendation=top_rec,
        overall_data_quality=quality,
    )


def assemble_matching_result(
    profile: Any,
    determinations: list[Any],
    application_sequence: Any,
    profile_warnings: list[str],
) -> MatchingResult:
    """Assemble a MatchingResult from evaluated determinations.

    Args:
        profile: UserProfile (or mock) used in evaluation.
        determinations: List of SchemeDetermination objects.
        application_sequence: ApplicationSequence from sequencing module.
        profile_warnings: List of warning strings from profile validation.

    Returns:
        A fully assembled MatchingResult.
    """
    profile_id = _compute_profile_id(profile)
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    state_applied = getattr(profile, "location_state", None)

    # Convert determinations to SchemeResult objects
    scheme_results: list[SchemeResult] = []
    for det in determinations:
        try:
            scheme_results.append(_make_scheme_result(det))
        except Exception as e:
            logger.warning("Error making SchemeResult for %s: %s", det, e)

    # Bucket by status
    eligible: list[SchemeResult] = []
    near_miss: list[SchemeResult] = []
    ineligible: list[SchemeResult] = []
    requires_prereq: list[SchemeResult] = []
    partial: list[SchemeResult] = []
    insufficient_data: list[SchemeResult] = []

    for sr in scheme_results:
        status = sr.status
        if status in ("ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"):
            eligible.append(sr)
        elif status == "NEAR_MISS":
            near_miss.append(sr)
        elif status in ("INELIGIBLE", "DISQUALIFIED"):
            ineligible.append(sr)
        elif status == "REQUIRES_PREREQUISITE":
            requires_prereq.append(sr)
        elif status == "PARTIAL":
            partial.append(sr)
        elif status == "INSUFFICIENT_DATA":
            insufficient_data.append(sr)
        else:
            # Unknown status → put in ineligible
            ineligible.append(sr)

    document_checklist = _build_document_checklist(eligible + near_miss)
    summary = _build_summary(eligible, near_miss, ineligible, requires_prereq, partial, insufficient_data)

    return MatchingResult(
        profile_id=profile_id,
        evaluation_timestamp=timestamp,
        engine_version=ENGINE_VERSION,
        state_applied=state_applied,
        eligible_schemes=eligible,
        near_miss_schemes=near_miss,
        ineligible_schemes=ineligible,
        requires_prerequisite_schemes=requires_prereq,
        partial_schemes=partial,
        insufficient_data_schemes=insufficient_data,
        application_sequence=application_sequence,
        document_checklist=document_checklist,
        summary=summary,
        profile_warnings=list(profile_warnings or []),
    )
