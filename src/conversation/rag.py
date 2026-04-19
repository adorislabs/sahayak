"""Lightweight in-process RAG for CBC Part 5 — scheme context retrieval.

Loads the parsed scheme rule base at startup and retrieves the most
relevant schemes for a given user profile and message.  Used to:

  1. Generate scheme-targeted follow-up questions
     ("PM-KISAN requires land ownership — do you own land?")
  2. Enrich near-miss responses with specific gap explanations
  3. Populate turn_audit.scheme_context for the explainability panel
  4. Drive proactive What If suggestions

No external vector DB is needed — the rule base is small enough
(<200 schemes × ~20 rules each) for in-memory TF-IDF.

Usage::

    from src.conversation.rag import SchemeRetriever
    retriever = SchemeRetriever(Path("parsed_schemes"))
    contexts = retriever.retrieve("I'm a farmer from UP", profile, top_k=3)
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ProfileGap:
    """A field required by a scheme that is missing from the current profile."""
    field_path: str
    field_label: str          # human-readable
    affects_schemes: int      # how many retrieved schemes need this field
    question_en: str          # contextual question to ask
    question_hi: str
    fix_instruction: str = ""
    estimated_days: str = ""


@dataclass
class AmbiguityFlag:
    """A 30-type ambiguity record from the parsed scheme rule base."""
    amb_id: str
    type_code: int
    type_name: str
    severity: str             # CRITICAL / HIGH / MEDIUM / LOW
    description: str
    source_quote: str = ""
    impact_on_result: str = ""


@dataclass
class RuleTrace:
    """Per-rule evaluation trace for the explainability panel."""
    rule_id: str
    description: str
    passed: bool
    user_value: Any = None
    source_ref: str = ""
    source_url: str = ""
    caveat: str = ""


@dataclass
class SchemeContext:
    """Retrieved scheme context for one conversation turn."""
    scheme_id: str
    scheme_name: str
    relevance: str            # "high" | "medium" | "low"
    why_relevant: str         # one-line explanation
    required_fields: list[str] = field(default_factory=list)
    profile_gaps: list[str] = field(default_factory=list)  # missing required fields
    gap_details: list[ProfileGap] = field(default_factory=list)
    rule_traces: list[RuleTrace] = field(default_factory=list)
    ambiguity_flags: list[AmbiguityFlag] = field(default_factory=list)
    confidence_estimate: float = 0.0


# ---------------------------------------------------------------------------
# 30 ambiguity type names (from docs/part1-planning/spec/05-ambiguity-map.md)
# ---------------------------------------------------------------------------

AMBIGUITY_TYPE_NAMES: dict[int, str] = {
    1: "Semantic Vagueness",
    2: "Evidence Gap",
    3: "Jurisdictional Overlap",
    4: "Discretionary Clauses",
    5: "Temporal Flux",
    6: "Mutual Exclusion",
    7: "Portability Gap",
    8: "Implementation Liveness",
    9: "Prerequisite Chaining",
    10: "Financial Threshold Flux",
    11: "Calculation Methodology",
    12: "Quota Tie-breaking Logic",
    13: "Succession and Inheritance",
    14: "Graduation Grace Periods",
    15: "Offline Fallback Protocol",
    16: "Household Unit Duality",
    17: "Legacy Data Reconciliation",
    18: "Grievance Redressal Specificity",
    19: "Linguistic Translation Delta",
    20: "Infrastructure Preconditions",
    21: "Life-Event Transition Protocols",
    22: "Identity Attribute Mutation",
    23: "Profile Recertification Triggers",
    24: "Inter-Departmental Identity Sync",
    25: "Retroactive Eligibility Adjustment",
    26: "Benefit Succession Path",
    27: "Regulatory Silence (Vacuum)",
    28: "Age-Out Transition",
    29: "Documentary Substitution",
    30: "Benefit Fragmentation",
}


# ---------------------------------------------------------------------------
# Field label registry (for gap explanations)
# ---------------------------------------------------------------------------

_FIELD_META: dict[str, dict[str, str]] = {
    "applicant.age": {
        "label": "Age", "label_hi": "उम्र",
        "q_en": "How old are you?",
        "q_hi": "आपकी उम्र कितनी है?",
    },
    "location.state": {
        "label": "State", "label_hi": "राज्य",
        "q_en": "Which state do you live in?",
        "q_hi": "आप किस राज्य में रहते हैं?",
    },
    "household.income_annual": {
        "label": "Annual Income", "label_hi": "सालाना आमदनी",
        "q_en": "What is your approximate annual income?",
        "q_hi": "आपकी सालाना आमदनी लगभग कितनी है?",
    },
    "applicant.caste_category": {
        "label": "Caste Category", "label_hi": "जाति श्रेणी",
        "q_en": "Which community or category do you belong to (SC/ST/OBC/General/EWS)?",
        "q_hi": "आप किस समुदाय या श्रेणी से हैं (SC/ST/OBC/सामान्य/EWS)?",
    },
    "applicant.gender": {
        "label": "Gender", "label_hi": "लिंग",
        "q_en": "Could you tell me your gender?",
        "q_hi": "आप अपना लिंग बता सकते हैं?",
    },
    "applicant.land_ownership_status": {
        "label": "Land Ownership", "label_hi": "भूमि स्वामित्व",
        "q_en": "Do you own agricultural land?",
        "q_hi": "क्या आपके पास कृषि भूमि है?",
    },
    "household.land_acres": {
        "label": "Land Area", "label_hi": "भूमि क्षेत्र",
        "q_en": "How much agricultural land do you own (in acres or bigha)?",
        "q_hi": "आपके पास कितनी कृषि भूमि है (एकड़ या बीघा में)?",
    },
    "documents.aadhaar": {
        "label": "Aadhaar Card", "label_hi": "आधार कार्ड",
        "q_en": "Do you have an Aadhaar card?",
        "q_hi": "क्या आपके पास आधार कार्ड है?",
    },
    "documents.bank_account": {
        "label": "Bank Account", "label_hi": "बैंक खाता",
        "q_en": "Do you have a bank account?",
        "q_hi": "क्या आपके पास बैंक खाता है?",
    },
    "employment.type": {
        "label": "Occupation", "label_hi": "पेशा",
        "q_en": "What kind of work do you do?",
        "q_hi": "आप क्या काम करते हैं?",
    },
    "household.size": {
        "label": "Family Size", "label_hi": "परिवार का आकार",
        "q_en": "How many members are in your family?",
        "q_hi": "आपके परिवार में कितने सदस्य हैं?",
    },
    "applicant.disability_status": {
        "label": "Disability", "label_hi": "विकलांगता",
        "q_en": "Do you have a disability?",
        "q_hi": "क्या आप दिव्यांग/विकलांग हैं?",
    },
    "applicant.marital_status": {
        "label": "Marital Status", "label_hi": "वैवाहिक स्थिति",
        "q_en": "What is your marital status? (married, unmarried, widowed, divorced)",
        "q_hi": "आपकी वैवाहिक स्थिति क्या है? (विवाहित, अविवाहित, विधवा, तलाकशुदा)",
    },
    "household.bpl_status": {
        "label": "BPL Status", "label_hi": "BPL स्थिति",
        "q_en": "Are you below the poverty line (BPL)?",
        "q_hi": "क्या आप गरीबी रेखा (BPL) के नीचे हैं?",
    },
    "household.ration_card_type": {
        "label": "Ration Card", "label_hi": "राशन कार्ड",
        "q_en": "What type of ration card do you have? (APL, BPL, Antyodaya, or none)",
        "q_hi": "आपके पास कौन सा राशन कार्ड है? (APL, BPL, अंत्योदय, या कोई नहीं)",
    },
    "applicant.education_level": {
        "label": "Education Level", "label_hi": "शिक्षा स्तर",
        "q_en": "What is your highest level of education? (e.g. no schooling, primary, Class 10, Class 12, graduate)",
        "q_hi": "आपकी सबसे ऊँची शिक्षा क्या है? (जैसे: कोई नहीं, प्राइमरी, कक्षा 10, कक्षा 12, स्नातक)",
    },
    "household.residence_type": {
        "label": "Residence Type", "label_hi": "निवास प्रकार",
        "q_en": "Do you live in a rural (village) or urban (city/town) area?",
        "q_hi": "क्या आप ग्रामीण (गाँव) या शहरी (शहर/कस्बा) क्षेत्र में रहते हैं?",
    },
    "applicant.pregnancy_status": {
        "label": "Pregnancy Status", "label_hi": "गर्भावस्था की स्थिति",
        "q_en": "Are you currently pregnant or a new mother?",
        "q_hi": "क्या आप गर्भवती हैं या नई माँ हैं?",
    },
    "documents.caste_certificate": {
        "label": "Caste Certificate", "label_hi": "जाति प्रमाण पत्र",
        "q_en": "_document_",
        "q_hi": "_document_",
    },
    "documents.income_certificate": {
        "label": "Income Certificate", "label_hi": "आय प्रमाण पत्र",
        "q_en": "_document_",
        "q_hi": "_document_",
    },
    "documents.mgnrega_job_card": {
        "label": "MGNREGA Job Card", "label_hi": "मनरेगा जॉब कार्ड",
        "q_en": "_document_",
        "q_hi": "_document_",
    },
    "documents.domicile_certificate": {
        "label": "Domicile Certificate", "label_hi": "निवास प्रमाण पत्र",
        "q_en": "_document_",
        "q_hi": "_document_",
    },
}


# ---------------------------------------------------------------------------
# TF-IDF index
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"[a-zA-Z\u0900-\u097F]+", text.lower())


class TermIndex:
    """Lightweight in-process TF-IDF index over scheme documents."""

    def __init__(self) -> None:
        self._docs: list[tuple[str, str]] = []          # (scheme_id, raw_text)
        self._tf: list[Counter[str]] = []
        self._idf: dict[str, float] = {}
        self._built = False

    def add(self, scheme_id: str, text: str) -> None:
        self._docs.append((scheme_id, text))

    def build(self) -> None:
        n = len(self._docs)
        if n == 0:
            return
        df: Counter[str] = Counter()
        for _, text in self._docs:
            tokens = set(_tokenize(text))
            df.update(tokens)
        self._idf = {
            t: math.log((n + 1) / (cnt + 1)) + 1
            for t, cnt in df.items()
        }
        for _, text in self._docs:
            tokens = _tokenize(text)
            total = len(tokens) or 1
            self._tf.append(Counter({t: c / total for t, c in Counter(tokens).items()}))
        self._built = True

    def query(self, text: str, top_k: int = 3) -> list[tuple[str, float]]:
        """Return top-k (scheme_id, score) pairs."""
        if not self._built or not self._docs:
            return []
        q_tokens = _tokenize(text)
        scores: list[float] = []
        for tf in self._tf:
            score = sum(
                tf.get(t, 0) * self._idf.get(t, 0)
                for t in q_tokens
            )
            scores.append(score)
        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:top_k]
        return [(self._docs[i][0], s) for i, s in ranked if s > 0]


# ---------------------------------------------------------------------------
# Scheme Retriever
# ---------------------------------------------------------------------------

class SchemeRetriever:
    """In-process scheme context retriever backed by parsed scheme JSONs."""

    def __init__(self, rule_base_path: Path) -> None:
        self._rule_base = rule_base_path
        self._schemes: dict[str, dict[str, Any]] = {}  # scheme_id → full JSON
        self._index = TermIndex()
        self._loaded = False
        self._load()

    def _load(self) -> None:
        """Load all parsed scheme JSONs and build the TF-IDF index.

        Handles both single-scheme files and batch files (list of schemes).
        """
        if not self._rule_base.exists():
            logger.warning(
                "Rule base path %s does not exist — RAG disabled", self._rule_base
            )
            return
        count = 0
        for json_path in self._rule_base.glob("**/*.json"):
            if json_path.name.startswith("."):
                continue  # skip hidden files like .gemini_cache.json
            try:
                with open(json_path, encoding="utf-8") as f:
                    raw = json.load(f)
                # Handle batch file (list) or single scheme (dict)
                if isinstance(raw, list):
                    schemes_in_file = raw
                elif isinstance(raw, dict):
                    # Could be a single scheme or a wrapper {"schemes": [...]}
                    if "schemes" in raw and isinstance(raw["schemes"], list):
                        schemes_in_file = raw["schemes"]
                    else:
                        schemes_in_file = [raw]
                else:
                    continue

                for scheme in schemes_in_file:
                    if not isinstance(scheme, dict):
                        continue
                    sid = scheme.get("scheme_id") or f"{json_path.stem}_{count}"
                    self._schemes[sid] = scheme
                    # Build index text: name + description + rule descriptions
                    index_parts: list[str] = [
                        scheme.get("scheme_name", ""),
                        scheme.get("description", ""),
                        scheme.get("ministry", ""),
                        scheme.get("short_name", ""),
                        str(scheme.get("state_scope", "")),
                    ]
                    for rule in scheme.get("rules", []):
                        # Support both formats:
                        # - Old format: rule has nested "conditions" list
                        # - Kaggle batch format: rule itself is the condition
                        index_parts.append(
                            rule.get("description") or rule.get("Description") or
                            rule.get("display_text") or rule.get("Display_Text") or ""
                        )
                        index_parts.append(rule.get("rule_name") or rule.get("Rule_ID") or "")
                        conds = rule.get("conditions", [])
                        if conds:
                            for cond in conds:
                                if isinstance(cond, dict):
                                    index_parts.append(str(cond.get("field", "")))
                                    index_parts.append(str(cond.get("description", "")))
                        else:
                            # Flat rule — Field and Display_Text contain key info
                            index_parts.append(str(rule.get("Field") or rule.get("field") or ""))
                            index_parts.append(str(rule.get("Display_Text") or rule.get("display_text") or ""))
                    self._index.add(sid, " ".join(filter(None, index_parts)))
                    count += 1

            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to load scheme file %s: %s", json_path.name, exc)

        self._index.build()
        self._loaded = True
        logger.info("RAG index built from %d schemes across parsed files", count)


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        profile: dict[str, Any],
        top_k: int = 3,
    ) -> list[SchemeContext]:
        """Retrieve top-k relevant scheme contexts for a query + profile.

        Returns an empty list if the rule base is not loaded.
        """
        if not self._loaded or not self._schemes:
            return []

        # Build query text from user message + profile summary
        profile_text = " ".join(
            f"{k} {v}" for k, v in profile.items() if v is not None
        )
        full_query = f"{query} {profile_text}"

        hits = self._index.query(full_query, top_k=top_k)
        contexts: list[SchemeContext] = []

        for scheme_id, score in hits:
            scheme = self._schemes.get(scheme_id, {})
            ctx = self._build_context(scheme_id, scheme, profile, score)
            contexts.append(ctx)

        return contexts

    def get_proactive_questions(
        self,
        profile: dict[str, Any],
        top_k: int = 3,
    ) -> list[tuple[str, str, str]]:
        """Return fields needed by relevant schemes that aren't in the profile.

        Returns list of (field_path, question_en, question_hi) tuples,
        ordered by how many retrieved schemes need that field.
        """
        if not self._loaded:
            return []

        # Retrieve relevant schemes based on current profile alone
        contexts = self.retrieve("", profile, top_k=top_k * 2)
        populated = {k for k, v in profile.items() if v is not None}

        field_count: Counter[str] = Counter()
        for ctx in contexts:
            for fp in ctx.profile_gaps:
                if fp not in populated:
                    field_count[fp] += 1

        result: list[tuple[str, str, str]] = []
        for fp, _ in field_count.most_common(top_k * 2):
            meta = _FIELD_META.get(fp, {})
            q_en = meta.get("q_en", "")
            q_hi = meta.get("q_hi", "")
            # Fall back to FIELD_QUESTION_MAP from templates if not in _FIELD_META
            if not q_en:
                from src.conversation.templates import FIELD_QUESTION_MAP
                fq = FIELD_QUESTION_MAP.get(fp, {})
                q_en = fq.get("en", "")
                q_hi = fq.get("hi", "")
            # Skip fields we have no human-readable question for
            if not q_en or q_en == "_document_":
                continue
            result.append((fp, q_en, q_hi))
            if len(result) >= top_k:
                break
        return result

    def get_gap_analysis(
        self,
        profile: dict[str, Any],
        top_k: int = 5,
    ) -> list[ProfileGap]:
        """Return gap analysis — missing fields sorted by scheme impact."""
        contexts = self.retrieve("", profile, top_k=top_k)
        populated = {k for k, v in profile.items() if v is not None}

        field_schemes: dict[str, list[str]] = defaultdict(list)
        for ctx in contexts:
            for fp in ctx.profile_gaps:
                if fp not in populated:
                    field_schemes[fp].append(ctx.scheme_name)

        gaps: list[ProfileGap] = []
        for fp, scheme_names in sorted(
            field_schemes.items(), key=lambda x: len(x[1]), reverse=True
        ):
            meta = _FIELD_META.get(fp, {})
            q_en = meta.get("q_en", "")
            if not q_en:
                from src.conversation.templates import FIELD_QUESTION_MAP
                fq = FIELD_QUESTION_MAP.get(fp, {})
                q_en = fq.get("en", "")
            # Skip completely unknown fields (raw field paths)
            if not q_en or q_en == "_document_":
                continue
            label = meta.get("label", fp.split(".")[-1].replace("_", " ").title())
            gaps.append(ProfileGap(
                field_path=fp,
                field_label=label,
                affects_schemes=len(scheme_names),
                question_en=q_en,
                question_hi=meta.get("q_hi", ""),
                fix_instruction=_fix_instruction(fp),
                estimated_days=_fix_timeline(fp),
            ))
        return gaps

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_context(
        self,
        scheme_id: str,
        scheme: dict[str, Any],
        profile: dict[str, Any],
        score: float,
    ) -> SchemeContext:
        """Build a SchemeContext from a scheme JSON and current profile."""
        populated = {k for k, v in profile.items() if v is not None}

        # Collect required fields from scheme rules
        required_fields: list[str] = []
        rule_traces: list[RuleTrace] = []
        for rule in scheme.get("rules", []):
            # Support both formats:
            # - Old format: rule has nested "conditions" list
            # - Kaggle batch format: rule itself is the condition (has "Field" key)
            cond_items: list[dict] = rule.get("conditions", [])
            if not cond_items:
                # Flat rule — treat the rule dict itself as the single condition
                cond_items = [rule]

            for cond in cond_items:
                if not isinstance(cond, dict):
                    continue
                # field key can be field_path / field / Field (batch format)
                fp = (
                    cond.get("field_path") or
                    cond.get("field") or
                    cond.get("Field") or ""
                )
                # Normalise to lowercase dot-path (batch files use same case already)
                fp = fp.strip()
                if fp and fp not in required_fields:
                    required_fields.append(fp)
                # Derive human-readable description for the trace
                description = (
                    rule.get("description") or rule.get("Description") or
                    rule.get("display_text") or rule.get("Display_Text") or
                    cond.get("description") or cond.get("Display_Text") or ""
                )
                rule_id = (
                    rule.get("rule_id") or rule.get("Rule_ID") or
                    cond.get("Rule_ID") or ""
                )
                rule_traces.append(RuleTrace(
                    rule_id=rule_id,
                    description=description,
                    passed=fp in populated if fp else False,
                    user_value=profile.get(fp) if fp else None,
                    source_ref=(
                        rule.get("source_ref") or rule.get("Source_Quote") or
                        cond.get("Source_Quote") or ""
                    ),
                    source_url=(
                        rule.get("source_url") or rule.get("Source_URL") or
                        cond.get("Source_URL") or ""
                    ),
                    caveat=(
                        rule.get("caveat") or rule.get("Notes") or
                        cond.get("Notes") or ""
                    ),
                ))

        profile_gaps = [f for f in required_fields if f not in populated]

        # Build gap details
        gap_details: list[ProfileGap] = []
        for fp in profile_gaps[:5]:  # top 5 gaps
            meta = _FIELD_META.get(fp, {})
            gap_details.append(ProfileGap(
                field_path=fp,
                field_label=meta.get("label", fp),
                affects_schemes=1,
                question_en=meta.get("q_en", f"Could you tell me your {fp}?"),
                question_hi=meta.get("q_hi", ""),
                fix_instruction=_fix_instruction(fp),
                estimated_days=_fix_timeline(fp),
            ))

        # Parse ambiguity flags from scheme
        amb_flags: list[AmbiguityFlag] = []
        for amb in scheme.get("ambiguity_flags", []):
            type_code = amb.get("ambiguity_type_code", 0)
            amb_flags.append(AmbiguityFlag(
                amb_id=amb.get("ambiguity_id", ""),
                type_code=type_code,
                type_name=AMBIGUITY_TYPE_NAMES.get(type_code, f"Type {type_code}"),
                severity=amb.get("severity", "MEDIUM"),
                description=amb.get("description", ""),
                source_quote=amb.get("source_quote", ""),
                impact_on_result=_amb_impact(amb.get("severity", "MEDIUM")),
            ))

        relevance = "high" if score > 0.5 else ("medium" if score > 0.2 else "low")
        scheme_name = scheme.get("scheme_name", scheme_id)

        return SchemeContext(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            relevance=relevance,
            why_relevant=_why_relevant(scheme, profile),
            required_fields=required_fields,
            profile_gaps=profile_gaps,
            gap_details=gap_details,
            rule_traces=rule_traces,
            ambiguity_flags=amb_flags,
            confidence_estimate=round(
                (len(required_fields) - len(profile_gaps)) / max(len(required_fields), 1),
                2,
            ),
        )


# ---------------------------------------------------------------------------
# Helper texts
# ---------------------------------------------------------------------------

def _fix_instruction(field_path: str) -> str:
    instructions = {
        "applicant.land_ownership_status": "Get land records (Khasra/Khatauni) from the local Tehsildar office",
        "household.land_acres": "Get land records showing acreage from the local Tehsildar or Revenue office",
        "documents.aadhaar": "Register at the nearest Aadhaar Seva Kendra or Common Service Centre (CSC)",
        "documents.bank_account": "Open a Jan Dhan account at any nationalised bank — no minimum balance required",
        "applicant.caste_category": "Obtain a caste certificate from SDM/Tehsildar office",
        "household.income_annual": "Obtain an income certificate from SDM/Tehsildar office",
    }
    return instructions.get(field_path, "")


def _fix_timeline(field_path: str) -> str:
    timelines = {
        "documents.aadhaar": "7–15 working days",
        "documents.bank_account": "Same day (Jan Dhan)",
        "applicant.caste_category": "15–30 working days",
        "applicant.land_ownership_status": "7–15 working days",
        "household.income_annual": "7–15 working days",
    }
    return timelines.get(field_path, "")


def _amb_impact(severity: str) -> str:
    return {
        "CRITICAL": "This rule's outcome may be determined differently by different district offices — a partial determination is provided.",
        "HIGH": "This ambiguity may affect the confidence score. The local office may interpret this rule differently.",
        "MEDIUM": "Minor wording ambiguity noted. Outcome is likely unchanged but documented for audit.",
        "LOW": "Low-impact wording issue. No action required.",
    }.get(severity, "")


def _why_relevant(scheme: dict[str, Any], profile: dict[str, Any]) -> str:
    """Generate a one-line explanation of why a scheme is relevant."""
    name = scheme.get("scheme_name", "This scheme")
    tags: list[str] = []
    if profile.get("employment.type") == "agriculture":
        tags.append("farming")
    if profile.get("applicant.caste_category") in ("SC", "ST"):
        tags.append(f"{profile['applicant.caste_category']} category")
    if profile.get("applicant.gender") == "female":
        tags.append("women")
    if tags:
        return f"{name} is relevant for {', '.join(tags)}"
    return f"{name} matches your profile"
