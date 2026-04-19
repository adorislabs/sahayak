---
scheme_id: PMFBY
scheme_name: Pradhan Mantri Fasal Bima Yojana
short_name: PMFBY
ministry: Ministry of Agriculture and Farmers Welfare
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://pmfby.gov.in/operationalGuidelines
tags:
  - crop_insurance
  - agriculture
  - farmers
  - central
---

# PMFBY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMFBY-R001 | PMFBY | eligibility | occupation | applicant.occupation | IN | applicant.occupation IN [farmer, sharecropper, tenant_farmer] | All farmers, including sharecroppers and tenant farmers, growing the notified crops in the notified areas, are eligible for coverage | https://pmfby.gov.in/operationalGuidelines | 0.99 | VERIFIED | Applicant must be a farmer (landowner, sharecropper, or tenant farmer) | 2.0.0 |
| PMFBY-R002 | PMFBY | eligibility | crop_type | applicant.crop_type | EQ | applicant.crop_type EQ notified_crop | Only notified crops in notified areas are eligible for PMFBY coverage | https://pmfby.gov.in/operationalGuidelines | 0.99 | VERIFIED | Farmer must be cultivating a government-notified crop in a notified area | 2.0.0 |
| PMFBY-R003 | PMFBY | eligibility | cultivable_land | applicant.has_cultivable_land | EQ | applicant.has_cultivable_land EQ true | Farmer who cultivates crops in India is eligible; must have sown/cultivable land for the season | https://pmfby.gov.in/operationalGuidelines | 0.97 | VERIFIED | Applicant must have cultivated (or intend to cultivate) land for the current season | 2.0.0 |
| PMFBY-R004 | PMFBY | prerequisite | bank_account | documents.bank_account | EQ | documents.bank_account EQ true | Premium subsidy and claim amounts are disbursed directly to farmer's bank account; bank account is mandatory | https://pmfby.gov.in/operationalGuidelines | 0.98 | VERIFIED | A bank account (linked to Aadhaar) is required for premium subsidy and claim disbursement | 2.0.0 |
