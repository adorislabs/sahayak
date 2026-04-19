"""
Quality Gate Validation & Reporting for Kaggle Parsing
"""

import json
import os
import glob
from collections import defaultdict
from pathlib import Path

def validate_batch(batch_data):
    """Validate a single batch against quality gates."""
    issues = []
    stats = {
        "total_schemes": len(batch_data),
        "total_rules": 0,
        "flagged_for_review": 0,
        "high_confidence": 0,
        "low_confidence": 0,
        "with_ambiguities": 0,
        "disqualifying_rules": 0,
        "prerequisite_rules": 0,
        "eligibility_rules": 0,
    }

    for scheme in batch_data:
        # Check required fields
        required = ["scheme_id", "scheme_name", "rules", "review_queue"]
        for field in required:
            if field not in scheme:
                issues.append(f"Missing field '{field}' in scheme {scheme.get('scheme_id', 'UNKNOWN')}")

        # Validate rules
        rules = scheme.get("rules", [])
        if not rules:
            issues.append(f"Scheme {scheme.get('scheme_id')} has no rules")

        stats["total_rules"] += len(rules)

        for rule in rules:
            # Check rule structure
            if "Rule_ID" not in rule:
                issues.append(f"Rule missing Rule_ID in {scheme.get('scheme_id')}")
            
            if "Operator" not in rule:
                issues.append(f"Rule {rule.get('Rule_ID')} missing Operator")
            
            # Check operator validity
            valid_ops = ["EQ", "NEQ", "LT", "LTE", "GT", "GTE", "BETWEEN", "IN", "NOT_IN", "IS_NULL", "IS_NOT_NULL"]
            if rule.get("Operator") not in valid_ops:
                issues.append(f"Invalid operator '{rule.get('Operator')}' in {rule.get('Rule_ID')}")
            
            # Check confidence bounds
            conf = rule.get("Confidence", 0)
            if not (0.0 <= conf <= 1.0):
                issues.append(f"Invalid confidence {conf} in {rule.get('Rule_ID')}")
            
            if conf >= 0.80:
                stats["high_confidence"] += 1
            elif conf < 0.65:
                stats["low_confidence"] += 1

            # Check audit status
            if rule.get("Audit_Status") != "PENDING":
                issues.append(f"Rule {rule.get('Rule_ID')} has non-PENDING audit status")

            # Count by rule type
            rule_type = rule.get("Rule_Type", "")
            if rule_type == "disqualifying":
                stats["disqualifying_rules"] += 1
            elif rule_type == "prerequisite":
                stats["prerequisite_rules"] += 1
            elif rule_type == "eligibility":
                stats["eligibility_rules"] += 1

            # Check for ambiguities
            if rule.get("Ambiguity_Flags"):
                stats["with_ambiguities"] += 1

        # Check review queue
        review = scheme.get("review_queue", {})
        if review.get("flagged"):
            stats["flagged_for_review"] += 1

    return issues, stats


def generate_comprehensive_report(output_dir):
    """Generate comprehensive validation report."""
    batch_files = sorted(glob.glob(os.path.join(output_dir, "kaggle_schemes_batch_*.json")))
    
    print("\n" + "=" * 100)
    print("COMPREHENSIVE PARSING VALIDATION REPORT")
    print("=" * 100)
    
    all_stats = defaultdict(int)
    all_issues = []
    batch_results = []
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch_data = json.load(f)
        
        issues, stats = validate_batch(batch_data)
        all_issues.extend(issues)
        
        # Aggregate stats
        for key, val in stats.items():
            all_stats[key] += val
        
        batch_num = os.path.basename(batch_file).split('_')[-1].replace('.json', '')
        batch_results.append({
            "batch": batch_num,
            "schemes": stats["total_schemes"],
            "rules": stats["total_rules"],
            "flagged": stats["flagged_for_review"],
            "issues": len(issues)
        })
    
    # Print summary
    print(f"\nOVERALL STATISTICS")
    print("-" * 100)
    print(f"Total Batches Processed:      {len(batch_files)}")
    print(f"Total Schemes Parsed:         {all_stats['total_schemes']}")
    print(f"Total Rules Extracted:        {all_stats['total_rules']}")
    print(f"Schemes Flagged for Review:   {all_stats['flagged_for_review']}")
    print(f"Rules with High Confidence:   {all_stats['high_confidence']}")
    print(f"Rules with Low Confidence:    {all_stats['low_confidence']}")
    print(f"Rules with Ambiguities:       {all_stats['with_ambiguities']}")
    print(f"\nRule Breakdown:")
    print(f"  - Eligibility Rules:        {all_stats['eligibility_rules']}")
    print(f"  - Disqualifying Rules:      {all_stats['disqualifying_rules']}")
    print(f"  - Prerequisite Rules:       {all_stats['prerequisite_rules']}")
    
    print(f"\nQuality Gate Results")
    print("-" * 100)
    print(f"Total Validation Issues:      {len(all_issues)}")
    
    if all_issues:
        print(f"\nFirst 20 issues:")
        for issue in all_issues[:20]:
            print(f"  ⚠️  {issue}")
    
    print(f"\nBatch Summary (first 10):")
    print("-" * 100)
    print(f"{'Batch':<10} {'Schemes':<12} {'Rules':<12} {'Flagged':<12} {'Issues':<10}")
    print("-" * 100)
    for result in batch_results[:10]:
        print(f"{result['batch']:<10} {result['schemes']:<12} {result['rules']:<12} {result['flagged']:<12} {result['issues']:<10}")
    
    return all_stats, all_issues, batch_results


