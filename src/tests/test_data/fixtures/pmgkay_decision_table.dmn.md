---
scheme_id: PMGKAY
scheme_name: Pradhan Mantri Garib Kalyan Anna Yojana
short_name: PMGKAY
ministry: Ministry of Consumer Affairs Food and Public Distribution
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://dfpd.gov.in/pmgkay.htm
tags:
  - food_security
  - ration
  - bpl
  - central
---

# PMGKAY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMGKAY-R001 | PMGKAY | prerequisite | ration_card | documents.ration_card_category | IN | documents.ration_card_category IN [AAY, PHH] | Beneficiaries under the National Food Security Act holding AAY or Priority Household ration cards are eligible for PMGKAY free grain | https://dfpd.gov.in/pmgkay.htm | 0.99 | VERIFIED | Must hold an Antyodaya Anna Yojana (AAY) or Priority Household (PHH) ration card under NFSA | 2.0.0 |
| PMGKAY-R002 | PMGKAY | eligibility | aadhaar | documents.aadhaar | EQ | documents.aadhaar EQ true | Aadhaar-based biometric authentication is mandatory for PMGKAY grain distribution at PDS outlets | https://dfpd.gov.in/pmgkay.htm | 0.97 | VERIFIED | Aadhaar seeding with ration card mandatory for biometric authentication at PDS | 2.0.0 |
| PMGKAY-R003 | PMGKAY | eligibility | poverty_status | household.bpl_status | EQ | household.bpl_status EQ true | Free grain entitlement is for poor and vulnerable households covered under NFSA | https://dfpd.gov.in/pmgkay.htm | 0.95 | VERIFIED | Household must be covered under National Food Security Act (NFSA) as BPL/deprived household | 2.0.0 |
