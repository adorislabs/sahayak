---
scheme_id: NSAP
scheme_name: National Social Assistance Programme - Indira Gandhi National Old Age Pension Scheme
short_name: NSAP-IGNOAPS
ministry: Ministry of Rural Development
state_scope: central
status: active
version: 1.3.0
last_verified: "2026-04-17"
data_source_tier: 2
source_urls:
  - https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf
tags:
  - pension
  - senior_citizen
  - bpl
  - central
---

# NSAP-IGNOAPS Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NSAP-R001 | NSAP | eligibility | age_range | applicant.age | GTE | applicant.age GTE 60 | The applicant should be at least 60 years of age | https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf | 0.99 | VERIFIED | Applicant must be 60 years or older | 1.3.0 |
| NSAP-R002 | NSAP | eligibility | poverty_status | household.bpl_status | EQ | household.bpl_status EQ true | The applicant should be living Below Poverty Line | https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf | 0.98 | VERIFIED | Must belong to a Below Poverty Line family | 1.3.0 |
| NSAP-R003 | NSAP | eligibility | nationality | applicant.nationality | EQ | applicant.nationality EQ Indian | The applicant should be a citizen of India | https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf | 0.99 | VERIFIED | Must be an Indian citizen | 1.3.0 |
| NSAP-R004 | NSAP | eligibility | scheme_enrollment | scheme.benefit_received | EQ | scheme.benefit_received EQ false | Should not be receiving pension from any other social security scheme | https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf | 0.90 | VERIFIED | Must not be receiving pension from other scheme | 1.3.0 |
| NSAP-R005-MH | NSAP | eligibility | age_range | applicant.age | GTE | applicant.age GTE 65 | Maharashtra: applicant should be 65 years of age or older | https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf | 0.85 | NEEDS_REVIEW | Maharashtra override: Must be 65 years or older | 1.3.0 |
| NSAP-R006 | NSAP | eligibility | document | documents.bank_account | EQ | documents.bank_account EQ true | Payment through bank account is mandatory | https://nsap.nic.in/Guidelines/nsap_guidelines_2014.pdf | 0.88 | VERIFIED | Must have a bank account for payment | 1.3.0 |
