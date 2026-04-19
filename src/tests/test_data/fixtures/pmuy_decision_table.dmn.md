---
scheme_id: PMUY
scheme_name: Pradhan Mantri Ujjwala Yojana 2.0
short_name: PMUY
ministry: Ministry of Petroleum and Natural Gas
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://pmuy.gov.in
  - https://theiashub.com/upsc/pm-ujjwala-scheme/
tags:
  - lpg
  - bpl
  - women_empowerment
  - central
---

# PMUY Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PMUY-DIS-001 | PMUY | disqualifying | lpg_connection | household.has_lpg_connection | EQ | household.has_lpg_connection EQ true | The household should not have any other LPG connection from any Oil Marketing Company (OMC) | https://pmuy.gov.in | 0.99 | VERIFIED | Disqualified: household already has an LPG connection from any OMC | 2.0.0 |
| PMUY-R001 | PMUY | eligibility | gender | applicant.gender | EQ | applicant.gender EQ female | The applicant must be a woman who has reached the age of 18 years | https://pmuy.gov.in | 0.99 | VERIFIED | Applicant must be an adult woman (female, age ≥18) | 2.0.0 |
| PMUY-R002 | PMUY | eligibility | age_range | applicant.age | GTE | applicant.age GTE 18 | The applicant must be a woman who has reached the age of 18 years | https://pmuy.gov.in | 0.99 | VERIFIED | Applicant must be 18 years of age or older | 2.0.0 |
| PMUY-R003 | PMUY | eligibility | poverty_category | household.poverty_category | IN | household.poverty_category IN [SC, ST, MBC, AAY, PMAYG_beneficiary, SECC_AHL_TIN, forest_dweller, tea_garden_tribe, island_resident, fourteen_point_declaration] | Woman applicant must belong to SC/ST, PMAY-G, MBC, AAY, Tea/Ex-Tea Garden tribes, Forest Dwellers, Islands/River Islands, SECC AHL TIN, or 14-point declaration household | https://pmuy.gov.in | 0.97 | VERIFIED | Applicant must belong to one of the designated deprived categories (SC/ST/MBC/AAY/PMAY-G/SECC/forest/island/14-point declaration) | 2.0.0 |
| PMUY-R004 | PMUY | prerequisite | aadhaar | documents.aadhaar | EQ | documents.aadhaar EQ true | Aadhaar Card of the applicant (for identity and address proof); not mandatory for residents of Assam and Meghalaya | https://pmuy.gov.in | 0.95 | VERIFIED | Aadhaar required for KYC (except Assam/Meghalaya residents) | 2.0.0 |
