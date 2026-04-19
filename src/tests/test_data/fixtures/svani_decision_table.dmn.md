---
scheme_id: SVANI
scheme_name: PM Street Vendor's AtmaNirbhar Nidhi
short_name: PM SVANidhi
ministry: Ministry of Housing and Urban Affairs
state_scope: central
status: active
version: 2.0.0
last_verified: "2026-04-17"
data_source_tier: 1
source_urls:
  - https://pmsvanidhi.mohua.gov.in
tags:
  - street_vendors
  - microfinance
  - urban
  - central
---

# PM SVANidhi Decision Table

| Rule_ID | Scheme_ID | Rule_Type | Condition_Type | Field | Operator | Condition | Source_Quote | Source_URL | Confidence | Audit_Status | Display_Text | Version |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SVANI-R001 | SVANI | eligibility | occupation | applicant.occupation | EQ | applicant.occupation EQ street_vendor | Street vendors active before March 24, 2020, are eligible for the working capital loan | https://pmsvanidhi.mohua.gov.in | 0.98 | VERIFIED | Applicant must be a street vendor (vending prior to 24 March 2020 preferred) | 2.0.0 |
| SVANI-R002 | SVANI | eligibility | age_range | applicant.age | GTE | applicant.age GTE 18 | Must be 18 years or older to apply for PM SVANidhi loan | https://pmsvanidhi.mohua.gov.in | 0.99 | VERIFIED | Applicant must be at least 18 years of age | 2.0.0 |
| SVANI-R003 | SVANI | eligibility | vendor_certificate | documents.vending_certificate | EQ | documents.vending_certificate EQ true | Vendors must hold a Certificate of Vending issued by ULB Town Vending Committee (TVC) | https://pmsvanidhi.mohua.gov.in | 0.92 | VERIFIED | Must hold a Certificate of Vending issued by ULB/TVC (logic group OR with SVANI-R004) | 2.0.0 |
| SVANI-R004 | SVANI | eligibility | ulb_registration | documents.ulb_registration | EQ | documents.ulb_registration EQ true | Vendors recommended by Urban Local Body (ULB) or having letter of recommendation are also eligible | https://pmsvanidhi.mohua.gov.in | 0.90 | VERIFIED | Alternatively: Letter of Recommendation from ULB (OR with SVANI-R003) | 2.0.0 |
| SVANI-R005 | SVANI | eligibility | residence_type | household.residence_type | EQ | household.residence_type EQ urban | PM SVANidhi is for urban street vendors; vending location must be in an urban area | https://pmsvanidhi.mohua.gov.in | 0.98 | VERIFIED | Vendor must operate in an urban area (ULB jurisdiction) | 2.0.0 |
