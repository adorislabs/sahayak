"""DSL rule builder and DMN renderer for CBC Part 1.

Provides:
  - FIELD_NAMESPACE: canonical field paths for all rule conditions
  - build_atomic_rule(): construct and validate a single Rule
  - build_rule_group(): construct an AND/OR compound rule group
  - render_dmn_row(): render one Rule as a DMN Decision Table row dict
  - render_dmn_table(): render a list of Rules as a Markdown DMN table

Why a canonical field namespace: Without a fixed vocabulary, different parsers
produce inconsistent field names ('age', 'applicant_age', 'AGE'), making cross-scheme
comparison impossible.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.exceptions import ValidationError
from src.schema import Operator, Rule, RuleGroup, SourceAnchor


# ---------------------------------------------------------------------------
# Canonical field namespace (50+ paths)
# ---------------------------------------------------------------------------

FIELD_NAMESPACE: dict[str, str] = {
    # Applicant demographics
    "applicant.age": "Applicant Age (years)",
    "applicant.gender": "Applicant Gender",
    "applicant.caste_category": "Applicant Caste Category",
    "applicant.disability_status": "Applicant Disability Status",
    "applicant.disability_percentage": "Applicant Disability Percentage (%)",
    "applicant.marital_status": "Applicant Marital Status",
    "applicant.widowed": "Applicant is Widowed",
    "applicant.nationality": "Applicant Nationality",
    "applicant.domicile_state": "Applicant Domicile State",
    "applicant.education_level": "Applicant Education Level",
    "applicant.employment_type": "Applicant Employment Type",
    "applicant.occupation": "Applicant Occupation",
    "applicant.aadhaar_linked": "Applicant Aadhaar Linked to Bank",
    "applicant.aadhaar_number": "Applicant Aadhaar Number",
    "applicant.bank_account": "Applicant Has Bank Account",
    "applicant.pan_number": "Applicant PAN Number",
    "applicant.date_of_birth": "Applicant Date of Birth",
    "applicant.is_minor": "Applicant is Minor",
    "applicant.guardian_name": "Applicant Guardian Name",
    # Agricultural / land
    "applicant.land_ownership_status": "Applicant Owns Agricultural Land",
    "applicant.farmer_type": "Applicant Farmer Type (small/marginal/large)",
    "household.land_acres": "Household Land Owned (acres)",
    "household.land_type": "Household Land Type (irrigated/rainfed)",
    "household.land_records_state": "Land Records State",
    # Household / income
    "household.income_annual": "Household Annual Income (INR)",
    "household.income_monthly": "Household Monthly Income (INR)",
    "household.bpl_status": "Household is Below Poverty Line",
    "household.ration_card_type": "Ration Card Category",
    "household.ration_card_number": "Ration Card Number",
    "household.size": "Household Size (number of members)",
    "household.dependent_count": "Number of Dependents",
    "household.residence_type": "Household Residence Type (rural/urban/semi-urban)",
    "household.domicile_years": "Years of Domicile in State",
    # Enrollment / social security membership
    "enrollment.epfo": "Enrolled in EPFO",
    "enrollment.nps": "Enrolled in NPS",
    "enrollment.esic": "Enrolled in ESIC",
    "enrollment.pmjdy": "Enrolled in PM Jan Dhan Yojana",
    "enrollment.ayushman": "Enrolled in Ayushman Bharat",
    "enrollment.pmkisan": "Enrolled in PM-KISAN",
    "enrollment.mudra": "Availed MUDRA loan",
    # Scheme-specific
    "scheme.prerequisite_scheme_id": "Prerequisite Scheme",
    "scheme.last_applied_date": "Last Scheme Application Date",
    "scheme.benefit_received": "Scheme Benefit Already Received",
    "scheme.application_state": "State of Application",
    # Income tax / formal sector
    "tax.income_tax_payer": "Applicant Pays Income Tax",
    "tax.gst_registered": "Business is GST Registered",
    "tax.turnover_annual": "Annual Business Turnover (INR)",
    # Infrastructure / location
    "location.state": "State",
    "location.district": "District",
    "location.village": "Village",
    "location.pin_code": "PIN Code",
    "location.tribal_area": "Located in Scheduled Tribal Area",
    "location.flood_prone": "Located in Flood-Prone Area",
    # Health
    "health.disability_certificate": "Has Disability Certificate (UDID)",
    "health.chronic_illness": "Has Chronic Illness",
    "health.pregnancy_status": "Applicant is Pregnant",
    "health.child_count": "Number of Children",
    # Employment
    "employment.sector": "Employment Sector (organised/unorganised)",
    "employment.daily_wage": "Daily Wage (INR)",
    "employment.contract_type": "Employment Contract Type",
}


# ---------------------------------------------------------------------------
# build_atomic_rule
# ---------------------------------------------------------------------------


def build_atomic_rule(
    rule_id: str,
    scheme_id: str,
    field: str,
    operator: Operator | str,
    value: Any,
    source_anchor: SourceAnchor,
    parse_run_id: str,
    **kwargs: Any,
) -> Rule:
    """Construct and validate an atomic Rule.

    Why: A factory function that validates operator vocabulary and field namespace
    before delegating to the Pydantic model, providing richer error messages
    than raw Pydantic errors.

    Args:
        rule_id: Unique rule identifier (e.g. "PMKISAN-R001").
        scheme_id: Parent scheme identifier.
        field: Dot-path field from FIELD_NAMESPACE (e.g. "applicant.age").
        operator: One of the 14 supported operators from the Operator enum.
        value: Primary comparison value (None for BETWEEN / IS_NULL / IS_NOT_NULL).
        source_anchor: Provenance record from the source document.
        parse_run_id: Identifier for the parsing run that produced this rule.
        **kwargs: Optional Rule fields (value_min, value_max, values, display_text, …).

    Raises:
        ValidationError: If operator is not in the 14-operator vocabulary,
                         or if field is not in the canonical FIELD_NAMESPACE.
    """
    # Validate operator
    try:
        op_enum = Operator(operator) if isinstance(operator, str) else operator
    except ValueError:
        raise ValidationError(
            f"Invalid operator '{operator}'. Must be one of: "
            + ", ".join(o.value for o in Operator)
        )

    # Validate field namespace
    if field not in FIELD_NAMESPACE:
        raise ValidationError(
            f"Field '{field}' is not in the canonical field namespace. "
            "Add it to FIELD_NAMESPACE in spec_04_rule_expression.py if required."
        )

    # Auto-generate display_text if not supplied
    if "display_text" not in kwargs:
        kwargs["display_text"] = _generate_display_text(field, op_enum, value, kwargs)

    return Rule(
        rule_id=rule_id,
        scheme_id=scheme_id,
        field=field,
        operator=op_enum,
        value=value,
        source_anchor=source_anchor,
        parse_run_id=parse_run_id,
        confidence=kwargs.pop("confidence", 0.90),
        rule_type=kwargs.pop("rule_type", "eligibility"),
        condition_type=kwargs.pop("condition_type", _infer_condition_type(field)),
        **kwargs,
    )


def _infer_condition_type(field: str) -> str:
    """Infer a condition_type label from the field path."""
    segment = field.split(".")[-1]
    mapping = {
        "age": "age_range",
        "income_annual": "income_ceiling",
        "income_monthly": "income_ceiling",
        "caste_category": "caste_category",
        "land_ownership_status": "land_ownership",
        "land_acres": "land_holding",
        "gender": "gender",
        "disability_status": "disability",
        "epfo": "scheme_enrollment",
        "nps": "scheme_enrollment",
        "esic": "scheme_enrollment",
        "bpl_status": "poverty_status",
        "ration_card_type": "ration_card",
    }
    return mapping.get(segment, segment)


def _generate_display_text(
    field: str,
    operator: Operator,
    value: Any,
    kwargs: dict[str, Any],
) -> str:
    """Generate a human-readable display_text from field/operator/value."""
    label = FIELD_NAMESPACE.get(field, field)

    if operator == Operator.BETWEEN:
        vmin = kwargs.get("value_min", "?")
        vmax = kwargs.get("value_max", "?")
        # Include age-specific wording for age fields
        if "age" in field:
            return f"Applicant age must be between {vmin} and {vmax} years"
        return f"{label} must be between {vmin} and {vmax}"
    elif operator == Operator.EQ:
        return f"{label} must equal {value}"
    elif operator == Operator.NEQ:
        return f"{label} must not equal {value}"
    elif operator in (Operator.LT, Operator.LTE):
        cmp = "<" if operator == Operator.LT else "≤"
        return f"{label} {cmp} {value}"
    elif operator in (Operator.GT, Operator.GTE):
        cmp = ">" if operator == Operator.GT else "≥"
        return f"{label} {cmp} {value}"
    elif operator in (Operator.IN, Operator.NOT_MEMBER):
        values = kwargs.get("values", [value])
        op_word = "must be one of" if operator == Operator.IN else "must not be a member of"
        return f"{label} {op_word}: {', '.join(str(v) for v in values)}"
    elif operator == Operator.NOT_IN:
        values = kwargs.get("values", [value])
        return f"{label} must not be: {', '.join(str(v) for v in values)}"
    elif operator == Operator.IS_NULL:
        return f"{label} must be absent"
    elif operator == Operator.IS_NOT_NULL:
        return f"{label} must be present"
    elif operator == Operator.CONTAINS:
        return f"{label} must contain '{value}'"
    elif operator == Operator.MATCHES:
        return f"{label} must match pattern '{value}'"
    return f"{label} {operator.value} {value}"


# ---------------------------------------------------------------------------
# build_rule_group
# ---------------------------------------------------------------------------


def build_rule_group(
    rule_group_id: str,
    scheme_id: str,
    logic: str,
    rule_ids: List[str],
) -> RuleGroup:
    """Build an AND/OR compound rule group.

    Why: Compound eligibility conditions (e.g. age AND income AND land ownership)
    must be expressed as groups so the evaluation engine knows to AND or OR them.

    Raises:
        ValidationError: If logic is not 'AND', 'OR', or 'AND_OR_AMBIGUOUS',
                         or if rule_ids is empty.
    """
    valid_logic = {"AND", "OR", "AND_OR_AMBIGUOUS"}
    if logic not in valid_logic:
        raise ValidationError(
            f"Invalid logic '{logic}'. Must be one of: {sorted(valid_logic)}"
        )

    if not rule_ids:
        raise ValidationError(
            f"rule_ids must be non-empty for group '{rule_group_id}'"
        )

    display_logic = {"AND": "ALL", "OR": "ANY", "AND_OR_AMBIGUOUS": "ALL OR ANY (ambiguous)"}
    display_text = f"Applicant must satisfy {display_logic.get(logic, logic)} of the following rules"

    return RuleGroup(
        rule_group_id=rule_group_id,
        scheme_id=scheme_id,
        logic=logic,
        rule_ids=rule_ids,
        display_text=display_text,
    )


# ---------------------------------------------------------------------------
# DMN rendering
# ---------------------------------------------------------------------------


def render_dmn_row(rule: Rule) -> dict[str, Any]:
    """Render a single Rule as a DMN Decision Table row (column-mapped dict).

    Output is deterministic and round-trippable — the same Rule always produces
    the same dict.

    Why: DMN is a W3C standard that policy officers and business analysts
    understand. Rendering to DMN enables non-technical stakeholders to audit rules.

    Raises:
        ValidationError: If rule is missing required fields (e.g. empty display_text).
    """
    if not rule.display_text:
        raise ValidationError(
            f"Rule '{rule.rule_id}' has empty display_text; cannot render DMN row"
        )

    # Build the condition expression string
    condition = _format_condition(rule)

    return {
        "Rule_ID": rule.rule_id,
        "Scheme_ID": rule.scheme_id,
        "Rule_Type": rule.rule_type,
        "Condition_Type": rule.condition_type,
        "Field": rule.field,
        "Operator": rule.operator.value,
        "Condition": condition,
        "Source_Quote": rule.source_anchor.source_quote,
        "Source_URL": rule.source_anchor.source_url,
        "Confidence": rule.confidence,
        "Audit_Status": rule.audit_status.value,
        "Display_Text": rule.display_text,
        "Version": rule.version,
    }


def _format_condition(rule: Rule) -> str:
    """Format a human-readable condition expression for the DMN table."""
    op = rule.operator
    if op == Operator.BETWEEN:
        return f"{rule.field} BETWEEN {rule.value_min} AND {rule.value_max}"
    elif op in (Operator.IN, Operator.NOT_IN, Operator.NOT_MEMBER):
        vals = ", ".join(str(v) for v in rule.values) if rule.values else str(rule.value)
        return f"{rule.field} {op.value} ({vals})"
    elif op in (Operator.IS_NULL, Operator.IS_NOT_NULL):
        return f"{rule.field} {op.value}"
    else:
        return f"{rule.field} {op.value} {rule.value}"


def render_dmn_table(rules: List[Rule]) -> str:
    """Render a list of Rules as a DMN Decision Table in Markdown format.

    Suitable for human audit by policy officers without engineering background.

    Why Markdown: Renderable in GitHub, Notion, and any policy-team wiki without
    requiring specialised DMN tooling.
    """
    if not rules:
        return "| Rule_ID | Field | Operator | Condition | Display_Text |\n|---|---|---|---|---|\n"

    rows = [render_dmn_row(rule) for rule in rules]

    # Build Markdown table
    columns = list(rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    data_rows = [
        "| " + " | ".join(str(row.get(col, "")) for col in columns) + " |"
        for row in rows
    ]

    return "\n".join([header, separator] + data_rows)
