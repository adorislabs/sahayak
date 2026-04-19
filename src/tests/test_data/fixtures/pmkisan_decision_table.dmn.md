---
scheme_id: PMKISAN
scheme_name: Pradhan Mantri Kisan Samman Nidhi
short_name: PM-KISAN
ministry: Ministry of Agriculture and Farmers Welfare
state_scope: central
status: active
version: 2.1.0
last_verified: "2026-04-17"
data_source_tier: 2
source_urls:
  - https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf
tags:
  - agriculture
  - income_support
  - central
---

# PM-KISAN Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMKISAN-R001 | PMKISAN | eligibility | land_ownership | applicant.land_ownership_status | EQ | applicant.land_ownership_status EQ true | All landholding farmer families, which have the cultivable land as per land records | https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf | 0.95 | VERIFIED | Applicant must own cultivable agricultural land as per state land records | 2.1.0 |
| PMKISAN-R002 | PMKISAN | eligibility | tax_status | employment.is_income_tax_payer | EQ | employment.is_income_tax_payer EQ false | Families in which one or more members are income tax payees are excluded | https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf | 0.98 | VERIFIED | No family member should be an income tax payer | 2.1.0 |
| PMKISAN-DIS-001 | PMKISAN | disqualifying | tax_status | employment.is_income_tax_payer | EQ | employment.is_income_tax_payer EQ true | If any family member is an income tax payer, the family shall be excluded | https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf | 0.99 | VERIFIED | Disqualified: Family has an income tax paying member | 2.1.0 |
| PMKISAN-R003 | PMKISAN | eligibility | scheme_enrollment | enrollment.epfo | EQ | enrollment.epfo EQ false | Families in which one or more members are EPFO members are excluded | https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf | 0.95 | VERIFIED | No family member should be enrolled in EPFO | 2.1.0 |
| PMKISAN-R004 | PMKISAN | eligibility | document | documents.aadhaar | EQ | documents.aadhaar EQ true | Aadhaar seeded data is mandatory for getting benefit | https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf | 0.90 | VERIFIED | Must have Aadhaar linked to bank account | 2.1.0 |
| PMKISAN-R005-UP | PMKISAN | eligibility | land_holding | household.land_acres | LTE | household.land_acres LTE 5.0 | Uttar Pradesh: cultivable land up to 5 acres only | https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf | 0.85 | NEEDS_REVIEW | UP state override: Land must not exceed 5 acres | 2.1.0 |
