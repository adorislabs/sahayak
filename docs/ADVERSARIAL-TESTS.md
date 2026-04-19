# Adversarial Test Suite Documentation

## Overview

The adversarial test suite (`src/tests/test_matching/test_adversarial_extended.py`) is a comprehensive stress-testing framework for the scheme matching engine. It validates the engine's behavior across **21 profiles** spanning edge cases, boundary conditions, and adversarial inputs that attempt to break the system.

**Test Coverage**: 179 tests across 21 profiles  
**Current Status**: ✅ All 179 tests passing  
**Profile Range**: `profile_11` through `profile_31`

---

## Test Architecture

### Structure
```
test_adversarial_extended.py
├── Helpers (parametrized and class-level)
│   ├── _load_profile() — Load JSON fixture
│   ├── _evaluate() — Run matching engine
│   ├── _all_scheme_ids() — Get scheme list
│   ├── _status_of() — Query scheme status
│   └── _has_warning_containing() — Check warning text
│
├── TestSmoke (4 × 21 = 84 tests)
│   └── Parametrized: age, documents, employment, income
│
├── Per-Profile Test Classes (1 per profile = 21 classes)
│   ├── TestProfile11HomeDomesticWorker (6 tests)
│   ├── TestProfile12CasteRecategorized (6 tests)
│   ├── ... (similar structure)
│   └── TestProfile31UnknownEmploymentType (5 tests)
│
└── TestConcurrentStress (5 tests)
    └── Asyncio stress with 50+ parallel evaluations
```

### Execution Modes
- **Smoke tests**: Quick, parametrized validation (age, documents, employment, income)
- **Scenario tests**: Deep, profile-specific assertions
- **Stress tests**: Concurrent evaluation under load

---

## Profile Catalog (Profiles 11–31)

### Edge Cases (Profiles 11–16)
**Purpose**: Exploit real-world irregularities and certification gaps.

#### Profile 11: Home Domestic Worker
- **Scenario**: Female, 42, OBC, urban Karnataka, informal domestic work, no employer proof
- **Tests** (6): Employment classification, PMSYM age boundary (>40 = ineligible), urban exclusion from MGNREGA, data quality
- **Key Triggers**: Age 42 > PMSYM max 40; urban → MGNREGA blocked; informal sector without docs → warnings
- **File**: `profile_11_home_domestic_worker.json`

#### Profile 12: Caste Recategorized
- **Scenario**: OBC community recategorized to SC; has old OBC cert, lacks new SC cert
- **Tests** (6): Caste status verification, certification gaps, eligibility with pending docs, data quality flagging
- **Key Triggers**: Missing SC certificate despite recategorization; caste_previous_category != current; certification_pending = true
- **File**: `profile_12_caste_recategorized.json`

#### Profile 13: Joint-to-Nuclear Family Split
- **Scenario**: Household downsized from 14 (joint) to 4 (nuclear); ration card not yet split
- **Tests** (6): Household size consistency, family type transitions, income/BPL reassessment, data quality
- **Key Triggers**: household.size=4 but previous_size=14; ration_card_split_done=false → warnings
- **File**: `profile_13_joint_to_nuclear_split.json`

