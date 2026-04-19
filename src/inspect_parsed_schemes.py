#!/usr/bin/env python3
"""
Kaggle Schemes Parsing - Quick Inspection & Lookup Tool
Usage: python inspect_parsed_schemes.py [--batch N] [--scheme SLUG] [--flagged]
"""

import json
import sys
import glob
import os
from pathlib import Path

def inspect_scheme(scheme_id, batches_dir):
    """Inspect a specific scheme by ID."""
    batch_files = sorted(glob.glob(os.path.join(batches_dir, "kaggle_schemes_batch_*.json")))
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch = json.load(f)
        
        for scheme in batch:
            if scheme.get("scheme_id") == scheme_id:
                print("\n" + "=" * 100)
                print(f"SCHEME: {scheme.get('scheme_name')}")
                print("=" * 100)
                print(f"ID:              {scheme.get('scheme_id')}")
                print(f"Short Name:      {scheme.get('short_name')}")
                print(f"State Scope:     {scheme.get('state_scope')}")
                print(f"Data Tier:       {scheme.get('data_source_tier')}")
                print(f"Parse Run:       {scheme.get('parse_run_id')}")
                print(f"Status:          {scheme.get('status')}")
                print(f"Total Rules:     {len(scheme.get('rules', []))}")
                
                review = scheme.get("review_queue", {})
                print(f"\nReview Status:")
                print(f"  Flagged:       {review.get('flagged')}")
                print(f"  Reason:        {review.get('reason')}")
                print(f"  Severity:      {review.get('severity')}")
                
                print(f"\nRULES ({len(scheme.get('rules', []))}):")
                print("-" * 100)
                
                for i, rule in enumerate(scheme.get('rules', []), 1):
                    print(f"\n[Rule {i}] {rule.get('Rule_ID')}")
                    print(f"  Type:       {rule.get('Rule_Type')}")
                    print(f"  Condition:  {rule.get('Condition_Type')}")
                    print(f"  Field:      {rule.get('Field')}")
                    print(f"  Operator:   {rule.get('Operator')}")
                    print(f"  Value:      {rule.get('Value')}")
                    print(f"  Confidence: {rule.get('Confidence'):.2f}")
                    print(f"  Quote:      {rule.get('Source_Quote')[:80]}")
                    if rule.get('Ambiguity_Flags'):
                        print(f"  Ambiguities: {', '.join(rule.get('Ambiguity_Flags'))}")
                
                return
    
    print(f"Scheme '{scheme_id}' not found")


def inspect_batch(batch_num, batches_dir):
    """Inspect a specific batch."""
    batch_file = os.path.join(batches_dir, f"kaggle_schemes_batch_{batch_num:03d}.json")
    
    if not os.path.exists(batch_file):
        print(f"Batch {batch_num} not found")
        return
    
    with open(batch_file, 'r') as f:
        batch = json.load(f)
    
    print(f"\n" + "=" * 100)
    print(f"BATCH {batch_num} SUMMARY")
    print("=" * 100)
    print(f"Total Schemes:  {len(batch)}")
    
    total_rules = sum(len(s.get('rules', [])) for s in batch)
    print(f"Total Rules:    {total_rules}")
    print(f"Avg Rules:      {total_rules / len(batch):.1f}")
    
    flagged = sum(1 for s in batch if s.get('review_queue', {}).get('flagged'))
    print(f"Flagged:        {flagged}")
    
    print(f"\nSchemes in this batch:")
    print("-" * 100)
    print(f"{'ID':<30} {'Name':<50} {'Rules':<8} {'Flagged':<8}")
    print("-" * 100)
    
    for scheme in batch:
        scheme_id = scheme.get('scheme_id', '')
        name = scheme.get('scheme_name', '')[:49]
        rules = len(scheme.get('rules', []))
        flagged = "YES" if scheme.get('review_queue', {}).get('flagged') else "NO"
        print(f"{scheme_id:<30} {name:<50} {rules:<8} {flagged:<8}")


