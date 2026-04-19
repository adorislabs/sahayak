---
scheme_id: MGNREGA
scheme_name: Mahatma Gandhi National Rural Employment Guarantee Act
short_name: MGNREGA
ministry: Ministry of Rural Development
state_scope: central
status: active
version: 1.5.0
last_verified: "2026-04-17"
data_source_tier: 2
source_urls:
  - https://nrega.nic.in/Circular_Archive/archive/nrega_guidelines.pdf
tags:
  - employment
  - rural
  - central
---

# MGNREGA Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MGNREGA-R001 | MGNREGA | eligibility | age_range | applicant.age | GTE | applicant.age GTE 18 | The applicant must be at least 18 years of age | https://nrega.nic.in/Circular_Archive/archive/nrega_guidelines.pdf | 0.99 | VERIFIED | Applicant must be at least 18 years old | 1.5.0 |
| MGNREGA-R002 | MGNREGA | eligibility | residence_type | household.residence_type | EQ | household.residence_type EQ rural | The applicant must be residing in a Rural Area | https://nrega.nic.in/Circular_Archive/archive/nrega_guidelines.pdf | 0.99 | VERIFIED | Must reside in a rural area | 1.5.0 |
| MGNREGA-R003 | MGNREGA | eligibility | document | documents.mgnrega_job_card | EQ | documents.mgnrega_job_card EQ true | Household must have a Job Card issued under MGNREGA | https://nrega.nic.in/Circular_Archive/archive/nrega_guidelines.pdf | 0.95 | VERIFIED | Must have MGNREGA Job Card | 1.5.0 |
| MGNREGA-R004 | MGNREGA | eligibility | employment | applicant.employment_type | IN | applicant.employment_type IN (manual_labour, agricultural, daily_wage, unemployed) | Willing to do unskilled manual work | https://nrega.nic.in/Circular_Archive/archive/nrega_guidelines.pdf | 0.85 | NEEDS_REVIEW | Must be willing to do unskilled manual work | 1.5.0 |
| MGNREGA-ADM-001 | MGNREGA | administrative_discretion | priority | household.bpl_status | EQ | household.bpl_status EQ true | Priority shall be given to BPL households, SC/ST households, women-headed households | https://nrega.nic.in/Circular_Archive/archive/nrega_guidelines.pdf | 0.80 | VERIFIED | Priority given to BPL households | 1.5.0 |
