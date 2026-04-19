"""Tests for the rule base loader: loading, state overrides, filtering, and error handling.

Spec reference: docs/part2-planning/specs/02-rule-evaluation-engine.md § Rule Base Loading
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/loader.py

Tests exercise:
  - load_rule_base: active scheme loading, DISPUTED exclusion, review queue exclusion,
    state override resolution, broken supersession chain
  - load_relationship_matrix: valid JSON, missing file, schema errors
  - load_ambiguity_map: valid JSON, missing file

Tests will fail (ImportError) until Agent B implements src/matching/loader.py.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from src.exceptions import CBCError  # type: ignore[import]
from src.matching.loader import (  # type: ignore[import]
    SchemeRuleSet,
    load_ambiguity_map,
    load_relationship_matrix,
    load_rule_base,
)

FIXTURES_DIR = Path(__file__).parent.parent / "test_data" / "fixtures"


# ===========================================================================
# Helpers
# ===========================================================================

def _write_scheme_file(directory: Path, filename: str, source: Path) -> None:
    """Copy a fixture scheme JSON into a temp directory."""
    shutil.copy(source, directory / filename)


def _write_review_queue(directory: Path, rule_ids: list[str]) -> None:
    (directory / "review_queue.json").write_text(json.dumps(rule_ids))


# ===========================================================================
# Group 1: load_rule_base — happy path
# ===========================================================================

class TestLoadRuleBaseHappyPath:
    """load_rule_base correctly loads and returns active schemes."""

    async def test_load_rule_base_returns_all_active_schemes(self) -> None:
        """Loading a directory with 3 active scheme files must return 3 entries."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")
            _write_scheme_file(tmp_path, "PMSYM.json", FIXTURES_DIR / "pmsym_scheme.json")
            _write_scheme_file(tmp_path, "MGNREGA.json", FIXTURES_DIR / "mgnrega_scheme.json")

            result = await load_rule_base(tmp_path)

        assert "PMKISAN" in result
        assert "PMSYM" in result
        assert "MGNREGA" in result
        assert len(result) == 3

    async def test_load_rule_base_returns_scheme_rule_set_instances(self) -> None:
        """Each value in the returned dict must be a SchemeRuleSet instance."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path)

        assert isinstance(result["PMKISAN"], SchemeRuleSet)

    async def test_load_rule_base_scheme_has_active_rules(self) -> None:
        """SchemeRuleSet.active_rules must be non-empty for a valid scheme."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path)

        assert len(result["PMKISAN"].active_rules) > 0


# ===========================================================================
# Group 2: load_rule_base — rule filtering
# ===========================================================================

class TestLoadRuleBaseFiltering:
    """load_rule_base correctly excludes DISPUTED rules and review-queue rules."""

    async def test_disputed_rules_excluded_from_active_rules(self) -> None:
        """Rules with audit_status=DISPUTED must not appear in active_rules."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "MGNREGA.json", FIXTURES_DIR / "mgnrega_scheme.json")

            result = await load_rule_base(tmp_path)

        rule_ids = [r.rule_id for r in result["MGNREGA"].active_rules]
        assert "MGNREGA-R004-DISPUTED" not in rule_ids

    async def test_disputed_rules_increment_excluded_count(self) -> None:
        """Excluding a DISPUTED rule must increment SchemeRuleSet.excluded_rules_count."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "MGNREGA.json", FIXTURES_DIR / "mgnrega_scheme.json")

            result = await load_rule_base(tmp_path)

        assert result["MGNREGA"].excluded_rules_count >= 1

    async def test_review_queue_rules_excluded_from_active_rules(self) -> None:
        """Rules listed in review_queue.json must be excluded from active_rules."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "NSAP.json", FIXTURES_DIR / "nsap_scheme.json")
            _write_review_queue(tmp_path, ["NSAP-REVIEW-001"])

            result = await load_rule_base(tmp_path)

        rule_ids = [r.rule_id for r in result["NSAP"].active_rules]
        assert "NSAP-REVIEW-001" not in rule_ids

    async def test_review_queue_exclusion_increments_excluded_count(self) -> None:
        """Review queue exclusion must be counted in SchemeRuleSet.excluded_rules_count."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "NSAP.json", FIXTURES_DIR / "nsap_scheme.json")
            _write_review_queue(tmp_path, ["NSAP-REVIEW-001"])

            result = await load_rule_base(tmp_path)

        assert result["NSAP"].excluded_rules_count >= 1

    async def test_inactive_schemes_not_loaded(self) -> None:
        """Scheme files with status != 'active' must be excluded from results."""
        inactive_scheme = {
            "scheme": {
                "scheme_id": "OLD-SCHEME",
                "scheme_name": "Old Discontinued Scheme",
                "short_name": "OLD",
                "ministry": "Test Ministry",
                "state_scope": "central",
                "status": "discontinued",
                "version": "1.0.0",
                "last_verified": "2020-01-01",
                "source_urls": [],
                "created_at": "2000-01-01",
                "updated_at": "2020-01-01",
            },
            "rules": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "OLD-SCHEME.json").write_text(json.dumps(inactive_scheme))
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path)

        assert "OLD-SCHEME" not in result
        assert "PMKISAN" in result


