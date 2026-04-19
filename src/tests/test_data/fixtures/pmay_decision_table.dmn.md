---
scheme_id: PMAY
scheme_name: Pradhan Mantri Awas Yojana — Urban
short_name: PMAY-U
ministry: Ministry of Housing and Urban Affairs
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://pmay-urban.gov.in/uploads/guidelines/Operational-Guidelines-of-PMAY-U-2.pdf
  - https://pmaymis.gov.in
tags:
  - housing
  - urban
  - central
---

# PMAY-U Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMAY-DIS-001 | PMAY | disqualifying | housing_status | household.has_pucca_house | EQ | household.has_pucca_house EQ true | Families belonging to EWS/LIG/MIG category, living in urban areas, having no pucca house anywhere in the country, are eligible | https://pmay-urban.gov.in/uploads/guidelines/Operational-Guidelines-of-PMAY-U-2.pdf | 0.99 | VERIFIED | Disqualified: applicant or spouse already owns a pucca house anywhere in India | 2.0.0 |
| PMAY-R001 | PMAY | eligibility | income_group | household.income_annual | LTE | household.income_annual LTE 300000 | Economically Weaker Section (EWS): Annual income up to Rs 3 lakh | https://pmay-urban.gov.in/uploads/guidelines/Operational-Guidelines-of-PMAY-U-2.pdf | 0.99 | VERIFIED | EWS category: annual household income up to ₹3,00,000 | 2.0.0 |
| PMAY-R002 | PMAY | eligibility | income_group | household.income_annual | BETWEEN | household.income_annual BETWEEN 300001 AND 600000 | Low-Income Group (LIG): Annual income between Rs 3.01 lakh and Rs 6 lakh | https://pmay-urban.gov.in/uploads/guidelines/Operational-Guidelines-of-PMAY-U-2.pdf | 0.99 | VERIFIED | LIG category: annual household income between ₹3,00,001 and ₹6,00,000 | 2.0.0 |
| PMAY-R003 | PMAY | eligibility | residence_type | household.residence_type | EQ | household.residence_type EQ urban | Families living in urban areas are eligible | https://pmay-urban.gov.in/uploads/guidelines/Operational-Guidelines-of-PMAY-U-2.pdf | 0.98 | VERIFIED | Applicant must be residing in an urban area (notified municipality/town) | 2.0.0 |
| PMAY-R004 | PMAY | eligibility | aadhaar | documents.aadhaar | EQ | documents.aadhaar EQ true | Aadhaar seeding is mandatory for PMAY-U benefit transfer | https://pmaymis.gov.in | 0.95 | VERIFIED | Aadhaar card mandatory for registration and direct benefit transfer | 2.0.0 |
| PMAY-R005 | PMAY | eligibility | gender | applicant.gender | EQ | applicant.gender EQ female | EWS/LIG beneficiaries: house must be allotted in the name of the female head of household or jointly | https://pmay-urban.gov.in/uploads/guidelines/Operational-Guidelines-of-PMAY-U-2.pdf | 0.90 | VERIFIED | For EWS/LIG: ownership must be in name of female head or co-ownership with spouse | 2.0.0 |
