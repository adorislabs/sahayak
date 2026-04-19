---
scheme_id: ABPMJAY
scheme_name: Ayushman Bharat Pradhan Mantri Jan Arogya Yojana
short_name: AB-PMJAY
ministry: Ministry of Health and Family Welfare
state_scope: central
status: active
version: 3.1.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://pmjay.gov.in/sites/default/files/2019-09/Operational-Guidelines-PMJAY.pdf
  - https://ayushmancard.org/en/eligibility-for-ayushman-card/
tags:
  - health
  - insurance
  - bpl
  - central
---

# AB-PMJAY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ABPMJAY-R001 | ABPMJAY | eligibility | poverty_status | household.bpl_status | EQ | household.bpl_status EQ true | Families meeting at least one of the six SECC deprivation criteria for rural areas are automatically included | https://pmjay.gov.in/sites/default/files/2019-09/Operational-Guidelines-PMJAY.pdf | 0.88 | VERIFIED | Household must meet SECC-2011 deprivation criteria (rural) or occupational criteria (urban) | 3.1.0 |
| ABPMJAY-R002 | ABPMJAY | eligibility | residence_type | household.residence_type | IN | household.residence_type IN [rural, urban] | Urban poor families meeting occupational criteria are also included | https://pmjay.gov.in/sites/default/files/2019-09/Operational-Guidelines-PMJAY.pdf | 0.95 | VERIFIED | Coverage extends to both rural SECC households and urban occupational-criteria households | 3.1.0 |
| ABPMJAY-R003 | ABPMJAY | eligibility | aadhaar | documents.aadhaar | EQ | documents.aadhaar EQ true | Aadhaar is the primary identity document for beneficiary verification and golden card issuance | https://pmjay.gov.in/sites/default/files/2019-09/Operational-Guidelines-PMJAY.pdf | 0.96 | VERIFIED | Aadhaar card required for beneficiary verification and Ayushman golden card generation | 3.1.0 |
| ABPMJAY-R004 | ABPMJAY | eligibility | age_range | applicant.age | GTE | applicant.age GTE 70 | From September 2024, all Indian citizens aged 70 years and above are eligible for Ayushman Card regardless of income or SECC status | https://ayushmancard.org/en/eligibility-for-ayushman-card/ | 0.95 | VERIFIED | Citizens aged 70 or above are eligible unconditionally (September 2024 expansion) | 3.1.0 |
| ABPMJAY-ADM-001 | ABPMJAY | administrative_discretion | income_ceiling | household.income_annual | LTE | household.income_annual LTE 500000 | Coverage is for poor and vulnerable families; income is not a direct criterion but SECC captures economic deprivation | https://pmjay.gov.in/sites/default/files/2019-09/Operational-Guidelines-PMJAY.pdf | 0.60 | PENDING | Informal income ceiling advisory — families with income > ₹5 lakh may face state-level scrutiny | 3.1.0 |