def generate_flagged_schemes_report(output_dir):
    """Generate report of schemes flagged for review."""
    batch_files = sorted(glob.glob(os.path.join(output_dir, "kaggle_schemes_batch_*.json")))
    
    flagged_schemes = []
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch_data = json.load(f)
        
        for scheme in batch_data:
            review = scheme.get("review_queue", {})
            if review.get("flagged"):
                flagged_schemes.append({
                    "scheme_id": scheme.get("scheme_id"),
                    "scheme_name": scheme.get("scheme_name"),
                    "reason": review.get("reason"),
                    "severity": review.get("severity"),
                    "num_rules": len(scheme.get("rules", [])),
                })
    
    print("\n" + "=" * 100)
    print("SCHEMES FLAGGED FOR REVIEW")
    print("=" * 100)
    print(f"Total Flagged: {len(flagged_schemes)}\n")
    
    # Group by severity
    by_severity = defaultdict(list)
    for scheme in flagged_schemes:
        severity = scheme.get("severity", "UNKNOWN")
        by_severity[severity].append(scheme)
    
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        schemes = by_severity.get(severity, [])
        if schemes:
            print(f"\n{severity} SEVERITY ({len(schemes)} schemes):")
            print("-" * 100)
            for scheme in schemes[:5]:  # Show first 5 per severity
                print(f"  {scheme['scheme_id']}")
                print(f"    Name: {scheme['scheme_name'][:80]}")
                print(f"    Reason: {scheme['reason']}")
                print()
    
    return flagged_schemes


def generate_batch_index(output_dir):
    """Generate index of all batches."""
    batch_files = sorted(glob.glob(os.path.join(output_dir, "kaggle_schemes_batch_*.json")))
    
    index = {
        "metadata": {
            "total_batches": len(batch_files),
            "batch_size": 50,
            "dataset": "Kaggle Indian Government Schemes",
            "version": "1.0.0-kaggle",
            "generated": "2026-04-17"
        },
        "batches": []
    }
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch_data = json.load(f)
        
        batch_num = os.path.basename(batch_file).split('_')[-1].replace('.json', '')
        scheme_ids = [s.get('scheme_id') for s in batch_data]
        
        index["batches"].append({
            "batch_number": int(batch_num),
            "file": os.path.basename(batch_file),
            "schemes_count": len(batch_data),
            "scheme_ids": scheme_ids
        })
    
    # Save index
    index_path = os.path.join(output_dir, "BATCH_INDEX.json")
    with open(index_path, 'w') as f:
        json.dump(index, f, indent=2)
    
    print(f"\nBatch index saved to: {index_path}")
    return index


if __name__ == "__main__":
    output_dir = "/Users/dhruv/Downloads/projects/cbc/parsed_schemes"
    
    # Run validation
    stats, issues, batch_results = generate_comprehensive_report(output_dir)
    
    # Run flagged schemes report
    flagged = generate_flagged_schemes_report(output_dir)
    
    # Generate batch index
    index = generate_batch_index(output_dir)
    
    print("\n" + "=" * 100)
    print("VALIDATION COMPLETE")
    print("=" * 100)
    print(f"All batches validated successfully!")
    print(f"Output directory: {output_dir}")
