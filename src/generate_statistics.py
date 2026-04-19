"""
Detailed Ambiguity Analysis Report Generator
"""

import json
import os
import glob
from collections import defaultdict
from pathlib import Path

def generate_ambiguity_analysis(output_dir):
    """Generate detailed ambiguity analysis."""
    batch_files = sorted(glob.glob(os.path.join(output_dir, "kaggle_schemes_batch_*.json")))
    
    # Collect all ambiguities
    ambiguity_distribution = defaultdict(list)
    scheme_ambiguities = defaultdict(list)
    all_ambiguities = []
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch_data = json.load(f)
        
        for scheme in batch_data:
            for rule in scheme.get("rules", []):
                for amb_flag in rule.get("Ambiguity_Flags", []):
                    ambiguity_distribution[amb_flag].append({
                        "scheme_id": scheme.get("scheme_id"),
                        "rule_id": rule.get("Rule_ID"),
                        "source_quote": rule.get("Source_Quote", "")
                    })
                    
                    scheme_ambiguities[scheme.get("scheme_id")].append(amb_flag)
    
    # Generate report
    report = {
        "metadata": {
            "total_ambiguities": len(ambiguity_distribution),
            "total_schemes_with_ambiguities": len(scheme_ambiguities),
            "generated": "2026-04-17"
        },
        "ambiguity_types": {},
        "top_ambiguities": []
    }
    
    # Count by type
    ambiguity_type_counts = defaultdict(int)
    for amb_id, occurrences in ambiguity_distribution.items():
        # Extract type code from ID
        parts = amb_id.split('-')
        if len(parts) >= 3:
            try:
                type_code = int(parts[2])
                ambiguity_type_counts[type_code] += len(occurrences)
            except:
                pass
    
    # Build report
    ambiguity_types_map = {
        1: "Vague Threshold",
        2: "Overlapping Categories",
        3: "Proxy Measure Conflict",
        4: "Discretionary Clauses",
        5: "Temporal Ambiguity",
        6: "Tenure Ambiguity",
        7: "Critical Data Gap",
        8: "Geographic Scope Conflict",
        9: "Account Type Ambiguity",
        10: "State Variation",
        11: "Classification Overlap",
        12: "Aggregation Ambiguity",
        13: "Compound Qualifier",
        14: "Self-Certification Risk",
        15: "Currency/Unit Mismatch",
        16: "Residency Duration",
        17: "Exclusion List Incomplete",
        18: "Benefit Cap Ambiguity",
        19: "Family vs Individual",
        20: "Double Negation",
        21: "Conditional Prerequisite",
        22: "Retroactive Eligibility",
        23: "Multiple Scheme Interaction",
        24: "Numeric Range Open-ended",
        25: "Missing Operator",
        26: "Gender Ambiguity",
        27: "Document Not Defined",
        28: "Age Boundary Edge Case",
        29: "Category Not Standardized",
        30: "Benefit Type Ambiguity",
    }
    
    for type_code in sorted(ambiguity_type_counts.keys()):
        count = ambiguity_type_counts[type_code]
        type_name = ambiguity_types_map.get(type_code, "Unknown")
        report["ambiguity_types"][f"{type_code:02d}_{type_name}"] = count
    
    # Top ambiguities
    sorted_ambs = sorted(ambiguity_distribution.items(), key=lambda x: len(x[1]), reverse=True)
    for amb_id, occurrences in sorted_ambs[:20]:
        report["top_ambiguities"].append({
            "id": amb_id,
            "occurrences": len(occurrences),
            "schemes_affected": len(set(o["scheme_id"] for o in occurrences))
        })
    
    return report


def generate_statistics_report(output_dir):
    """Generate comprehensive statistics."""
    batch_files = sorted(glob.glob(os.path.join(output_dir, "kaggle_schemes_batch_*.json")))
    
    stats = {
        "dataset": {
            "total_schemes": 0,
            "total_rules": 0,
            "batches": 0,
        },
        "by_rule_type": defaultdict(int),
        "by_condition_type": defaultdict(int),
        "by_operator": defaultdict(int),
        "by_confidence_band": defaultdict(int),
        "by_state": defaultdict(int),
        "review_flagged": 0,
        "average_rules_per_scheme": 0,
        "average_confidence": 0,
    }
    
    total_confidence = 0
    rule_count = 0
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch_data = json.load(f)
        
        stats["dataset"]["total_schemes"] += len(batch_data)
        stats["dataset"]["batches"] += 1
        
        for scheme in batch_data:
            # State scope
            state = scheme.get("state_scope", "central")
            stats["by_state"][state] += 1
            
            # Review flag
            if scheme.get("review_queue", {}).get("flagged"):
                stats["review_flagged"] += 1
            
            for rule in scheme.get("rules", []):
                stats["dataset"]["total_rules"] += 1
                rule_count += 1
                
                # Rule type
                rule_type = rule.get("Rule_Type", "unknown")
                stats["by_rule_type"][rule_type] += 1
                
                # Condition type
                condition_type = rule.get("Condition_Type", "unknown")
                stats["by_condition_type"][condition_type] += 1
                
                # Operator
                operator = rule.get("Operator", "unknown")
                stats["by_operator"][operator] += 1
                
                # Confidence band
                confidence = rule.get("Confidence", 0.5)
                if confidence >= 0.90:
                    stats["by_confidence_band"]["0.90-1.00"] += 1
                elif confidence >= 0.80:
                    stats["by_confidence_band"]["0.80-0.89"] += 1
                elif confidence >= 0.70:
                    stats["by_confidence_band"]["0.70-0.79"] += 1
                elif confidence >= 0.60:
                    stats["by_confidence_band"]["0.60-0.69"] += 1
                else:
                    stats["by_confidence_band"]["<0.60"] += 1
                
                total_confidence += confidence
    
    if rule_count > 0:
        stats["average_rules_per_scheme"] = stats["dataset"]["total_rules"] / stats["dataset"]["total_schemes"]
        stats["average_confidence"] = total_confidence / rule_count
    
    return stats


