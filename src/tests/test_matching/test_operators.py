"""Tests for the 14 operator evaluation functions in src.matching.operators.

Spec reference: docs/part2-planning/specs/02-rule-evaluation-engine.md § Operators
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/operators.py

Key contracts tested here:
  - All 14 operator functions exist and behave correctly
  - None is returned (never raised) on TypeError / type mismatch
  - evaluate_operator dispatches correctly to each of the 14 op_* functions
  - Pure functions: no side effects, no I/O

Tests will fail (ImportError) until Agent B implements src/matching/operators.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.matching.operators import (  # type: ignore[import]
    evaluate_operator,
    op_between,
    op_contains,
    op_eq,
    op_gt,
    op_gte,
    op_in,
    op_is_not_null,
    op_is_null,
    op_lt,
    op_lte,
    op_matches,
    op_neq,
    op_not_in,
    op_not_member,
)
from src.schema import Operator


# ===========================================================================
# Group 1: op_eq
# ===========================================================================

class TestOpEq:
    """EQ: user_value == rule_value."""

    def test_op_eq_matching_integers_returns_true(self) -> None:
        """Integer equality must return True."""
        assert op_eq(30, 30) is True

    def test_op_eq_different_integers_returns_false(self) -> None:
        """Non-equal integers must return False."""
        assert op_eq(31, 30) is False

    def test_op_eq_matching_strings_returns_true(self) -> None:
        """String equality must return True."""
        assert op_eq("male", "male") is True

    def test_op_eq_different_strings_returns_false(self) -> None:
        """Different strings must return False."""
        assert op_eq("male", "female") is False

    def test_op_eq_boolean_true_true_returns_true(self) -> None:
        """Boolean True == True must return True."""
        assert op_eq(True, True) is True

    def test_op_eq_boolean_mismatch_returns_false(self) -> None:
        """Boolean True == False must return False."""
        assert op_eq(True, False) is False

    def test_op_eq_none_user_value_returns_none(self) -> None:
        """None user_value cannot be evaluated — must return None."""
        assert op_eq(None, 30) is None

    def test_op_eq_type_mismatch_returns_none(self) -> None:
        """Comparing string to integer must return None (not raise TypeError)."""
        assert op_eq("thirty", 30) is None


# ===========================================================================
# Group 2: op_neq
# ===========================================================================

class TestOpNeq:
    """NEQ: user_value != rule_value."""

    def test_op_neq_different_values_returns_true(self) -> None:
        """Different values must return True."""
        assert op_neq("married", "widowed") is True

    def test_op_neq_equal_values_returns_false(self) -> None:
        """Equal values must return False."""
        assert op_neq("SC", "SC") is False

    def test_op_neq_none_user_value_returns_none(self) -> None:
        assert op_neq(None, "SC") is None


# ===========================================================================
# Group 3: op_lt
# ===========================================================================

class TestOpLt:
    """LT: user_value < rule_value."""

    def test_op_lt_user_below_threshold_returns_true(self) -> None:
        """16 < 18 must return True."""
        assert op_lt(16, 18) is True

    def test_op_lt_user_equal_threshold_returns_false(self) -> None:
        """18 < 18 must return False (not strictly less)."""
        assert op_lt(18, 18) is False

    def test_op_lt_user_above_threshold_returns_false(self) -> None:
        """20 < 18 must return False."""
        assert op_lt(20, 18) is False

    def test_op_lt_none_user_value_returns_none(self) -> None:
        assert op_lt(None, 18) is None

    def test_op_lt_string_comparison_returns_none(self) -> None:
        """Non-numeric types must return None, not raise."""
        assert op_lt("twenty", 18) is None


# ===========================================================================
# Group 4: op_lte
# ===========================================================================

class TestOpLte:
    """LTE: user_value <= rule_value."""

    def test_op_lte_user_equal_threshold_returns_true(self) -> None:
        assert op_lte(200000, 200000) is True

    def test_op_lte_user_below_threshold_returns_true(self) -> None:
        assert op_lte(150000, 200000) is True

    def test_op_lte_user_above_threshold_returns_false(self) -> None:
        assert op_lte(250000, 200000) is False

    def test_op_lte_none_user_value_returns_none(self) -> None:
        assert op_lte(None, 200000) is None


# ===========================================================================
# Group 5: op_gt
# ===========================================================================

class TestOpGt:
    """GT: user_value > rule_value."""

    def test_op_gt_user_above_threshold_returns_true(self) -> None:
        assert op_gt(65, 60) is True

    def test_op_gt_user_equal_threshold_returns_false(self) -> None:
        assert op_gt(60, 60) is False

    def test_op_gt_user_below_threshold_returns_false(self) -> None:
        assert op_gt(55, 60) is False

    def test_op_gt_none_user_value_returns_none(self) -> None:
        assert op_gt(None, 60) is None


# ===========================================================================
# Group 6: op_gte
# ===========================================================================

class TestOpGte:
    """GTE: user_value >= rule_value."""

    def test_op_gte_user_equal_threshold_returns_true(self) -> None:
        """Exact threshold value must return True (≥ not >)."""
        assert op_gte(60, 60) is True

    def test_op_gte_user_above_threshold_returns_true(self) -> None:
        assert op_gte(72, 60) is True

    def test_op_gte_user_below_threshold_returns_false(self) -> None:
        assert op_gte(55, 60) is False

    def test_op_gte_none_user_value_returns_none(self) -> None:
        assert op_gte(None, 18) is None

    def test_op_gte_disability_threshold_boundary_exactly_40(self) -> None:
        """NSAP requires ≥ 40% disability — exactly 40 must return True."""
        assert op_gte(40, 40) is True


# ===========================================================================
# Group 7: op_between
# ===========================================================================

class TestOpBetween:
    """BETWEEN: value_min <= user_value <= value_max."""

    def test_op_between_value_in_range_returns_true(self) -> None:
        """Age 25 in [18, 40] must return True."""
        assert op_between(25, 18.0, 40.0) is True

    def test_op_between_value_at_lower_bound_returns_true(self) -> None:
        """Age 18 (lower boundary) must return True."""
        assert op_between(18, 18.0, 40.0) is True

    def test_op_between_value_at_upper_bound_returns_true(self) -> None:
        """Age 40 (upper boundary) must return True."""
        assert op_between(40, 18.0, 40.0) is True

    def test_op_between_value_below_lower_returns_false(self) -> None:
        """Age 17 is below [18, 40] — must return False."""
        assert op_between(17, 18.0, 40.0) is False

    def test_op_between_value_above_upper_returns_false(self) -> None:
        """Age 41 is above [18, 40] — must return False."""
        assert op_between(41, 18.0, 40.0) is False

    def test_op_between_none_user_value_returns_none(self) -> None:
        assert op_between(None, 18.0, 40.0) is None  # type: ignore[arg-type]

    def test_op_between_non_numeric_user_value_returns_none(self) -> None:
        """String user_value must return None, not raise."""
        assert op_between("twenty", 18.0, 40.0) is None  # type: ignore[arg-type]


# ===========================================================================
# Group 8: op_in
# ===========================================================================

class TestOpIn:
    """IN: user_value in rule_values list."""

    def test_op_in_value_present_returns_true(self) -> None:
        assert op_in("SC", ["SC", "ST", "OBC"]) is True

    def test_op_in_value_absent_returns_false(self) -> None:
        assert op_in("General", ["SC", "ST", "OBC"]) is False

    def test_op_in_empty_list_returns_false(self) -> None:
        assert op_in("SC", []) is False

    def test_op_in_none_user_value_returns_none(self) -> None:
        assert op_in(None, ["SC", "ST"]) is None

    def test_op_in_ration_card_type_bpl_in_allowed_returns_true(self) -> None:
        """Ration card BPL in [BPL, AAY, PHH] must return True."""
        assert op_in("BPL", ["BPL", "AAY", "PHH"]) is True

    def test_op_in_ration_card_type_apl_in_allowed_returns_false(self) -> None:
        """Ration card APL not in [BPL, AAY, PHH] must return False."""
        assert op_in("APL", ["BPL", "AAY", "PHH"]) is False


# ===========================================================================
# Group 9: op_not_in
# ===========================================================================

class TestOpNotIn:
    """NOT_IN: user_value not in rule_values list."""

    def test_op_not_in_value_absent_returns_true(self) -> None:
        assert op_not_in("General", ["SC", "ST", "OBC"]) is True

    def test_op_not_in_value_present_returns_false(self) -> None:
        assert op_not_in("SC", ["SC", "ST", "OBC"]) is False

    def test_op_not_in_none_user_value_returns_none(self) -> None:
        assert op_not_in(None, ["SC"]) is None


# ===========================================================================
# Group 10: op_not_member
# ===========================================================================

class TestOpNotMember:
    """NOT_MEMBER: no element of user list appears in rule list."""

    def test_op_not_member_no_overlap_returns_true(self) -> None:
        """User enrolled in [MGNREGA], scheme list is [NPS, EPFO] → no overlap → True."""
        assert op_not_member(["MGNREGA"], ["NPS", "EPFO"]) is True

    def test_op_not_member_with_overlap_returns_false(self) -> None:
        """User enrolled in [MGNREGA, NPS], scheme list is [NPS] → overlap → False."""
        assert op_not_member(["MGNREGA", "NPS"], ["NPS"]) is False

    def test_op_not_member_empty_user_list_returns_true(self) -> None:
        """Empty enrollments list → no overlap possible → True."""
        assert op_not_member([], ["NPS"]) is True

    def test_op_not_member_none_user_value_returns_none(self) -> None:
        assert op_not_member(None, ["NPS"]) is None  # type: ignore[arg-type]


# ===========================================================================
# Group 11: op_is_null / op_is_not_null
# ===========================================================================

class TestOpNullChecks:
    """IS_NULL and IS_NOT_NULL: field presence checks."""

    def test_op_is_null_with_none_returns_true(self) -> None:
        assert op_is_null(None) is True

    def test_op_is_null_with_value_returns_false(self) -> None:
        assert op_is_null(42) is False

    def test_op_is_null_with_false_returns_false(self) -> None:
        """Boolean False is a value (not null) — must return False."""
        assert op_is_null(False) is False

    def test_op_is_not_null_with_value_returns_true(self) -> None:
        assert op_is_not_null("SC") is True

    def test_op_is_not_null_with_none_returns_false(self) -> None:
        assert op_is_not_null(None) is False

    def test_op_is_not_null_with_zero_returns_true(self) -> None:
        """Integer 0 is a value (not null) — must return True."""
        assert op_is_not_null(0) is True


# ===========================================================================
# Group 12: op_contains
# ===========================================================================

class TestOpContains:
    """CONTAINS: rule_value is a substring of user_value (or element in user list)."""

    def test_op_contains_substring_present_returns_true(self) -> None:
        assert op_contains("PM-KISAN enrolled", "PM-KISAN") is True

    def test_op_contains_substring_absent_returns_false(self) -> None:
        assert op_contains("MGNREGA enrolled", "PM-KISAN") is False

    def test_op_contains_none_user_value_returns_none(self) -> None:
        assert op_contains(None, "PM-KISAN") is None

    def test_op_contains_list_with_element_returns_true(self) -> None:
        """user_value is a list and rule_value is in it."""
        assert op_contains(["MGNREGA", "NSAP"], "MGNREGA") is True


# ===========================================================================
# Group 13: op_matches
# ===========================================================================

class TestOpMatches:
    """MATCHES: user_value matches a regex pattern in rule_value."""

    def test_op_matches_valid_regex_match_returns_true(self) -> None:
        """State code 'MH' must match regex '^[A-Z]{2}$'."""
        assert op_matches("MH", r"^[A-Z]{2}$") is True

    def test_op_matches_no_match_returns_false(self) -> None:
        assert op_matches("maharashtra", r"^[A-Z]{2}$") is False

    def test_op_matches_none_user_value_returns_none(self) -> None:
        assert op_matches(None, r"^[A-Z]{2}$") is None

    @pytest.mark.filterwarnings("ignore::FutureWarning")
    def test_op_matches_invalid_regex_returns_none(self) -> None:
        """Invalid regex pattern must return None, not raise re.error."""
        assert op_matches("MH", r"[[[invalid") is None


# ===========================================================================
# Group 14: evaluate_operator dispatcher
# ===========================================================================

class TestEvaluateOperatorDispatcher:
    """evaluate_operator correctly dispatches to each of the 14 op_* functions."""

    def test_dispatcher_eq_operator(self) -> None:
        result = evaluate_operator(Operator.EQ, "male", "male")
        assert result is True

    def test_dispatcher_neq_operator(self) -> None:
        result = evaluate_operator(Operator.NEQ, "male", "female")
        assert result is True

    def test_dispatcher_lt_operator(self) -> None:
        result = evaluate_operator(Operator.LT, 16, 18)
        assert result is True

    def test_dispatcher_lte_operator(self) -> None:
        result = evaluate_operator(Operator.LTE, 200000, 200000)
        assert result is True

    def test_dispatcher_gt_operator(self) -> None:
        result = evaluate_operator(Operator.GT, 65, 60)
        assert result is True

    def test_dispatcher_gte_operator(self) -> None:
        result = evaluate_operator(Operator.GTE, 60, 60)
        assert result is True

    def test_dispatcher_between_operator_uses_min_max(self) -> None:
        result = evaluate_operator(Operator.BETWEEN, 25, None, rule_value_min=18.0, rule_value_max=40.0)
        assert result is True

    def test_dispatcher_in_operator_uses_rule_values(self) -> None:
        result = evaluate_operator(Operator.IN, "SC", None, rule_values=["SC", "ST"])
        assert result is True

    def test_dispatcher_not_in_operator(self) -> None:
        result = evaluate_operator(Operator.NOT_IN, "General", None, rule_values=["SC", "ST"])
        assert result is True

    def test_dispatcher_not_member_operator(self) -> None:
        result = evaluate_operator(Operator.NOT_MEMBER, [], None, rule_values=["NPS"])
        assert result is True

    def test_dispatcher_is_null_operator(self) -> None:
        result = evaluate_operator(Operator.IS_NULL, None, None)
        assert result is True

    def test_dispatcher_is_not_null_operator(self) -> None:
        result = evaluate_operator(Operator.IS_NOT_NULL, "something", None)
        assert result is True

    def test_dispatcher_contains_operator(self) -> None:
        result = evaluate_operator(Operator.CONTAINS, "has PM-KISAN", "PM-KISAN")
        assert result is True

    def test_dispatcher_matches_operator(self) -> None:
        result = evaluate_operator(Operator.MATCHES, "MH", r"^[A-Z]{2}$")
        assert result is True

    def test_dispatcher_none_user_value_returns_none_not_raises(self) -> None:
        """Passing None user_value to any operator must return None, never raise."""
        for operator in Operator:
            result = evaluate_operator(operator, None, "any_value")
            assert result is None or isinstance(result, bool), (
                f"evaluate_operator({operator}) with None user_value raised or returned wrong type"
            )
