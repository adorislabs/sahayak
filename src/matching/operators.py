"""14 operator evaluation functions for DMN rule evaluation.

All functions return Optional[bool]:
  - True:  condition is satisfied
  - False: condition is not satisfied
  - None:  cannot determine (missing data, type mismatch, invalid pattern)

None is NEVER raised — all exceptions are caught internally.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from src.schema import Operator


def op_eq(user_value: Any, rule_value: Any) -> Optional[bool]:
    """EQ: user_value == rule_value. Returns None if user_value is None or types mismatch."""
    if user_value is None:
        return None
    try:
        # Handle numeric types loosely (int vs float)
        if isinstance(rule_value, (int, float)) and isinstance(user_value, (int, float)):
            return float(user_value) == float(rule_value)
        if type(user_value) != type(rule_value):
            # Allow bool vs non-bool comparison to return None
            if isinstance(user_value, bool) or isinstance(rule_value, bool):
                if not (isinstance(user_value, bool) and isinstance(rule_value, bool)):
                    return None
            # String vs non-string
            if isinstance(user_value, str) != isinstance(rule_value, str):
                return None
        return user_value == rule_value
    except (TypeError, ValueError):
        return None


def op_neq(user_value: Any, rule_value: Any) -> Optional[bool]:
    """NEQ: user_value != rule_value. Returns None if user_value is None or types mismatch."""
    if user_value is None:
        return None
    result = op_eq(user_value, rule_value)
    if result is None:
        return None
    return not result


def op_lt(user_value: Any, rule_value: Any) -> Optional[bool]:
    """LT: user_value < rule_value. Returns None on non-numeric or missing data."""
    if user_value is None:
        return None
    try:
        return float(user_value) < float(rule_value)
    except (TypeError, ValueError):
        return None


def op_lte(user_value: Any, rule_value: Any) -> Optional[bool]:
    """LTE: user_value <= rule_value. Returns None on non-numeric or missing data."""
    if user_value is None:
        return None
    try:
        return float(user_value) <= float(rule_value)
    except (TypeError, ValueError):
        return None


def op_gt(user_value: Any, rule_value: Any) -> Optional[bool]:
    """GT: user_value > rule_value. Returns None on non-numeric or missing data."""
    if user_value is None:
        return None
    try:
        return float(user_value) > float(rule_value)
    except (TypeError, ValueError):
        return None


def op_gte(user_value: Any, rule_value: Any) -> Optional[bool]:
    """GTE: user_value >= rule_value. Returns None on non-numeric or missing data."""
    if user_value is None:
        return None
    try:
        return float(user_value) >= float(rule_value)
    except (TypeError, ValueError):
        return None


def op_between(
    user_value: Any, lower: float | None, upper: float | None
) -> Optional[bool]:
    """BETWEEN: lower <= user_value <= upper. Returns None on non-numeric or missing data."""
    if user_value is None:
        return None
    if lower is None or upper is None:
        return None
    try:
        uv = float(user_value)
        return float(lower) <= uv <= float(upper)
    except (TypeError, ValueError):
        return None


def op_in(user_value: Any, valid_values: list[Any] | None) -> Optional[bool]:
    """IN: user_value is in the valid_values list. Returns None if user_value is None."""
    if user_value is None:
        return None
    if not valid_values:
        return False
    try:
        return user_value in valid_values
    except TypeError:
        return None


def op_not_in(user_value: Any, excluded_values: list[Any] | None) -> Optional[bool]:
    """NOT_IN: user_value is NOT in excluded_values. Returns None if user_value is None."""
    if user_value is None:
        return None
    if not excluded_values:
        return True
    try:
        return user_value not in excluded_values
    except TypeError:
        return None


def op_not_member(user_value: Any, group_values: list[Any] | None) -> Optional[bool]:
    """NOT_MEMBER: no element of user_value (list) appears in group_values.

    Returns None if user_value is None. Returns True if user_value is an empty list.
    """
    if user_value is None:
        return None
    if not group_values:
        return True
    try:
        if not isinstance(user_value, (list, set, tuple)):
            return None
        return not any(v in group_values for v in user_value)
    except TypeError:
        return None


def op_is_null(user_value: Any) -> Optional[bool]:
    """IS_NULL: user_value is None. Always returns True or False, never None."""
    return user_value is None


def op_is_not_null(user_value: Any) -> Optional[bool]:
    """IS_NOT_NULL: user_value is not None. Always returns True or False, never None."""
    return user_value is not None


def op_contains(user_value: Any, substring: Any) -> Optional[bool]:
    """CONTAINS: substring is in user_value (string or list). Returns None if user_value is None."""
    if user_value is None:
        return None
    try:
        if isinstance(user_value, (list, set, tuple)):
            return substring in user_value
        return substring in str(user_value)
    except TypeError:
        return None


def op_matches(user_value: Any, pattern: Any) -> Optional[bool]:
    """MATCHES: user_value matches regex pattern. Returns None on invalid pattern or missing data."""
    if user_value is None:
        return None
    try:
        compiled = re.compile(str(pattern))
        return bool(compiled.search(str(user_value)))
    except (re.error, TypeError, ValueError):
        return None


def evaluate_operator(
    operator: Operator,
    user_value: Any,
    rule_value: Any = None,
    *,
    rule_value_min: float | None = None,
    rule_value_max: float | None = None,
    rule_values: list[Any] | None = None,
) -> Optional[bool]:
    """Dispatch to the correct op_* function based on the operator enum.

    Returns:
        True: condition satisfied
        False: condition not satisfied
        None: cannot determine (missing data, type mismatch)

    Never raises. All exceptions are caught internally.
    """
    try:
        if operator == Operator.EQ:
            return op_eq(user_value, rule_value)
        elif operator == Operator.NEQ:
            return op_neq(user_value, rule_value)
        elif operator == Operator.LT:
            return op_lt(user_value, rule_value)
        elif operator == Operator.LTE:
            return op_lte(user_value, rule_value)
        elif operator == Operator.GT:
            return op_gt(user_value, rule_value)
        elif operator == Operator.GTE:
            return op_gte(user_value, rule_value)
        elif operator == Operator.BETWEEN:
            return op_between(user_value, rule_value_min, rule_value_max)
        elif operator == Operator.IN:
            return op_in(user_value, rule_values)
        elif operator == Operator.NOT_IN:
            return op_not_in(user_value, rule_values)
        elif operator == Operator.NOT_MEMBER:
            return op_not_member(user_value, rule_values)
        elif operator == Operator.IS_NULL:
            return op_is_null(user_value)
        elif operator == Operator.IS_NOT_NULL:
            return op_is_not_null(user_value)
        elif operator == Operator.CONTAINS:
            return op_contains(user_value, rule_value)
        elif operator == Operator.MATCHES:
            return op_matches(user_value, rule_value)
        else:
            return None
    except Exception:
        return None
