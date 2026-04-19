"""Shared fixtures for the Part 2 matching engine test suite.

All fixtures produce typed objects (real Pydantic models and dataclasses from
src.spec_03_schema) rather than raw dicts. Tests that need disk-level JSON files
reference TEST_DATA_DIR directly.

Layout
------
- Profile fixtures:      valid_profile_farmer, valid_profile_widow, minimal_profile,
                         full_profile, profile_with_disability
- Rule fixtures:         rule_pmkisan_land, rule_pmkisan_disqualify, rule_pmsym_age, ...
- SchemeRuleSet fixtures: mock_pmkisan_ruleset, mock_pmsym_ruleset, mock_mgnrega_ruleset,
                          mock_nsap_ruleset
- Relationship fixtures: mock_relationships
- Ambiguity fixtures:    mock_ambiguity_flags, mock_ambiguity_critical
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.schema import (
    AmbiguityFlag,
    AmbiguitySeverity,
    AuditStatus,
    Operator,
    Rule,
    Scheme,
    SchemeRelationship,
    SchemeStatus,
    SourceAnchor,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TEST_DATA_DIR: Path = Path(__file__).parent.parent / "test_data"
FIXTURES_DIR: Path = TEST_DATA_DIR / "fixtures"
PROFILES_DIR: Path = TEST_DATA_DIR / "profiles"


# ---------------------------------------------------------------------------
# Helper builders (not fixtures — called inside fixtures)
# ---------------------------------------------------------------------------

def _source_anchor(scheme: str, quote: str = "Test rule source text") -> SourceAnchor:
    return SourceAnchor(
        source_url=f"https://example.gov.in/{scheme.lower()}/guidelines.pdf",
        document_title=f"{scheme} Guidelines",
        source_quote=quote,
        page_number=1,
        section="Test Section",
        notification_date="2023-01-01",
        language="en",
    )


def _make_rule(
    rule_id: str,
    scheme_id: str,
    rule_type: str,
    field: str,
    operator: Operator,
    *,
    value: Optional[Any] = None,
    value_min: Optional[float] = None,
    value_max: Optional[float] = None,
    values: Optional[list[Any]] = None,
    logic_group: Optional[str] = None,
    logic_operator: Optional[str] = None,
    state_scope: str = "central",
    audit_status: AuditStatus = AuditStatus.VERIFIED,
    ambiguity_flags: Optional[list[AmbiguityFlag]] = None,
    confidence: float = 0.95,
    supersedes_rule_id: Optional[str] = None,
    display_text: str = "Test rule display text",
) -> Rule:
    return Rule(
        rule_id=rule_id,
        scheme_id=scheme_id,
        rule_type=rule_type,
        condition_type="test_condition",
        field=field,
        operator=operator,
        value=value,
        value_min=value_min,
        value_max=value_max,
        values=values or [],
        logic_group=logic_group,
        logic_operator=logic_operator,
        prerequisite_scheme_ids=[],
        state_scope=state_scope,
        source_anchor=_source_anchor(scheme_id),
        ambiguity_flags=ambiguity_flags or [],
        confidence=confidence,
        audit_status=audit_status,
        parse_run_id="RUN-TEST-001",
        version="1.0.0",
        supersedes_rule_id=supersedes_rule_id,
        display_text=display_text,
    )


# ---------------------------------------------------------------------------
# Profile fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_profile_farmer() -> dict[str, Any]:
    """Archetypal farmer profile that should pass PM-KISAN and MGNREGA eligibility."""
    return {
        "applicant.age": 38,
        "applicant.gender": "male",
        "applicant.caste_category": "OBC",
        "applicant.marital_status": "married",
        "applicant.disability_status": False,
        "applicant.land_ownership_status": True,
        "location.state": "UP",
        "household.income_annual": 150000,
        "household.size": 5,
        "household.bpl_status": True,
        "household.ration_card_type": "BPL",
        "household.residence_type": "rural",
        "documents.aadhaar": True,
        "documents.bank_account": True,
        "documents.bank_account_type": "jan_dhan",
        "employment.type": "agriculture",
        "employment.is_income_tax_payer": False,
        "employment.is_epfo_member": False,
        "employment.is_esic_member": False,
        "employment.is_nps_subscriber": False,
    }


@pytest.fixture
def valid_profile_widow() -> dict[str, Any]:
    """Widowed woman for NSAP pension eligibility testing."""
    return {
        "applicant.age": 65,
        "applicant.gender": "female",
        "applicant.caste_category": "SC",
        "applicant.marital_status": "widowed",
        "applicant.disability_status": False,
        "location.state": "RJ",
        "household.income_annual": 60000,
        "household.size": 2,
        "household.bpl_status": True,
        "household.ration_card_type": "BPL",
        "household.residence_type": "rural",
        "documents.aadhaar": True,
        "documents.bank_account": True,
        "documents.bank_account_type": "jan_dhan",
        "employment.type": "agriculture",
        "employment.is_income_tax_payer": False,
    }


@pytest.fixture
def valid_profile_unorganised_worker() -> dict[str, Any]:
    """Unorganised sector worker profile for PM-SYM eligibility."""
    return {
        "applicant.age": 28,
        "applicant.gender": "female",
        "applicant.caste_category": "OBC",
        "applicant.marital_status": "married",
        "applicant.disability_status": False,
        "location.state": "MH",
        "household.income_annual": 120000,
        "household.income_monthly": 10000,
        "household.size": 3,
        "household.bpl_status": False,
        "household.residence_type": "urban",
        "documents.aadhaar": True,
        "documents.bank_account": True,
        "documents.bank_account_type": "jan_dhan",
        "employment.type": "unorganised",
        "employment.is_income_tax_payer": False,
        "employment.is_epfo_member": False,
        "employment.is_esic_member": False,
        "employment.is_nps_subscriber": False,
    }


@pytest.fixture
def minimal_profile() -> dict[str, Any]:
    """Minimum viable profile — only mandatory fields, no optional ones."""
    return {
        "applicant.age": 30,
        "applicant.gender": "male",
        "applicant.caste_category": "General",
        "applicant.marital_status": "married",
        "location.state": "MH",
        "household.income_annual": 200000,
        "employment.type": "formal",
    }


@pytest.fixture
def empty_profile() -> dict[str, Any]:
    """Empty profile — all fields absent."""
    return {}


@pytest.fixture
def profile_with_disability() -> dict[str, Any]:
    """Profile with disability_status=True but no disability_percentage — should trigger warning."""
    return {
        "applicant.age": 35,
        "applicant.gender": "male",
        "applicant.caste_category": "SC",
        "applicant.marital_status": "unmarried",
        "applicant.disability_status": True,
        # disability_percentage intentionally omitted
        "location.state": "UP",
        "household.income_annual": 100000,
        "employment.type": "unorganised",
        "employment.is_income_tax_payer": False,
    }


@pytest.fixture
def profile_income_inconsistency() -> dict[str, Any]:
    """Profile with annual/monthly income mismatch — should trigger cross-field warning."""
    return {
        "applicant.age": 40,
        "applicant.gender": "female",
        "applicant.caste_category": "OBC",
        "applicant.marital_status": "married",
        "location.state": "GJ",
        "household.income_annual": 180000,    # declared annual
        "household.income_monthly": 25000,    # × 12 = 300000 — >20% mismatch
        "employment.type": "self_employed",
        "employment.is_income_tax_payer": False,
    }


@pytest.fixture
def profile_tax_payer_low_income() -> dict[str, Any]:
    """is_income_tax_payer=True but income below threshold — cross-field warning."""
    return {
        "applicant.age": 45,
        "applicant.gender": "male",
        "applicant.caste_category": "General",
        "applicant.marital_status": "married",
        "location.state": "DL",
        "household.income_annual": 200000,    # below 2.5L tax threshold
        "employment.type": "formal",
        "employment.is_income_tax_payer": True,
    }


# ---------------------------------------------------------------------------
# Rule fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rule_pmkisan_land_ownership() -> Rule:
    """PMKISAN-R001: land_ownership_status EQ True (eligibility)."""
    return _make_rule(
        "PMKISAN-R001", "PMKISAN", "eligibility",
        "applicant.land_ownership_status", Operator.EQ,
        value=True,
        logic_group="PMKISAN-GROUP-A", logic_operator="AND",
        display_text="Applicant must own cultivable agricultural land",
    )


@pytest.fixture
def rule_pmkisan_disqualify_tax() -> Rule:
    """PMKISAN-DIS-001: is_income_tax_payer EQ True (disqualifying)."""
    return _make_rule(
        "PMKISAN-DIS-001", "PMKISAN", "disqualifying",
        "employment.is_income_tax_payer", Operator.EQ,
        value=True,
        display_text="Income tax paying household disqualifies from PM-KISAN",
    )


@pytest.fixture
def rule_pmsym_age_range() -> Rule:
    """PMSYM-R001: age BETWEEN 18-40 (eligibility)."""
    return _make_rule(
        "PMSYM-R001", "PMSYM", "eligibility",
        "applicant.age", Operator.BETWEEN,
        value_min=18.0, value_max=40.0,
        logic_group="PMSYM-GROUP-A", logic_operator="AND",
        display_text="Applicant must be 18–40 years old",
    )


@pytest.fixture
def rule_pmsym_not_epfo() -> Rule:
    """PMSYM-R002: is_epfo_member EQ False (eligibility)."""
    return _make_rule(
        "PMSYM-R002", "PMSYM", "eligibility",
        "employment.is_epfo_member", Operator.EQ,
        value=False,
        logic_group="PMSYM-GROUP-A", logic_operator="AND",
        display_text="Applicant must not be an EPFO member",
    )


@pytest.fixture
def rule_pmsym_disqualify_epfo() -> Rule:
    """PMSYM-DIS-001: is_epfo_member EQ True (disqualifying) — EPFO member cannot join PM-SYM."""
    return _make_rule(
        "PMSYM-DIS-001", "PMSYM", "disqualifying",
        "employment.is_epfo_member", Operator.EQ,
        value=True,
        display_text="EPFO member is disqualified from PM Shram Yogi Maandhan",
    )


@pytest.fixture
def rule_pmsym_adm_income() -> Rule:
    """PMSYM-ADM-001: income_monthly LTE 15000 (admin_discretion) — income ceiling advisory."""
    return _make_rule(
        "PMSYM-ADM-001", "PMSYM", "admin_discretion",
        "household.income_monthly", Operator.LTE,
        value=15000,
        audit_status=AuditStatus.PENDING,
        confidence=0.80,
        display_text="Monthly income should not exceed ₹15,000 (discretionary income ceiling)",
    )


@pytest.fixture
def rule_mgnrega_age_gte_18() -> Rule:
    """MGNREGA-R001: age GTE 18 (eligibility)."""
    return _make_rule(
        "MGNREGA-R001", "MGNREGA", "eligibility",
        "applicant.age", Operator.GTE,
        value=18,
        logic_group="MGNREGA-GROUP-A", logic_operator="AND",
        display_text="Applicant must be at least 18 years old",
    )


@pytest.fixture
def rule_mgnrega_rural() -> Rule:
    """MGNREGA-R002: residence_type EQ rural — has CRITICAL ambiguity."""
    amb = AmbiguityFlag(
        ambiguity_id="AMB-007",
        scheme_id="MGNREGA",
        rule_id="MGNREGA-R002",
        ambiguity_type_code=7,
        ambiguity_type_name="Portability Gap",
        description="Migrant workers cannot transfer job card across state lines.",
        severity=AmbiguitySeverity.CRITICAL,
        resolution_status="OPEN",
    )
    return _make_rule(
        "MGNREGA-R002", "MGNREGA", "eligibility",
        "household.residence_type", Operator.EQ,
        value="rural",
        logic_group="MGNREGA-GROUP-A", logic_operator="AND",
        ambiguity_flags=[amb],
        display_text="Applicant must reside in a rural area",
    )


@pytest.fixture
def rule_nsap_age_gte_60() -> Rule:
    """NSAP-R001: age GTE 60 (eligibility, OR group)."""
    return _make_rule(
        "NSAP-R001", "NSAP", "eligibility",
        "applicant.age", Operator.GTE,
        value=60,
        logic_group="NSAP-GROUP-A", logic_operator="OR",
        display_text="Applicant must be 60 years or older for old age pension",
    )


@pytest.fixture
def rule_nsap_disability_gte_40() -> Rule:
    """NSAP-R002: disability_percentage GTE 40 — NEEDS_REVIEW with CRITICAL ambiguity."""
    amb = AmbiguityFlag(
        ambiguity_id="AMB-012",
        scheme_id="NSAP",
        rule_id="NSAP-R002",
        ambiguity_type_code=12,
        ambiguity_type_name="Quota Tie-breaking Logic",
        description="Disability threshold conflict: 40% central vs 80% some states.",
        severity=AmbiguitySeverity.CRITICAL,
        resolution_status="OPEN",
    )
    return _make_rule(
        "NSAP-R002", "NSAP", "eligibility",
        "applicant.disability_percentage", Operator.GTE,
        value=40,
        logic_group="NSAP-GROUP-A", logic_operator="OR",
        audit_status=AuditStatus.NEEDS_REVIEW,
        ambiguity_flags=[amb],
        confidence=0.72,
        display_text="Applicant disability of 40%+ qualifies for disability pension",
    )


@pytest.fixture
def rule_nsap_bank_account_prerequisite() -> Rule:
    """NSAP-PRE-001: bank_account EQ True (prerequisite)."""
    return _make_rule(
        "NSAP-PRE-001", "NSAP", "prerequisite",
        "documents.bank_account", Operator.EQ,
        value=True,
        display_text="Bank account required for DBT payment",
    )


@pytest.fixture
def rule_disputed() -> Rule:
    """A rule with DISPUTED audit status — should be excluded from evaluation."""
    return _make_rule(
        "TEST-DISPUTED-001", "MGNREGA", "eligibility",
        "applicant.caste_category", Operator.IN,
        values=["SC", "ST"],
        audit_status=AuditStatus.DISPUTED,
        display_text="DISPUTED: SC/ST priority rule",
    )


@pytest.fixture
def rule_unverified_pass() -> Rule:
    """Rule with PENDING audit status — produces UNVERIFIED_PASS outcome on match."""
    return _make_rule(
        "TEST-PENDING-001", "PMSYM", "eligibility",
        "household.income_monthly", Operator.LTE,
        value=15000,
        audit_status=AuditStatus.PENDING,
        confidence=0.80,
        display_text="Monthly income ≤ ₹15,000",
    )


@pytest.fixture
def rule_needs_review_high_ambiguity() -> Rule:
    """Rule with NEEDS_REVIEW status and HIGH ambiguity — affects data confidence score."""
    amb = AmbiguityFlag(
        ambiguity_id="AMB-002",
        scheme_id="PMKISAN",
        rule_id="PMKISAN-R001",
        ambiguity_type_code=2,
        ambiguity_type_name="Evidence Gap",
        description="Leased land may or may not qualify.",
        severity=AmbiguitySeverity.HIGH,
        resolution_status="OPEN",
    )
    return _make_rule(
        "TEST-REVIEW-HIGH-001", "PMKISAN", "eligibility",
        "applicant.land_ownership_status", Operator.EQ,
        value=True,
        audit_status=AuditStatus.NEEDS_REVIEW,
        ambiguity_flags=[amb],
        confidence=0.75,
        display_text="Land ownership (needs review, evidence gap ambiguity)",
    )


@pytest.fixture
def rule_state_override_up() -> Rule:
    """State override rule for UP — supersedes PMKISAN-R001."""
    return _make_rule(
        "PMKISAN-R001-UP", "PMKISAN", "eligibility",
        "applicant.land_ownership_status", Operator.EQ,
        value=True,
        state_scope="UP",
        supersedes_rule_id="PMKISAN-R001",
        display_text="UP: Land ownership including patta holders",
    )


# ---------------------------------------------------------------------------
# SchemeRuleSet fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pmkisan_ruleset(
    rule_pmkisan_land_ownership: Rule,
    rule_pmkisan_disqualify_tax: Rule,
) -> "Any":
    """Minimal PMKISAN SchemeRuleSet: 1 disqualifying + 1 eligibility rule."""
    # Import deferred so tests fail gracefully before Agent B implements
    from src.matching.loader import SchemeRuleSet  # type: ignore[import]

    scheme = Scheme(
        scheme_id="PMKISAN",
        scheme_name="PM Kisan Samman Nidhi",
        short_name="PM-KISAN",
        ministry="Ministry of Agriculture",
        state_scope="central",
        status=SchemeStatus.ACTIVE,
        version="2.1.0",
        last_verified="2024-01-15",
        source_urls=["https://pmkisan.gov.in/guidelines.pdf"],
        created_at="2019-02-01",
        updated_at="2024-01-15",
    )
    return SchemeRuleSet(
        scheme=scheme,
        active_rules=[rule_pmkisan_disqualify_tax, rule_pmkisan_land_ownership],
        excluded_rules_count=0,
        state_overrides_applied=[],
    )


@pytest.fixture
def mock_pmsym_ruleset(
    rule_pmsym_age_range: Rule,
    rule_pmsym_not_epfo: Rule,
    rule_unverified_pass: Rule,
    rule_pmsym_disqualify_epfo: Rule,
    rule_pmsym_adm_income: Rule,
) -> "Any":
    """Full PMSYM SchemeRuleSet: disqualifying + eligibility + admin_discretion rules.

    Rules in evaluation order:
      Phase A: PMSYM-DIS-001 (is_epfo_member EQ True → DISQUALIFIED)
      Phase C: PMSYM-R001 (age 18–40), PMSYM-R002 (not EPFO), TEST-PENDING-001 (income ≤ 15k)
      Phase D: PMSYM-ADM-001 (income_monthly advisory)
    """
    from src.matching.loader import SchemeRuleSet  # type: ignore[import]

    scheme = Scheme(
        scheme_id="PMSYM",
        scheme_name="PM Shram Yogi Maandhan",
        short_name="PM-SYM",
        ministry="Ministry of Labour and Employment",
        state_scope="central",
        status=SchemeStatus.ACTIVE,
        version="1.0.0",
        last_verified="2024-02-01",
        source_urls=["https://labour.gov.in/pmsym.pdf"],
        created_at="2019-02-15",
        updated_at="2024-02-01",
    )
    return SchemeRuleSet(
        scheme=scheme,
        active_rules=[
            rule_pmsym_disqualify_epfo,   # Phase A
            rule_pmsym_age_range,         # Phase C
            rule_pmsym_not_epfo,          # Phase C
            rule_unverified_pass,         # Phase C (PENDING eligibility)
            rule_pmsym_adm_income,        # Phase D
        ],
        excluded_rules_count=0,
        state_overrides_applied=[],
    )


@pytest.fixture
def mock_mgnrega_ruleset(
    rule_mgnrega_age_gte_18: Rule,
    rule_mgnrega_rural: Rule,
) -> "Any":
    """MGNREGA SchemeRuleSet with CRITICAL ambiguity on residence rule."""
    from src.matching.loader import SchemeRuleSet  # type: ignore[import]

    scheme = Scheme(
        scheme_id="MGNREGA",
        scheme_name="MGNREGA",
        short_name="MGNREGA",
        ministry="Ministry of Rural Development",
        state_scope="central",
        status=SchemeStatus.ACTIVE,
        version="1.0.0",
        last_verified="2024-01-01",
        source_urls=["https://nrega.nic.in/act.pdf"],
        created_at="2005-09-01",
        updated_at="2024-01-01",
    )
    return SchemeRuleSet(
        scheme=scheme,
        active_rules=[rule_mgnrega_age_gte_18, rule_mgnrega_rural],
        excluded_rules_count=1,   # Disputed rule excluded
        state_overrides_applied=[],
    )


@pytest.fixture
def mock_nsap_ruleset(
    rule_nsap_age_gte_60: Rule,
    rule_nsap_disability_gte_40: Rule,
    rule_nsap_bank_account_prerequisite: Rule,
) -> "Any":
    """NSAP SchemeRuleSet: OR eligibility group + prerequisite."""
    from src.matching.loader import SchemeRuleSet  # type: ignore[import]

    scheme = Scheme(
        scheme_id="NSAP",
        scheme_name="National Social Assistance Programme",
        short_name="NSAP",
        ministry="Ministry of Rural Development",
        state_scope="central",
        status=SchemeStatus.ACTIVE,
        version="1.0.0",
        last_verified="2024-01-10",
        source_urls=["https://nsap.nic.in/guidelines.pdf"],
        created_at="1995-08-15",
        updated_at="2024-01-10",
    )
    return SchemeRuleSet(
        scheme=scheme,
        active_rules=[
            rule_nsap_bank_account_prerequisite,
            rule_nsap_age_gte_60,
            rule_nsap_disability_gte_40,
        ],
        excluded_rules_count=1,   # NSAP-REVIEW-001 in review queue
        state_overrides_applied=[],
    )


@pytest.fixture
def mock_all_rulesets(
    mock_pmkisan_ruleset: "Any",
    mock_pmsym_ruleset: "Any",
    mock_mgnrega_ruleset: "Any",
    mock_nsap_ruleset: "Any",
) -> "dict[str, Any]":
    """All 4 mock scheme rule sets keyed by scheme_id."""
    return {
        "PMKISAN": mock_pmkisan_ruleset,
        "PMSYM": mock_pmsym_ruleset,
        "MGNREGA": mock_mgnrega_ruleset,
        "NSAP": mock_nsap_ruleset,
    }


# ---------------------------------------------------------------------------
# Relationship fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_relationships() -> list[SchemeRelationship]:
    """5 scheme relationships covering all 4 relationship types."""
    return [
        SchemeRelationship(
            relationship_id="REL-001",
            scheme_a="MGNREGA",
            scheme_b="PMKISAN",
            relationship_type="COMPLEMENTARY",
            confidence=0.88,
            display_to_user=True,
            source_evidence="Both target agricultural households",
        ),
        SchemeRelationship(
            relationship_id="REL-002",
            scheme_a="PMSYM",
            scheme_b="NSAP",
            relationship_type="MUTUAL_EXCLUSION",
            confidence=0.95,
            display_to_user=True,
            source_evidence="Double pension prohibition at age 60+",
        ),
        SchemeRelationship(
            relationship_id="REL-003",
            scheme_a="MGNREGA",
            scheme_b="PMKISAN",
            relationship_type="PREREQUISITE",
            confidence=0.70,
            display_to_user=True,
            source_evidence="MGNREGA card required for PM-KISAN in some states",
        ),
        SchemeRelationship(
            relationship_id="REL-004",
            scheme_a="PMKISAN",
            scheme_b="MGNREGA",
            relationship_type="OVERLAP",
            confidence=0.65,
            display_to_user=True,
            source_evidence="Operational overlap in rural targeting",
        ),
        SchemeRelationship(
            relationship_id="REL-005",
            scheme_a="PMSYM",
            scheme_b="MGNREGA",
            relationship_type="COMPLEMENTARY",
            confidence=0.72,
            display_to_user=True,
            source_evidence="Unorganised rural workers benefit from both",
        ),
    ]


# ---------------------------------------------------------------------------
# Ambiguity fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ambiguity_flags() -> list[AmbiguityFlag]:
    """Ambiguity flags at all 4 severity levels."""
    return [
        AmbiguityFlag(
            ambiguity_id="AMB-002",
            scheme_id="PMKISAN",
            rule_id="PMKISAN-R001",
            ambiguity_type_code=2,
            ambiguity_type_name="Evidence Gap",
            description="Leased land may not qualify.",
            severity=AmbiguitySeverity.HIGH,
            resolution_status="OPEN",
        ),
        AmbiguityFlag(
            ambiguity_id="AMB-007",
            scheme_id="MGNREGA",
            rule_id="MGNREGA-R002",
            ambiguity_type_code=7,
            ambiguity_type_name="Portability Gap",
            description="Migrant job card not transferable.",
            severity=AmbiguitySeverity.CRITICAL,
            resolution_status="OPEN",
        ),
        AmbiguityFlag(
            ambiguity_id="AMB-012",
            scheme_id="NSAP",
            rule_id="NSAP-R002",
            ambiguity_type_code=12,
            ambiguity_type_name="Quota Tie-breaking Logic",
            description="Disability threshold inconsistency.",
            severity=AmbiguitySeverity.CRITICAL,
            resolution_status="OPEN",
        ),
        AmbiguityFlag(
            ambiguity_id="AMB-004",
            scheme_id="PMSYM",
            rule_id="PMSYM-ADM-001",
            ambiguity_type_code=4,
            ambiguity_type_name="Discretionary Clauses",
            description="Income verification is discretionary.",
            severity=AmbiguitySeverity.MEDIUM,
            resolution_status="OPEN",
        ),
        AmbiguityFlag(
            ambiguity_id="AMB-021",
            scheme_id="NSAP",
            rule_id="NSAP-REVIEW-001",
            ambiguity_type_code=21,
            ambiguity_type_name="Life-Event Transition Protocols",
            description="No protocol for widow who remarries.",
            severity=AmbiguitySeverity.HIGH,
            resolution_status="OPEN",
        ),
    ]


@pytest.fixture
def mock_ambiguity_critical() -> list[AmbiguityFlag]:
    """Only CRITICAL severity flags — for data confidence cap tests."""
    return [
        AmbiguityFlag(
            ambiguity_id="AMB-007",
            scheme_id="MGNREGA",
            rule_id="MGNREGA-R002",
            ambiguity_type_code=7,
            ambiguity_type_name="Portability Gap",
            description="Migrant job card not transferable.",
            severity=AmbiguitySeverity.CRITICAL,
            resolution_status="OPEN",
        ),
    ]


# ---------------------------------------------------------------------------
# Loader mock fixtures (patch src.matching.loader at module boundary)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_loader(mock_all_rulesets: "dict[str, Any]", mock_relationships: list[SchemeRelationship], mock_ambiguity_flags: list[AmbiguityFlag]) -> AsyncMock:
    """AsyncMock that returns the 4 mock rulesets when load_rule_base is called."""
    loader = AsyncMock()
    loader.load_rule_base = AsyncMock(return_value=mock_all_rulesets)
    loader.load_relationship_matrix = AsyncMock(return_value=mock_relationships)
    loader.load_ambiguity_map = AsyncMock(return_value=mock_ambiguity_flags)
    return loader


@pytest.fixture(autouse=True)
def _restore_engine_loader() -> "Any":
    """Restore the real load_rule_base on src.matching.engine before every test.

    Why needed: test_t4 runs 5 concurrent coroutines each using `with patch(...)`.
    Concurrent unittest.mock.patch calls interleave their save/restore operations and
    leave load_rule_base in a patched state after the test completes. Any subsequent
    test that expects RuleBaseError from an empty directory would silently succeed
    because the mock returns a populated rule base. This fixture is a safety net.
    """
    import src.matching.engine as _engine_mod
    from src.matching.loader import load_rule_base as _real_fn

    _engine_mod.load_rule_base = _real_fn
    yield


# ---------------------------------------------------------------------------
# Adversarial profile loader (reads from test_data/profiles/)
# ---------------------------------------------------------------------------

def load_adversarial_profile(filename: str) -> dict[str, Any]:
    """Load a named adversarial profile JSON file from test_data/profiles/."""
    path = PROFILES_DIR / filename
    with path.open() as f:
        return json.load(f)
