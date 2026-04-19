---
scheme_id: SSY
scheme_name: Sukanya Samriddhi Yojana
short_name: SSY
ministry: Ministry of Finance (DFS)
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://www.indiapost.gov.in/Financial/pages/content/sukanya-samridhi.aspx
  - https://cleartax.in/s/sukanya-samriddhi-yojana
tags:
  - girl_child
  - savings
  - women_empowerment
  - central
---

# SSY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SSY-R001 | SSY | eligibility | gender | applicant.gender | EQ | applicant.gender EQ female | Only a girl child can avail the benefits of Sukanya Samriddhi Yojana | https://cleartax.in/s/sukanya-samriddhi-yojana | 0.99 | VERIFIED | Beneficiary must be a girl (female) child | 2.0.0 |
| SSY-R002 | SSY | eligibility | age_range | applicant.age | LTE | applicant.age LTE 10 | The maximum age of this child should be 10 years; a grace period applies for girls born in the year of scheme launch | https://en.wikipedia.org/wiki/Sukanya_Samriddhi_Account | 0.99 | VERIFIED | Girl child must be 10 years of age or younger at time of account opening | 2.0.0 |
| SSY-DIS-001 | SSY | disqualifying | existing_account | enrollment.has_ssy_account | EQ | enrollment.has_ssy_account EQ true | Maximum two accounts per family are permitted (one per girl child); no third account allowed | https://cleartax.in/s/sukanya-samriddhi-yojana | 0.98 | VERIFIED | Disqualified: family already has SSY accounts for two girl children | 2.0.0 |
| SSY-R003 | SSY | prerequisite | bank_account | documents.guardian_bank_account | EQ | documents.guardian_bank_account EQ true | Account opened by parent or legal guardian on behalf of the girl child | https://cleartax.in/s/sukanya-samriddhi-yojana | 0.98 | VERIFIED | Account must be opened by parent or legal guardian; guardian bank account required | 2.0.0 |
| SSY-R004 | SSY | eligibility | nationality | applicant.is_resident_indian | EQ | applicant.is_resident_indian EQ true | SSY Account Eligibility: Only for resident Indian girl children | https://cleartax.in/s/sukanya-samriddhi-yojana | 0.98 | VERIFIED | Beneficiary must be a resident Indian girl child (NRIs not eligible) | 2.0.0 |