# ===========================================================================
# Group 3: load_rule_base — state overrides
# ===========================================================================

class TestLoadRuleBaseStateOverrides:
    """load_rule_base correctly applies state-specific rule overrides."""

    async def test_state_override_replaces_central_rule(self) -> None:
        """When user_state='UP', PMKISAN-R001 must be replaced by PMKISAN-R001-UP."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path, user_state="UP")

        rule_ids = [r.rule_id for r in result["PMKISAN"].active_rules]
        # Original central rule replaced
        assert "PMKISAN-R001" not in rule_ids
        # State override present
        assert "PMKISAN-R001-UP" in rule_ids

    async def test_state_override_recorded_in_state_overrides_applied(self) -> None:
        """Applied state overrides must be recorded in SchemeRuleSet.state_overrides_applied."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path, user_state="UP")

        assert "PMKISAN-R001-UP" in result["PMKISAN"].state_overrides_applied

    async def test_no_state_override_when_different_state(self) -> None:
        """When user_state='MH' (no override exists), central rules must not be replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path, user_state="MH")

        rule_ids = [r.rule_id for r in result["PMKISAN"].active_rules]
        # Central rule must still be present (no MH override in fixture)
        assert "PMKISAN-R001" in rule_ids

    async def test_no_user_state_loads_only_central_rules(self) -> None:
        """Without user_state, state-scoped override rules must be excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_scheme_file(tmp_path, "PMKISAN.json", FIXTURES_DIR / "pmkisan_scheme.json")

            result = await load_rule_base(tmp_path, user_state=None)

        rule_ids = [r.rule_id for r in result["PMKISAN"].active_rules]
        assert "PMKISAN-R001-UP" not in rule_ids


# ===========================================================================
# Group 4: load_rule_base — error cases
# ===========================================================================

