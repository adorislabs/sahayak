---
scheme_id: APY
scheme_name: Atal Pension Yojana
short_name: APY
ministry: Ministry of Finance (PFRDA)
state_scope: central
status: active
version: 2.1.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://financialservices.gov.in/beta/en/atal-pension-yojna
  - https://www.pfrda.org.in/index7.cshtml?id=584
tags:
  - pension
  - unorganised_sector
  - central
---

# APY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APY-R001 | APY | eligibility | age_range | applicant.age | BETWEEN | applicant.age BETWEEN 18 AND 40 | The age of the subscriber should be between 18 and 40 years | https://financialservices.gov.in/beta/en/atal-pension-yojna | 0.99 | VERIFIED | Applicant must be between 18 and 40 years of age at time of joining | 2.1.0 |
| APY-R002 | APY | prerequisite | bank_account | documents.bank_account | EQ | documents.bank_account EQ true | He / She should have a savings bank account / post office savings bank account | https://financialservices.gov.in/beta/en/atal-pension-yojna | 0.98 | VERIFIED | A savings bank account or post office savings account is mandatory for auto-debit | 2.1.0 |
| APY-R003 | APY | eligibility | tax_status | employment.is_income_tax_payer | EQ | employment.is_income_tax_payer EQ false | From 1 October 2022, new APY subscribers should not be current or former income-tax payers under the Income-tax Act | https://financialservices.gov.in/beta/en/atal-pension-yojna | 0.97 | VERIFIED | Applicant must not be a current or former income tax payer (effective 1 October 2022) | 2.1.0 |
| APY-DIS-001 | APY | disqualifying | tax_status | employment.is_income_tax_payer | EQ | employment.is_income_tax_payer EQ true | Income tax payers are not eligible to join APY from 1 October 2022 | https://financialservices.gov.in/beta/en/atal-pension-yojna | 0.97 | VERIFIED | Disqualified: applicant is a current or former income tax payer (rule effective Oct 2022) | 2.1.0 |
