---
scheme_id: PMSYM
scheme_name: Pradhan Mantri Shram Yogi Maandhan
short_name: PM-SYM
ministry: Ministry of Labour and Employment
state_scope: central
status: active
version: 1.2.0
last_verified: "2026-04-17"
data_source_tier: 2
source_urls:
  - https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf
tags:
  - pension
  - unorganized_workers
  - central
---

# PM-SYM Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMSYM-R001 | PMSYM | eligibility | age_range | applicant.age | BETWEEN | applicant.age BETWEEN 18 AND 40 | The minimum age of joining the scheme is 18 years and maximum is 40 years | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.98 | VERIFIED | Applicant age must be between 18 and 40 years | 1.2.0 |
| PMSYM-R002 | PMSYM | eligibility | income_ceiling | household.income_monthly | LTE | household.income_monthly LTE 15000 | Monthly income should not exceed Rs. 15,000 | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.95 | VERIFIED | Monthly income must not exceed Rs 15,000 | 1.2.0 |
| PMSYM-R003 | PMSYM | eligibility | employment | employment.sector | EQ | employment.sector EQ unorganised | The scheme is meant for unorganised workers | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.95 | VERIFIED | Must be employed in the unorganised sector | 1.2.0 |
| PMSYM-R004 | PMSYM | eligibility | scheme_enrollment | enrollment.epfo | EQ | enrollment.epfo EQ false | Should not be a member of EPFO/ESIC/NPS (Government funded) | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.95 | VERIFIED | Must not be enrolled in EPFO | 1.2.0 |
| PMSYM-R005 | PMSYM | eligibility | scheme_enrollment | enrollment.esic | EQ | enrollment.esic EQ false | Should not be a member of EPFO/ESIC/NPS (Government funded) | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.95 | VERIFIED | Must not be enrolled in ESIC | 1.2.0 |
| PMSYM-R006 | PMSYM | eligibility | scheme_enrollment | enrollment.nps | EQ | enrollment.nps EQ false | Should not be a member of EPFO/ESIC/NPS (Government funded) | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.95 | VERIFIED | Must not be enrolled in NPS (Govt) | 1.2.0 |
| PMSYM-R007 | PMSYM | eligibility | document | documents.aadhaar | EQ | documents.aadhaar EQ true | Should have Aadhaar number | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.90 | VERIFIED | Must have Aadhaar number | 1.2.0 |
| PMSYM-R008 | PMSYM | eligibility | document | documents.bank_account | EQ | documents.bank_account EQ true | Should have savings bank account or Jan Dhan account | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.90 | VERIFIED | Must have savings bank account | 1.2.0 |
| PMSYM-DIS-001 | PMSYM | disqualifying | tax_status | employment.is_income_tax_payer | EQ | employment.is_income_tax_payer EQ true | Should not be an income tax payer | https://labour.gov.in/sites/default/files/PMSYM_Guidelines.pdf | 0.98 | VERIFIED | Disqualified: Must not be an income tax payer | 1.2.0 |
