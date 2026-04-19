#!/usr/bin/env python3
"""Post-processing enhancement script: upgrades parsed_schemes/ batch files using Gemini Flash 2.5.

What this does:
  1. Finds all eligibility.other rules that couldn't be regex-parsed (~11,188 rules)
  2. Classifies them with Gemini in batches of 20 (one API call per batch)
  3. Overwrites fields ONLY when Gemini confidence ≥ CONFIDENCE_THRESHOLD
  4. Also re-detects ambiguities using Gemini's full 30-type analysis
  5. Updates Ambiguity_Flags in each rule
  6. Writes upgraded batches back in-place
  7. Prints a token-cost report at the end

Token budget estimate (first run, no cache):
  11,188 other rules ÷ 20 per call = ~560 classify calls ≈ $0.10–$0.15
  Ambiguity detection on all 20,718 rules ÷ 20 = ~1,036 calls ≈ $0.15–$0.20
  Total: ~$0.25–$0.35 (out of $100 budget)
  Subsequent runs: $0.00 (everything cached)

Usage:
  python src/enhance_with_gemini.py                        # enhance all batches
  python src/enhance_with_gemini.py --batch 001            # single batch
  python src/enhance_with_gemini.py --dry-run              # show stats without writing
  python src/enhance_with_gemini.py --classify-only        # skip ambiguity detection
  python src/enhance_with_gemini.py --ambiguity-only       # skip rule classification
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import sys
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enhance_with_gemini")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
BATCHES_DIR = PROJECT_ROOT / "parsed_schemes"
CONFIDENCE_THRESHOLD = 0.60  # Only apply Gemini classification if confident enough

# Condition type mapping from Gemini field → matching engine condition_type
_FIELD_TO_CONDITION_TYPE: dict[str, str] = {
    "applicant.age": "age_range",
    "applicant.gender": "gender",
    "applicant.caste_category": "caste_category",
    "applicant.education_level": "education_level",
    "applicant.marital_status": "marital_status",
    "applicant.disability_status": "disability_status",
    "applicant.nationality": "nationality",
    "applicant.religion": "religion",
    "employment.occupation": "occupation",
    "employment.employment_status": "employment_status",
    "employment.is_income_tax_payer": "employment:income_tax_status",
    "household.income_annual": "income_ceiling",
    "household.bpl_status": "bpl_status",
    "household.family_size": "family_size",
    "household.is_ration_card_holder": "ration_card_status",
    "location.state": "domicile",
    "location.district": "district",
    "location.is_urban": "urban_rural",
    "assets.cultivable_land": "land_ownership",
    "assets.house_ownership": "house_ownership",
    "documents.aadhaar": "document:aadhaar",
    "documents.bank_account": "document:bank_account",
    "eligibility.other": "other",
}

# Severity mapping for ambiguity types (mirrors ambiguity_map.py)
_CRITICAL_TYPES = {9, 3, 20}
_HIGH_TYPES = {1, 6, 7, 10, 14, 16, 19, 23, 25, 28, 29}
_MEDIUM_TYPES = {4, 5, 8, 11, 12, 13, 15, 17, 21, 24, 26, 27, 30}

AMBIGUITY_TAXONOMY: dict[int, str] = {
    1: "Semantic Vagueness", 2: "Undefined Term", 3: "Conflicting Criteria",
    4: "Discretionary Clause", 5: "Temporal Ambiguity", 6: "Mutual Exclusion Conflict",
    7: "Portability Gap", 8: "Eligibility Threshold Overlap",
    9: "Prerequisite Chaining / Circular Dependency", 10: "Financial Threshold Flux",
    11: "Categorical Boundary Ambiguity", 12: "Documentation Requirement Ambiguity",
    13: "Benefit Duplication Risk", 14: "Administrative Boundary Conflict",
    15: "Implementation Gap", 16: "Targeting Inconsistency",
    17: "Appeal Mechanism Vagueness", 18: "Grievance Redressal Specificity",
    19: "Linguistic Translation Delta", 20: "Infrastructure Precondition",
    21: "Life-Event Transition Ambiguity", 22: "Household Definition Inconsistency",
    23: "Residency Requirement Vagueness", 24: "Income Computation Method Ambiguity",
    25: "Caste Certificate Jurisdiction Conflict", 26: "Gender Eligibility Gap",
    27: "Age Calculation Method Ambiguity", 28: "Land Record Jurisdiction Conflict",
    29: "Disability Certification Ambiguity", 30: "Aadhaar Linkage Requirement Gap",
}


def _severity_for_type(code: int) -> str:
    if code in _CRITICAL_TYPES:
        return "CRITICAL"
    if code in _HIGH_TYPES:
        return "HIGH"
    if code in _MEDIUM_TYPES:
        return "MEDIUM"
    return "LOW"


def _apply_classification(rule: dict, classification: dict) -> tuple[bool, str]:
    """Apply Gemini classification to a rule dict in-place.

    Returns (changed: bool, reason: str).
    Only applies if confidence ≥ CONFIDENCE_THRESHOLD and field is not already specific.
    """
    confidence = float(classification.get("confidence", 0))
    new_field = classification.get("field", "eligibility.other")
    is_procedural = classification.get("is_procedural", False)

    # Skip: already classified to a specific field
    current_field = rule.get("Field", "eligibility.other")
    if current_field != "eligibility.other":
        return False, "already classified"

    # Skip: low confidence
    if confidence < CONFIDENCE_THRESHOLD:
        return False, f"low confidence ({confidence:.2f})"

    # Skip: Gemini also returned eligibility.other for procedural rules
    if new_field == "eligibility.other" and not is_procedural:
        # Still update condition_text and confidence slightly
        new_condition = classification.get("condition_text")
        if new_condition and new_condition != rule.get("Condition"):
            rule["Condition"] = new_condition
            rule["Display_Text"] = new_condition
        return False, "Gemini kept as other"

    # Apply the structured classification
    rule["Field"] = new_field
    rule["Condition_Type"] = _FIELD_TO_CONDITION_TYPE.get(new_field, "other")
    rule["Operator"] = classification.get("operator") or rule.get("Operator", "EQ")

    val = classification.get("value")
    val_min = classification.get("value_min")
    val_max = classification.get("value_max")
    values = classification.get("values", [])

    if rule["Operator"] == "BETWEEN":
        rule["Value"] = None
        rule["Value_Min"] = val_min
        rule["Value_Max"] = val_max
    elif rule["Operator"] in ("IN", "NOT_IN"):
        rule["Value"] = None
        rule["Values"] = values if isinstance(values, list) else []
    else:
        rule["Value"] = val
        rule["Value_Min"] = None
        rule["Value_Max"] = None
        rule["Values"] = []

    condition_text = classification.get("condition_text")
    if condition_text:
        rule["Condition"] = condition_text
        rule["Display_Text"] = condition_text

    rule["Confidence"] = round(confidence, 3)
    rule.setdefault("Notes", "")
    rule["Notes"] = ((rule["Notes"] or "") + " [enhanced by Gemini]").strip()

    return True, f"classified as {new_field} (confidence {confidence:.2f})"


def _apply_ambiguity_flags(rule: dict, scheme_id: str, detection: dict) -> int:
    """Merge Gemini-detected ambiguity flags into rule's Ambiguity_Flags list.

    Returns count of new flags added.
    """
    detected_types = detection.get("detected_types", [])
    descriptions = detection.get("descriptions", {})

    if not detected_types:
        return 0

    existing = rule.setdefault("Ambiguity_Flags", [])
    # Collect already-present type codes to avoid duplicates
    existing_codes = {
        flag.get("ambiguity_type_code") for flag in existing if isinstance(flag, dict)
    }

    added = 0
    for code in detected_types:
        if not isinstance(code, int) or code not in AMBIGUITY_TAXONOMY:
            continue
        if code in existing_codes:
            continue

        desc_text = descriptions.get(str(code), f"{AMBIGUITY_TAXONOMY[code]} detected in rule text")
        flag = {
            "ambiguity_id": f"AMB-{uuid.uuid4().hex[:6].upper()}",
            "scheme_id": scheme_id,
            "rule_id": rule.get("Rule_ID"),
            "ambiguity_type_code": code,
            "ambiguity_type_name": AMBIGUITY_TAXONOMY[code],
            "description": desc_text,
            "severity": _severity_for_type(code),
            "resolution_status": "OPEN",
            "source": "gemini",
        }
        existing.append(flag)
        existing_codes.add(code)
        added += 1

    return added


# ---------------------------------------------------------------------------
# Main enhancement logic
# ---------------------------------------------------------------------------


def enhance_batch(
    batch_path: Path,
    enhancer: "GeminiEnhancer",  # type: ignore[name-defined]  # noqa: F821
    dry_run: bool = False,
    classify: bool = True,
    detect_ambiguity: bool = True,
) -> dict[str, int]:
    """Enhance one batch file. Returns stats dict."""
    data = json.loads(batch_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        logger.warning("Skipping %s — not a list-format batch", batch_path.name)
        return {}

    stats = {
        "schemes": len(data),
        "rules_total": 0,
        "rules_classified": 0,
        "rules_skipped_low_confidence": 0,
        "ambiguity_flags_added": 0,
    }

    # Collect all rules for ambiguity detection (all rules, not just other)
    all_rules_for_ambiguity: list[tuple[dict, dict, str]] = []  # (rule, scheme)
    other_rules: list[tuple[dict, dict]] = []  # (rule, scheme)

    for scheme in data:
        scheme_id = scheme.get("scheme_id", "UNKNOWN")
        for rule in scheme.get("rules", []):
            stats["rules_total"] += 1
            if rule.get("Field") == "eligibility.other":
                other_rules.append((rule, scheme))
            if detect_ambiguity:
                all_rules_for_ambiguity.append((rule, scheme, scheme_id))

    # --- Rule classification ---
    if classify and other_rules:
        logger.info(
            "  Classifying %d eligibility.other rules in %s...",
            len(other_rules),
            batch_path.name,
        )
        texts = [r.get("Source_Quote", r.get("Condition", "")) for r, _ in other_rules]
        classifications = enhancer.classify_rule_batch(texts)

        for (rule, _), classification in zip(other_rules, classifications):
            changed, reason = _apply_classification(rule, classification)
            if changed:
                stats["rules_classified"] += 1
            elif "low confidence" in reason:
                stats["rules_skipped_low_confidence"] += 1

    # --- Ambiguity detection ---
    if detect_ambiguity and all_rules_for_ambiguity:
        logger.info(
            "  Detecting ambiguities in %d rules in %s...",
            len(all_rules_for_ambiguity),
            batch_path.name,
        )
        texts = [
            r.get("Source_Quote", r.get("Condition", ""))
            for r, _, _ in all_rules_for_ambiguity
        ]
        detections = enhancer.detect_ambiguities_batch(texts)

        for (rule, _, scheme_id), detection in zip(all_rules_for_ambiguity, detections):
            added = _apply_ambiguity_flags(rule, scheme_id, detection)
            stats["ambiguity_flags_added"] += added

    if not dry_run:
        batch_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("  Saved %s", batch_path.name)

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    global CONFIDENCE_THRESHOLD  # may be overridden by --confidence arg
    parser = argparse.ArgumentParser(
        description="Enhance parsed scheme batches with Gemini Flash 2.5."
    )
    parser.add_argument(
        "--batch",
        metavar="NNN",
        help="Process only batch number NNN (e.g. 001). Default: all batches.",
    )
    parser.add_argument(
        "--from-batch",
        metavar="NNN",
        default=None,
        help="Resume from batch NNN (inclusive). Skips all earlier batches.",
    )
    parser.add_argument(
        "--to-batch",
        metavar="NNN",
        default=None,
        help="Stop after batch NNN (inclusive). Used with --from-batch for parallel workers.",
    )
    parser.add_argument(
        "--cache-suffix",
        metavar="SUFFIX",
        default="",
        help="Append SUFFIX to the cache filename so parallel workers don't collide (e.g. _w1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files.",
    )
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="Only classify eligibility.other rules; skip ambiguity detection.",
    )
    parser.add_argument(
        "--ambiguity-only",
        action="store_true",
        help="Only run ambiguity detection; skip rule classification.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=CONFIDENCE_THRESHOLD,
        help=f"Minimum Gemini confidence to apply classification (default: {CONFIDENCE_THRESHOLD}).",
    )
    args = parser.parse_args()

    # Update module-level threshold so _apply_classification uses the right value
    CONFIDENCE_THRESHOLD = args.confidence

    # Import here so module-level failures don't block --help
    try:
        from src.gemini_enhancer import GeminiEnhancer
    except ImportError:
        from gemini_enhancer import GeminiEnhancer  # type: ignore[import]

    logger.info("Initialising Gemini enhancer...")
    cache_path = f"parsed_schemes/.gemini_cache{args.cache_suffix}.json"
    try:
        enhancer = GeminiEnhancer(cache_path=cache_path)
    except ValueError as exc:
        logger.error("Failed to initialise Gemini: %s", exc)
        sys.exit(1)

    logger.info("Cache: %s", enhancer.cache_stats())

    # Find batch files
    if args.batch:
        pattern = str(BATCHES_DIR / f"kaggle_schemes_batch_{args.batch.zfill(3)}.json")
    else:
        pattern = str(BATCHES_DIR / "kaggle_schemes_batch_*.json")

    batch_files = sorted(glob.glob(pattern))
    if not batch_files:
        logger.error("No batch files matched pattern: %s", pattern)
        sys.exit(1)

    # Resume support: skip batches before --from-batch
    if args.from_batch:
        cutoff = f"kaggle_schemes_batch_{args.from_batch.zfill(3)}.json"
        batch_files = [b for b in batch_files if Path(b).name >= cutoff]
        if not batch_files:
            logger.error("No batches at or after %s", cutoff)
            sys.exit(1)
        logger.info("Resuming from %s (%d batches remaining)", cutoff, len(batch_files))

    # Range limit: drop batches after --to-batch
    if args.to_batch:
        ceiling = f"kaggle_schemes_batch_{args.to_batch.zfill(3)}.json"
        batch_files = [b for b in batch_files if Path(b).name <= ceiling]
        if not batch_files:
            logger.error("No batches at or before %s", ceiling)
            sys.exit(1)
        logger.info("Will stop after %s (%d batches in range)", ceiling, len(batch_files))

    logger.info(
        "Processing %d batch file(s)%s...",
        len(batch_files),
        " (DRY RUN)" if args.dry_run else "",
    )

    total_stats: dict[str, int] = {}
    do_classify = not args.ambiguity_only
    do_ambiguity = not args.classify_only

    for batch_path in batch_files:
        logger.info("Processing %s", Path(batch_path).name)
        try:
            stats = enhance_batch(
                Path(batch_path),
                enhancer,
                dry_run=args.dry_run,
                classify=do_classify,
                detect_ambiguity=do_ambiguity,
            )
            for k, v in stats.items():
                total_stats[k] = total_stats.get(k, 0) + v
        except Exception as exc:
            logger.error("Failed on %s: %s", batch_path, exc, exc_info=True)

    # Summary
    print("\n" + "=" * 60)
    print("ENHANCEMENT COMPLETE")
    print("=" * 60)
    for k, v in sorted(total_stats.items()):
        print(f"  {k}: {v:,}")
    print()
    print(enhancer.cost_report())
    print(enhancer.cache_stats())
    print("=" * 60)


if __name__ == "__main__":
    main()