class TestLoadRuleBaseErrors:
    """load_rule_base raises RuleBaseError appropriately."""

    async def test_empty_directory_raises_rule_base_error(self) -> None:
        """An empty schemes_dir with no JSON files must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(RuleBaseError):
                await load_rule_base(Path(tmp))

    async def test_no_active_schemes_raises_rule_base_error(self) -> None:
        """If all schemes are inactive/discontinued, RuleBaseError must be raised."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        inactive = {
            "scheme": {
                "scheme_id": "GONE",
                "scheme_name": "Gone Scheme",
                "short_name": "GONE",
                "ministry": "Ministry of Gone",
                "state_scope": "central",
                "status": "discontinued",
                "version": "1.0.0",
                "last_verified": "2020-01-01",
                "source_urls": [],
                "created_at": "2000-01-01",
                "updated_at": "2020-01-01",
            },
            "rules": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "GONE.json").write_text(json.dumps(inactive))

            with pytest.raises(RuleBaseError):
                await load_rule_base(tmp_path)

    async def test_broken_supersession_chain_raises_rule_base_error(self) -> None:
        """A state rule referencing a non-existent central rule must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        # Manually build scheme with an invalid supersession chain
        scheme_with_broken_chain = {
            "scheme": {
                "scheme_id": "BROKEN",
                "scheme_name": "Broken Scheme",
                "short_name": "BROKEN",
                "ministry": "Test",
                "state_scope": "central",
                "status": "active",
                "version": "1.0.0",
                "last_verified": "2024-01-01",
                "source_urls": [],
                "created_at": "2024-01-01",
                "updated_at": "2024-01-01",
            },
            "rules": [
                {
                    "rule_id": "BROKEN-STATE-001",
                    "scheme_id": "BROKEN",
                    "rule_type": "eligibility",
                    "condition_type": "test",
                    "field": "applicant.age",
                    "operator": "GTE",
                    "value": 18,
                    "values": [],
                    "state_scope": "UP",
                    "supersedes_rule_id": "BROKEN-CENTRAL-999",  # does not exist
                    "source_anchor": {
                        "source_url": "https://example.com",
                        "document_title": "Test",
                        "source_quote": "Test",
                        "notification_date": "2024-01-01",
                        "language": "en",
                    },
                    "confidence": 0.8,
                    "audit_status": "PENDING",
                    "parse_run_id": "RUN-TEST",
                    "version": "1.0.0",
                    "display_text": "Broken state rule",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "BROKEN.json").write_text(json.dumps(scheme_with_broken_chain))

            with pytest.raises(RuleBaseError):
                await load_rule_base(tmp_path, user_state="UP")


# ===========================================================================
# Group 5: load_relationship_matrix
# ===========================================================================

class TestLoadRelationshipMatrix:
    """load_relationship_matrix loads and validates relationship data."""

    async def test_load_relationship_matrix_returns_list(self) -> None:
        """Valid relationships.json must return a list of SchemeRelationship objects."""
        from src.schema import SchemeRelationship

        result = await load_relationship_matrix(FIXTURES_DIR / "relationships.json")

        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], SchemeRelationship)

    async def test_load_relationship_matrix_missing_file_raises_rule_base_error(self) -> None:
        """Missing relationships.json must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        with pytest.raises(RuleBaseError):
            await load_relationship_matrix(Path("/nonexistent/path/relationships.json"))

    async def test_load_relationship_matrix_malformed_json_raises_rule_base_error(self) -> None:
        """Malformed JSON in relationships file must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "relationships.json"
            bad_file.write_text("{invalid json {{{{")

            with pytest.raises(RuleBaseError):
                await load_relationship_matrix(bad_file)

    async def test_load_relationship_matrix_correct_relationship_types(self) -> None:
        """Each loaded relationship must have a valid relationship_type."""
        valid_types = {"PREREQUISITE", "MUTUAL_EXCLUSION", "COMPLEMENTARY", "OVERLAP"}

        result = await load_relationship_matrix(FIXTURES_DIR / "relationships.json")

        for rel in result:
            assert rel.relationship_type in valid_types


# ===========================================================================
# Group 6: load_ambiguity_map
# ===========================================================================

class TestLoadAmbiguityMap:
    """load_ambiguity_map loads and validates ambiguity flag data."""

    async def test_load_ambiguity_map_returns_list(self) -> None:
        """Valid ambiguity_map.json must return a list of AmbiguityFlag objects."""
        from src.schema import AmbiguityFlag

        result = await load_ambiguity_map(FIXTURES_DIR / "ambiguity_map.json")

        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], AmbiguityFlag)

    async def test_load_ambiguity_map_missing_file_raises_rule_base_error(self) -> None:
        """Missing ambiguity_map.json must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        with pytest.raises(RuleBaseError):
            await load_ambiguity_map(Path("/nonexistent/ambiguity_map.json"))

    async def test_load_ambiguity_map_severity_values_are_valid(self) -> None:
        """All loaded flags must have valid severity values."""
        from src.schema import AmbiguitySeverity

        result = await load_ambiguity_map(FIXTURES_DIR / "ambiguity_map.json")
        valid_severities = {s.value for s in AmbiguitySeverity}

        for flag in result:
            assert flag.severity.value in valid_severities