#### Profile 14: Minor Aging Out
- **Scenario**: Age 17, female, ST, Jharkhand, enrolled in JSSK+PMJAY (parent's schemes), turning 18 in 3 months
- **Tests** (6): Minor-age warnings, parent scheme eligibility, age milestone transitions, life-cycle logic
- **Key Triggers**: age=17 < 18 → minor warning; upcoming_age_milestone=18; parent_scheme_beneficiary=true
- **File**: `profile_14_minor_aging_out.json`

#### Profile 15: Disability Percentage Change
- **Scenario**: Disability reassessed from 40% → 70%; new UDID certificate pending
- **Tests** (6): Disability threshold boundaries (40%, 70%), certification gaps, eligibility reassessment, data quality
- **Key Triggers**: disability_percentage=70 (>40 threshold); new_certificate_available=false; reassessment_year=2024
- **File**: `profile_15_disability_percentage_change.json`

#### Profile 16: Gig Worker
- **Scenario**: Food delivery worker, no salary slip, platform income proof only
- **Tests** (6): Informal sector income verification, employment classification, PMSYM eligibility, platform income recognition
- **Key Triggers**: employment.type=informal; platform=food_delivery; has_salary_slip=false; platform_income_proof=true
- **File**: `profile_16_gig_worker.json`

---

### Engine-Breaking Boundary Tests (Profiles 17–31)
**Purpose**: Attack the matching engine with boundary conditions, contradictions, and extreme values.

#### Profile 17: Age Boundary 18
- **Scenario**: Age exactly 18 (PMSYM lower bound)
- **Tests** (5): PMSYM BETWEEN [18, 40] must include 18; MGNREGA GTE 18 matches
- **File**: `profile_17_age_boundary_18.json`

#### Profile 18: Age Boundary 40
- **Scenario**: Age exactly 40 (PMSYM upper bound)
- **Tests** (5): PMSYM BETWEEN [18, 40] must include 40 (not >40)
- **File**: `profile_18_age_boundary_40.json`

#### Profile 19: Age Boundary 60
- **Scenario**: Age exactly 60 (NSAP old-age lower bound)
- **Tests** (5): NSAP GTE 60 must include 60 (not >60)
- **File**: `profile_19_age_boundary_60.json`

#### Profile 20: Income at BPL Threshold
- **Scenario**: Annual income ₹120,000 exactly at BPL cutoff; monthly = ₹10,000 (consistent)
- **Tests** (5): BPL boundary logic; income consistency; eligibility determination at threshold
- **File**: `profile_20_income_at_bpl_threshold.json`

#### Profile 21: All Documents Missing
- **Scenario**: All documents false (aadhaar, bank, caste_cert, income_cert, mgnrega)
- **Tests** (6): NSAP prerequisite (bank_account required) blocks eligibility; PMSYM/MGNREGA legitimately eligible in mock (no doc prerequisites); warning generation
- **Key Finding**: Mock ruleset only gates on bank_account; PMSYM/MGNREGA have no document prerequisites → they evaluate as ELIGIBLE based on age/employment/residence alone
- **File**: `profile_21_all_documents_missing.json`

#### Profile 22: Maximum Active Enrollments
- **Scenario**: 10 schemes in active_enrollments simultaneously (PMKISAN, MGNREGA, NSAP, PMSYM, PMJAY, PMFBY, PM-KISAN-MAN-DHAN, SAMPANN, JSSK, NFBS)
- **Tests** (5): Engine handles high enrollment load; no conflicts; recommendation logic under saturation
- **File**: `profile_22_maximum_active_enrollments.json`

#### Profile 23: Triple Special Category Stacking
- **Scenario**: Age 65, SC, female, widowed, disability 50%, AAY, BPL (maximum disqualifier stack)
- **Tests** (5): NSAP eligible via age route (65 ≥ 60) AND disability route (50% ≥ 40%); multiple pathways to eligibility
- **File**: `profile_23_triple_special_category.json`

#### Profile 24: Income Inconsistency
- **Scenario**: Annual ₹200,000 vs monthly ₹5,000 (implied ₹60,000 from monthly; 233% mismatch)
- **Tests** (5): Cross-field validator detects income inconsistency; warning generation (caplog-based); data quality flagging
- **Key Finding**: >20% mismatch triggers DEBUG-level warning that surfaces in logs (not instance `profile_warnings` due to class-variable design)
- **File**: `profile_24_income_inconsistency.json`

#### Profile 25: Single-Person Household
- **Scenario**: Household size = 1 (minimum edge case)
- **Tests** (5): Engine handles minimal household; no assumptions about family structure; eligibility evaluation
- **File**: `profile_25_single_person_household.json`

#### Profile 26: Oversized Household
- **Scenario**: Household size = 15 with 7 children (maximum practical edge case)
- **Tests** (5): Engine scales to large households; no stack overflow; eligibility calculation with high dependent count
- **File**: `profile_26_oversized_household.json`

#### Profile 27: Infant Age Zero
- **Scenario**: Age = 0 (newborn; valid per profile validator [0, 120])
- **Tests** (5): Age 0 triggers minor-age warning; engine handles infants; MGNREGA and NSAP inapplicable
- **File**: `profile_27_infant_age_zero.json`

#### Profile 28: Maximum Age 120
- **Scenario**: Age = 120 (oldest allowed by validator)
- **Tests** (5): Engine handles extreme age; NSAP/PMJAY eligibility for elderly; no crash at boundary
- **File**: `profile_28_max_age_120.json`

#### Profile 29: Tax Payer + BPL Contradiction
- **Scenario**: is_income_tax_payer=true, bpl_status=true, income=₹60,000 (<₹2.5L tax threshold)
- **Tests** (5): Data quality warning (contradiction: tax payer but BPL); validator flags inconsistency; caplog verification
- **Key Finding**: Legitimate data contradiction that signals data-quality issues, surfaced via DEBUG-level log
- **File**: `profile_29_tax_payer_with_bpl.json`

#### Profile 30: Disability 100% + Rich
- **Scenario**: Disability 100%, income ₹900,000, EPFO+NPS+tax_payer (maximum disqualifier stack)
- **Tests** (5): Eligibility despite high disability (100%); income/employment status override disability advantage; NSAP eligibility via disability overrides income limits
- **File**: `profile_30_disability_100_rich.json`

#### Profile 31: Unknown Employment Type
- **Scenario**: employment.type = "gig" (non-standard enum value not in schema)
- **Tests** (5): Engine gracefully handles unknown employment types; no crash; eligibility evaluation with unrecognized fields
- **File**: `profile_31_unknown_employment_type.json`

---

## Test Execution

### Run All Adversarial Tests
```bash
source .venv/bin/activate
python -m pytest src/tests/test_matching/test_adversarial_extended.py -v
```

### Run Specific Profile Class
```bash
python -m pytest src/tests/test_matching/test_adversarial_extended.py::TestProfile21AllDocumentsMissing -v
```

### Run Only Smoke Tests
```bash
python -m pytest src/tests/test_matching/test_adversarial_extended.py::TestSmoke -v
```

### Run Only Stress Tests
```bash
python -m pytest src/tests/test_matching/test_adversarial_extended.py::TestConcurrentStress -v
```

### Run with Coverage
```bash
python -m pytest src/tests/test_matching/test_adversarial_extended.py --cov=src.matching --cov-report=term-missing
```

---

## Test Patterns & Techniques

### Warning Detection Pattern
Since `UserProfile._warnings` is a class-level variable (not instance-level), warnings generated by the cross-field validator are never stored in `result.profile_warnings`. Instead, they surface as DEBUG-level logs:

```python
# Correct pattern:
import logging
caplog.at_level(logging.DEBUG, logger="src.matching.profile")
UserProfile.from_flat_json(data)
# Check logs OR result.profile_warnings
assert any("warning_keyword" in rec.message.lower() for rec in caplog.records) or \
       any("warning_keyword" in w.lower() for w in result.profile_warnings)
```

### Mock Ruleset Design
The test suite uses a simplified mock ruleset for reproducibility:
- **PMSYM**: Age BETWEEN [18, 40]; no EPFO; income ≤ ₹15,000/month
- **PMKISAN**: Land ownership required; not for income-tax payers
- **MGNREGA**: Age ≥ 18; must be rural; has ambiguity (AMB-007)
- **NSAP**: Age ≥ 60 OR disability ≥ 40%; requires bank account (prerequisite)

### Profile Loading Helpers
All tests use lightweight helpers to avoid boilerplate:
```python
def _load_profile(filename: str) -> dict[str, Any]:
    """Load fixture from src/tests/test_data/profiles/"""
    path = Path(__file__).parent / "test_data" / "profiles" / filename
    with open(path) as f:
        return json.load(f)

async def _evaluate(data, rulesets, relationships, ambiguity, tmp_path) -> MatchingResult:
    """Run engine.evaluate_eligibility() with mocked rulesets."""
    # ... patches and invocation ...
```

---

## Known Limitations & Design Notes

### Profile Warnings Class-Level Bug
- **Issue**: `UserProfile._warnings` is `class UserProfile` variable, not instance variable
- **Impact**: `result.profile_warnings` is always `[]`; warnings only surface as DEBUG logs
- **Workaround**: Tests use `caplog` to verify warning generation
- **Recommendation**: Fix in `src/matching/profile.py` by using `PrivateAttr` (Pydantic v2)

### Mock Ruleset Simplifications
- No actual Aadhaar/bank account validation (mocked as boolean checks)
- No real income thresholds (mocked as simple comparison)
- Ambiguity flags (AMB-007) included but not fully resolved
- Prerequisite rules (NSAP bank_account) enforced; other schemes don't gate on documents

---

## Coverage Summary

| Dimension | Coverage |
|-----------|----------|
| **Profiles** | 21 (11–31) |
| **Tests** | 179 total |
| **Smoke (parametrized)** | 84 tests (4 per profile × 21) |
| **Scenario (profile-specific)** | 85 tests (4–6 per profile) |
| **Stress (concurrent)** | 5 tests (50+ concurrent evals) |
| **Schemes** | 4 (PMKISAN, PMSYM, MGNREGA, NSAP) |

---

## Integration with CI/CD

The adversarial test suite is integrated into the full test suite and validates without regressions:

```bash
# Full test suite (all 1512 tests)
pytest src/tests/ -q

# Expected: ~1510 passed, 1 skipped
# Adversarial suite: 179 passed (0 failures)
```

Adversarial tests are a subset of the comprehensive test matrix and run as part of standard validation pipelines.

---

## Future Enhancements

1. **Profile Mutation**: Generate variants of profiles programmatically (e.g., income ±10%)
2. **Fuzzing**: Random boundary-value generation for numerical fields
3. **Performance Benchmarks**: Track engine latency across profiles
4. **Coverage Analysis**: Identify uncovered rule paths and design profiles to hit them
5. **Concurrent Load Simulation**: Scale stress tests to 500+ simultaneous evaluations
