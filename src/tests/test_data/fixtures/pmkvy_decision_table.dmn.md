---
scheme_id: PMKVY
scheme_name: Pradhan Mantri Kaushal Vikas Yojana 4.0
short_name: PMKVY 4.0
ministry: Ministry of Skill Development and Entrepreneurship
state_scope: central
status: active
version: 4.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://www.msde.gov.in/static/uploads/2024/02/PMKVY-4.0-Guidelines_final-copy.pdf
  - https://www.pmkvyofficial.org
tags:
  - skill_training
  - youth
  - employment
  - central
---

# PMKVY 4.0 Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMKVY-R001 | PMKVY | eligibility | age_range | applicant.age | BETWEEN | applicant.age BETWEEN 15 AND 45 | Indian nationals aged 15-45 years are eligible; unemployed youth or school/college dropouts | https://www.msde.gov.in/static/uploads/2024/02/PMKVY-4.0-Guidelines_final-copy.pdf | 0.95 | VERIFIED | Applicant must be between 15 and 45 years of age | 4.0.0 |
| PMKVY-DIS-001 | PMKVY | disqualifying | enrollment_status | enrollment.is_fulltime_enrolled | EQ | enrollment.is_fulltime_enrolled EQ true | Candidates currently enrolled full-time in a formal education institution are not eligible for PMKVY short-term skill training | https://www.msde.gov.in/static/uploads/2024/02/PMKVY-4.0-Guidelines_final-copy.pdf | 0.88 | VERIFIED | Disqualified: applicant is currently a full-time enrolled student in a formal institution | 4.0.0 |
| PMKVY-R002 | PMKVY | eligibility | education_min | applicant.education_level_min | GTE | applicant.education_level_min GTE class_8 | Applicants must have a minimum qualification of 8th, 10th, or 12th pass; ITI graduates also eligible | https://www.msde.gov.in/static/uploads/2024/02/PMKVY-4.0-Guidelines_final-copy.pdf | 0.88 | VERIFIED | Minimum educational qualification: Class 8 pass (subject to sector-specific requirements) | 4.0.0 |
| PMKVY-R003 | PMKVY | prerequisite | bank_account | documents.bank_account | EQ | documents.bank_account EQ true | Stipend and certification incentives are transferred directly to trainees' bank accounts; bank account mandatory | https://www.msde.gov.in/static/uploads/2024/02/PMKVY-4.0-Guidelines_final-copy.pdf | 0.95 | VERIFIED | Bank account (Aadhaar-linked) required for stipend/incentive transfer | 4.0.0 |
