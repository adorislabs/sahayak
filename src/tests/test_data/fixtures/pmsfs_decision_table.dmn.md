---
scheme_id: PMSFS
scheme_name: Post-Matric Scholarship for SC/ST Students
short_name: PMS SC/ST
ministry: Ministry of Social Justice and Empowerment / Ministry of Tribal Affairs
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://scholarships.gov.in
  - https://socialjustice.gov.in/schemes/9
tags:
  - scholarship
  - sc_st
  - education
  - central
---

# PMS SC/ST Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMSFS-R001 | PMSFS | eligibility | caste_category | applicant.caste_category | IN | applicant.caste_category IN [SC, ST] | Post-Matric Scholarships are available for Scheduled Caste (SC) and Scheduled Tribe (ST) students | https://scholarships.gov.in | 0.99 | VERIFIED | Applicant must belong to Scheduled Caste (SC) or Scheduled Tribe (ST) category | 2.0.0 |
| PMSFS-R002 | PMSFS | eligibility | education_level | applicant.education_level | EQ | applicant.education_level EQ post_matric | The scholarship is for students pursuing post-matriculation or post-secondary level courses | https://scholarships.gov.in | 0.99 | VERIFIED | Applicant must be enrolled in a post-matriculation (Class 11 and above) course | 2.0.0 |
| PMSFS-R003 | PMSFS | eligibility | income_ceiling | household.income_annual | LTE | household.income_annual LTE 250000 | Family income should generally not exceed ₹2.5 lakh per annum for SC/ST category | https://www.buddy4study.com/article/post-matric-scholarship | 0.88 | NEEDS_REVIEW | Annual family income must not exceed ₹2,50,000 (income limit revision to ₹4.5L under government review as of 2026) | 2.0.0 |
| PMSFS-R004 | PMSFS | prerequisite | caste_certificate | documents.caste_certificate | EQ | documents.caste_certificate EQ true | Caste certificate issued by competent authority is mandatory for scholarship application | https://scholarships.gov.in | 0.98 | VERIFIED | Valid SC/ST caste certificate issued by competent authority is mandatory | 2.0.0 |
| PMSFS-R005 | PMSFS | eligibility | academic_performance | applicant.previous_exam_marks_pct | GTE | applicant.previous_exam_marks_pct GTE 50 | Applicants must have at least 50% marks in their previous examination | https://www.buddy4study.com/article/post-matric-scholarship | 0.85 | NEEDS_REVIEW | Applicant must have secured at least 50% marks in the last qualifying examination (varies by state) | 2.0.0 |
