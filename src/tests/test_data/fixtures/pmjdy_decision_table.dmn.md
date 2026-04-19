---
scheme_id: PMJDY
scheme_name: Pradhan Mantri Jan Dhan Yojana
short_name: PMJDY
ministry: Ministry of Finance (DFS)
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://pmjdy.gov.in/scheme
tags:
  - financial_inclusion
  - banking
  - central
---

# PMJDY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMJDY-DIS-001 | PMJDY | disqualifying | bank_account | documents.bank_account | EQ | documents.bank_account EQ true | Every unbanked adult who does not have a bank account is eligible; existing account holders are not re-eligible for zero-balance account | https://pmjdy.gov.in/scheme | 0.98 | VERIFIED | Disqualified: applicant already holds a bank account with any scheduled commercial bank | 2.0.0 |
| PMJDY-R001 | PMJDY | eligibility | age_range | applicant.age | GTE | applicant.age GTE 10 | Minors of age 10 years and above can open a minor account with guardian oversight | https://pmjdy.gov.in/scheme | 0.90 | VERIFIED | Applicant must be at least 10 years old (minor accounts ≥10 years with guardian) | 2.0.0 |
| PMJDY-R002 | PMJDY | eligibility | nationality | applicant.is_indian_citizen | EQ | applicant.is_indian_citizen EQ true | The scheme is open to all Indian citizens who are unbanked | https://pmjdy.gov.in/scheme | 0.98 | VERIFIED | Applicant must be an Indian citizen | 2.0.0 |
| PMJDY-R003 | PMJDY | eligibility | aadhaar | documents.aadhaar | EQ | documents.aadhaar EQ true | Aadhaar is the preferred KYC document; those without Aadhaar may submit other officially valid documents | https://pmjdy.gov.in/scheme | 0.85 | VERIFIED | Aadhaar preferred for KYC; OVD acceptable where Aadhaar unavailable | 2.0.0 |