def print_statistics_summary(stats):
    """Print formatted statistics summary."""
    print("\n" + "=" * 100)
    print("DETAILED STATISTICS REPORT")
    print("=" * 100)
    
    print(f"\nDATASET OVERVIEW")
    print("-" * 100)
    print(f"Total Schemes:           {stats['dataset']['total_schemes']}")
    print(f"Total Rules:             {stats['dataset']['total_rules']}")
    print(f"Total Batches:           {stats['dataset']['batches']}")
    print(f"Avg Rules per Scheme:    {stats['average_rules_per_scheme']:.2f}")
    print(f"Avg Confidence Score:    {stats['average_confidence']:.3f}")
    print(f"Schemes Flagged:         {stats['review_flagged']}")
    
    print(f"\nRULE TYPES")
    print("-" * 100)
    for rule_type in ["eligibility", "disqualifying", "prerequisite"]:
        count = stats['by_rule_type'].get(rule_type, 0)
        pct = (count / stats['dataset']['total_rules'] * 100) if stats['dataset']['total_rules'] > 0 else 0
        print(f"  {rule_type:20} {count:>8}  ({pct:5.1f}%)")
    
    print(f"\nCONFIDENCE DISTRIBUTION")
    print("-" * 100)
    for band in ["0.90-1.00", "0.80-0.89", "0.70-0.79", "0.60-0.69", "<0.60"]:
        count = stats['by_confidence_band'].get(band, 0)
        pct = (count / stats['dataset']['total_rules'] * 100) if stats['dataset']['total_rules'] > 0 else 0
        print(f"  {band:12} {count:>8}  ({pct:5.1f}%)")
    
    print(f"\nOPERATORS USED (Top 10)")
    print("-" * 100)
    sorted_ops = sorted(stats['by_operator'].items(), key=lambda x: x[1], reverse=True)
    for op, count in sorted_ops[:10]:
        pct = (count / stats['dataset']['total_rules'] * 100) if stats['dataset']['total_rules'] > 0 else 0
        print(f"  {op:15} {count:>8}  ({pct:5.1f}%)")
    
    print(f"\nSTATE DISTRIBUTION (Top 10)")
    print("-" * 100)
    sorted_states = sorted(stats['by_state'].items(), key=lambda x: x[1], reverse=True)
    for state, count in sorted_states[:10]:
        pct = (count / stats['dataset']['total_schemes'] * 100) if stats['dataset']['total_schemes'] > 0 else 0
        print(f"  {state:20} {count:>8}  ({pct:5.1f}%)")
    
    print(f"\nCONDITION TYPES (Top 15)")
    print("-" * 100)
    sorted_conds = sorted(stats['by_condition_type'].items(), key=lambda x: x[1], reverse=True)
    for cond, count in sorted_conds[:15]:
        pct = (count / stats['dataset']['total_rules'] * 100) if stats['dataset']['total_rules'] > 0 else 0
        print(f"  {cond:30} {count:>8}  ({pct:5.1f}%)")


if __name__ == "__main__":
    output_dir = "/Users/dhruv/Downloads/projects/cbc/parsed_schemes"
    
    # Generate statistics
    stats = generate_statistics_report(output_dir)
    print_statistics_summary(stats)
    
    # Save statistics
    stats_path = os.path.join(output_dir, "STATISTICS.json")
    with open(stats_path, 'w') as f:
        # Convert defaultdicts to regular dicts for JSON serialization
        clean_stats = {
            "dataset": dict(stats["dataset"]),
            "by_rule_type": dict(stats["by_rule_type"]),
            "by_condition_type": dict(stats["by_condition_type"]),
            "by_operator": dict(stats["by_operator"]),
            "by_confidence_band": dict(stats["by_confidence_band"]),
            "by_state": dict(stats["by_state"]),
            "review_flagged": stats["review_flagged"],
            "average_rules_per_scheme": stats["average_rules_per_scheme"],
            "average_confidence": stats["average_confidence"],
        }
        json.dump(clean_stats, f, indent=2)
    print(f"\nStatistics saved to: {stats_path}")