def list_flagged_schemes(batches_dir):
    """List all schemes flagged for review."""
    batch_files = sorted(glob.glob(os.path.join(batches_dir, "kaggle_schemes_batch_*.json")))
    
    flagged_list = []
    
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch = json.load(f)
        
        for scheme in batch:
            if scheme.get('review_queue', {}).get('flagged'):
                flagged_list.append({
                    "id": scheme.get('scheme_id'),
                    "name": scheme.get('scheme_name'),
                    "reason": scheme.get('review_queue', {}).get('reason'),
                    "severity": scheme.get('review_queue', {}).get('severity'),
                    "rules": len(scheme.get('rules', []))
                })
    
    print(f"\n" + "=" * 100)
    print(f"FLAGGED SCHEMES FOR REVIEW ({len(flagged_list)} total)")
    print("=" * 100)
    
    # Group by severity
    by_severity = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for item in flagged_list:
        severity = item.get("severity", "LOW")
        if severity in by_severity:
            by_severity[severity].append(item)
    
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        items = by_severity[severity]
        if items:
            print(f"\n{severity} SEVERITY ({len(items)} schemes):")
            print("-" * 100)
            print(f"{'ID':<30} {'Name':<40} {'Rules':<8}")
            print("-" * 100)
            for item in items[:10]:
                print(f"{item['id']:<30} {item['name'][:39]:<40} {item['rules']:<8}")
            if len(items) > 10:
                print(f"... and {len(items) - 10} more")


def list_all_schemes(batches_dir):
    """List all schemes."""
    batch_files = sorted(glob.glob(os.path.join(batches_dir, "kaggle_schemes_batch_*.json")))
    
    schemes = []
    for batch_file in batch_files:
        with open(batch_file, 'r') as f:
            batch = json.load(f)
        
        for scheme in batch:
            schemes.append({
                "id": scheme.get('scheme_id'),
                "name": scheme.get('scheme_name'),
                "state": scheme.get('state_scope'),
                "rules": len(scheme.get('rules', [])),
                "flagged": scheme.get('review_queue', {}).get('flagged')
            })
    
    print(f"\n" + "=" * 100)
    print(f"ALL SCHEMES ({len(schemes)} total)")
    print("=" * 100)
    print(f"{'ID':<30} {'State':<8} {'Rules':<8} {'Flagged':<8} {'Name':<40}")
    print("-" * 100)
    
    for scheme in schemes:
        flagged = "YES" if scheme['flagged'] else "NO"
        print(f"{scheme['id']:<30} {scheme['state']:<8} {scheme['rules']:<8} {flagged:<8} {scheme['name'][:39]:<40}")


def main():
    batches_dir = "/Users/dhruv/Downloads/projects/cbc/parsed_schemes"
    
    if len(sys.argv) < 2:
        print("""
Usage: python inspect_parsed_schemes.py [COMMAND] [OPTIONS]

Commands:
  --batch N              Inspect batch number N (1-68)
  --scheme SLUG          Inspect specific scheme by slug
  --flagged              List all schemes flagged for review
  --all                  List all schemes
  --help                 Show this help
  
Examples:
  python inspect_parsed_schemes.py --batch 1
  python inspect_parsed_schemes.py --scheme pmuy
  python inspect_parsed_schemes.py --flagged
  python inspect_parsed_schemes.py --all
""")
        return
    
    if sys.argv[1] == "--batch" and len(sys.argv) > 2:
        inspect_batch(int(sys.argv[2]), batches_dir)
    elif sys.argv[1] == "--scheme" and len(sys.argv) > 2:
        inspect_scheme(sys.argv[2].upper(), batches_dir)
    elif sys.argv[1] == "--flagged":
        list_flagged_schemes(batches_dir)
    elif sys.argv[1] == "--all":
        list_all_schemes(batches_dir)
    elif sys.argv[1] == "--help":
        print("Help text shown above")
    else:
        print(f"Unknown command: {sys.argv[1]}")


if __name__ == "__main__":
    main()
