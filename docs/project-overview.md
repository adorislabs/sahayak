# Project: AI Document Intelligence for India's Welfare System

NOTE: This document is not necessarily how the project will strictly work but a rough anchor to understand the intention.

## Project Vision

Named after APJ Abdul Kalam, this project builds an AI document intelligence engine for India's social security system. Millions of eligible Indians miss out on government benefits because the eligibility criteria are hidden in complex bureaucratic language across hundreds of PDFs with unclear requirements. This system transforms that landscape.

The core problem is not **discovery** (portals like myScheme already exist) but **fulfillment** — the last-mile gap where eligible citizens fail to actually receive benefits due to bureaucratic complexity, opaque eligibility language, cross-scheme conflicts, and the absence of unified application workflows. This project aims to be the "Amazon for Welfare": a system that discovers, evaluates, explains, and eventually assists in applying for government welfare schemes.

Note this document is just the base implementation that is required regardless of enhancement. Throughout the directory there are multiple implementations that are mentioned that are also to be implemented.

---

## Architecture Summary

The project is organized into **8 Parts** executed in sequence. Each Part produces artifacts consumed by downstream Parts. The dependency chain is:

```
PART 1 → PART 2 → PART 3 → PART 4 → PART 5 → PART 6 → PART 7 → PART 8
(Data)   (Parse)  (Match)  (Stress) (Convo)  (Infra)  (B2B)    (Prod)
```

| Part | Name | Status | Depends On |
|------|------|--------|------------|
| 1 | Data Structuring (Schema & Rules) | ✅ In progress / Done | — |
| 2 | Real Data Parsing Pipeline | 🔶 Planning done | Part 1 |
| 3 | The Matching Engine | 🔶 Planning done | Parts 1, 2 |
| 4 | Stress Testing & Validation Suite | ⬜ Not started | Parts 1, 2, 3 |
| 5 | Conversational Interface | ⬜ Not started | Part 3 |
| 6 | Dynamic Infrastructure & Monitoring | ⬜ Not started | Parts 1, 2 |
| 7 | B2B Middleware & Extended Use Cases | ⬜ Not started | Parts 3, 5, 6 |
| 8 | Production Readiness & Architecture | ⬜ Not started | All |

---

## PART 1: Data Structuring (Schema & Rules)

**Status**: ✅ In progress / Done — see `docs/part1-planning/` and `src/`

### Objective
Use AI to parse and structure eligibility criteria for central government welfare schemes: example: PM Kisan, MGNREGA, Ayushman Bharat, PMAY, and others.
Note you may apply to all schemes you get but the top 15 schemes should be upto date and stress tested.

### Critical Constraint
Eligibility rules must be converted to explicit logical rules, not prose summaries. The system must find every contradiction, overlap, and ambiguity across all schemes. Government eligibility language is vague by design—it preserves administrative discretion. Your ambiguity map is not optional; it's a core output.

### Key Decisions Made
- **DMN Decision Tables** over JSON for rule representation (human-auditable by policy officers)
- **Three-Tier Data Sourcing**: myScheme.gov.in (baseline) → National Portal PDFs (ground truth) → Kaggle dataset (accelerator)
- **Immutable rules + supersession chain** for versioning
- **Ambiguity Map is a first-class deliverable** — every ambiguity tracked with its own ID (`AMB-001`...)
- **30 Ambiguity Types Framework** for systematic edge-case detection (see `docs/reports/insight-reports/insight-report-ambiguity-map.md`)

### Deliverables
- Structured eligibility rules for 15+ anchor schemes in DMN-compatible format
- Pydantic v2 schema with full traceability (`source_url`, `source_section`, `last_verified`, `version`, `state_scope`)
- Ambiguity Map: contradictions, overlaps, vague terms, discretionary clauses
- Scheme Relationship Matrix: prerequisites, mutual exclusions, complementary schemes
- Source Anchors: every rule row linked to its exact PDF/Gazette source
- Review Queue: rules that failed quality gates, routed for human review

### Reference
- Planning: `docs/part1-planning/`
- Specs: `docs/part1-planning/spec/01` through `08`
- Implementation: `src/spec_01` through `src/spec_08`
- Tests: `src/tests/`

---

## PART 2: Real Data Parsing Pipeline

**Status**: 🔶 Planning done — implementation not started
**Depends on**: Part 1 (schema, rule format, ambiguity types)

### Problem This Solves
Part 1 builds the *schema and processing infrastructure*. Part 2 actually *uses it on real data*. Without this Part, the system has a rule engine with no rules loaded. This is the bridge between "we can parse schemes" and "we have parsed all the schemes."

### Objective
Run the parsing pipeline against the real dataset — the Kaggle "Indian Government Schemes" dataset (~3,400+ schemes), official Gazette PDFs, and myScheme.gov.in content — to populate the rule base with actual structured eligibility data.

### Data Sources
1. **Kaggle Dataset** (CSV/JSON, ~3,400+ schemes): Pre-parsed starting point with `Scheme Name`, `Eligibility`, `Benefits`, `Application Process` columns. Download the zip, load with pandas/polars, segment into batches of 50.
2. **myScheme.gov.in**: 4,650+ digitized scheme summaries. Draft baseline rules from here.
3. **National Portal PDFs** (india.gov.in / egazette.gov.in): Official Gazette PDFs — every rule must be verified against these before entering the rule base.
4. **Dataful.in**: Cross-reference fund release data to identify dormant vs. active schemes (avoid wasting effort on dead schemes).

### Parsing Agent Workflow
1. Load dataset (Kaggle CSV) with polars, segment into batches of 50 schemes
2. For each batch, pass eligibility prose to the Parsing Agent with strict ruleset
3. Agent outputs structured JSON: `age_min`, `age_max`, `residency`, `gender_req`, `income_ceiling`, plus `ambiguity_flags` array
4. Cross-validate parsed output against source PDFs for accuracy (Source Anchor linking)
5. Auto-populate the Ambiguity Map with unresolved conditions and edge cases
6. Save to Logical Rule Base only after validation passes
7. Failed rules auto-routed to `review_queue.json` (no human gates between batches)

### Anchor Schemes (Top 15 — must be stress-tested)
These schemes cover the widest population and are most digitized. They must be fully parsed, validated, and stress-tested before any downstream Part proceeds:
- PM-Kisan, MGNREGA, Ayushman Bharat (PM-JAY), PMAY, PM-GKAY
- Atal Pension Yojana (APY), PM-SYM, PM SVANidhi, Jan Dhan Yojana
- Ujjwala Yojana, Sukanya Samriddhi, PM Fasal Bima Yojana
- National Social Assistance Programme (NSAP), Scholarship schemes, Skill India

### Scraping (Last Resort)
For state-specific schemes not in any dataset: Python + Playwright (not Selenium). Target `/schemes/{scheme-slug}` endpoints. Map output directly to internal schema format.

### Deliverables
- Populated rule base: 15+ anchor schemes fully parsed and validated
- Extended rule base: remaining Kaggle schemes parsed (best-effort, review queue for failures)
- Populated Ambiguity Map with real ambiguities discovered during parsing
- Populated Scheme Relationship Matrix with real prerequisite/exclusion data
- Dormant scheme filter: list of schemes excluded due to zero fund releases
- Parsing quality report: accuracy metrics, failure rates, common error patterns

### Key Constraint
Variable names (`income`, `caste`, `age`) must be verified against **API Setu documentation** to ensure compatibility with actual government data fields. Misaligned naming causes silent failures in downstream matching.

---

## PART 3: The Matching Engine

**Status**: 🔶 Planning done — see `docs/part2-planning/` for full specs
**Depends on**: Parts 1, 2 (populated rule base, ambiguity map, relationship matrix)

> **Note**: This was previously called "Part II" in early planning. The full planning
> documents are in `docs/part2-planning/` (8 specification documents). The planning
> is complete and ready for implementation. Agents should read `docs/part2-planning/README.md`
> for the full spec index.

### User Input
Age, state, caste category, income, land ownership, occupation, family size, bank account status.

### System Outputs
- Schemes the user fully qualifies for with confidence scores
- Schemes they almost qualify for with gap analysis
- Document checklist in priority order
- Correct application sequence (some schemes are prerequisites for others)

### Output Requirements
Every result must be explainable. Confidence scores must connect to specific rule evaluations. No black boxes. Build ten adversarial user profiles: a widow who remarried recently, a farmer who leases rather than owns land, someone with an Aadhaar but no bank account. Test every failure and document it.

### Key Architectural Decisions (from planning)
- **Stateless evaluation engine**: No persistent user data storage (PII risk mitigation)
- **Deterministic evaluation order**: Disqualifiers → Prerequisites → Eligibility → Discretionary
- **Three-tier confidence**: Rule Match Score × Data Confidence × Profile Completeness (composite = `min`, not average)
- **Partial determination over silence**: Always give a partial answer rather than refusing when one rule is ambiguous
- **Gap analysis is first-class**: Failed rules + gap magnitude + actionable steps + prerequisites + document needs
- **Mutual exclusion as hard constraint**: Choice sets for conflicting schemes, not silent double-recommendation

### Reference
- Full specs: `docs/part2-planning/` (8 documents: `00-overview.md` through `08-architecture-contract.md`)

---

## PART 4: Stress Testing & Validation Suite

**Status**: ⬜ Not started
**Depends on**: Parts 1, 2, 3

### Problem This Solves
Parts 1-3 build the data pipeline, rule base, and matching engine independently. This Part validates the entire chain end-to-end on real data with adversarial inputs. Without it, we cannot know whether the system actually works for real Indian citizens.

### Objective
Systematically stress-test the complete pipeline (data → rules → matching → output) using adversarial profiles, edge cases, and the 30 Ambiguity Types Framework to surface every failure mode before building user-facing interfaces.

### 4.1 Adversarial User Profiles (10 minimum)
Build and test profiles that exploit every known edge case:
1. **Widow who recently remarried** — tests life-event transition protocols, benefit succession
2. **Farmer who leases rather than owns land** — tests land ownership ambiguity, documentary substitution
3. **Person with Aadhaar but no bank account** — tests infrastructure preconditions
4. **Interstate migrant worker** (documents tied to Bihar, lives in Karnataka) — tests portability gaps
5. **Home-based domestic worker** (no formal employer) — tests hidden segment coverage
6. **Person whose caste was recently recategorized** — tests identity attribute mutation, retroactive eligibility
7. **Family that recently split** (joint to nuclear) — tests household unit duality, benefit fragmentation
8. **Minor dependent aging out of parent's scheme** — tests age-out transition, profile recertification
9. **Person with disability percentage change** — tests retroactive eligibility adjustment
10. **Gig worker with no salary slip** (Zomato/Swiggy driver) — tests evidence gaps, platform transaction data as proof

### 4.2 30 Ambiguity Types Validation
For each of the 30 ambiguity types defined in the Ambiguity Map framework (see `docs/reports/insight-reports/insight-report-ambiguity-map.md`), verify:
- The parsing pipeline correctly flags the ambiguity when present in source data
- The matching engine handles it correctly (UNDETERMINED, not silent PASS/FAIL)
- The confidence score is appropriately penalized
- The output explanation surfaces the ambiguity to the user

### 4.3 Cross-Scheme Conflict Testing
- Test all known prerequisite chains (Scheme A requires card from Scheme B)
- Test all mutual exclusions (cannot hold Scheme C and D simultaneously)
- Test complementary scheme detection (eligible for E → should be recommended F)
- Verify the system never silently recommends conflicting schemes

### 4.4 Hidden Segment Audit
Three explicit audit questions for every anchor scheme:
- **Migrant Portability**: Does the benefit follow the person across state lines?
- **Home-Based Workers**: Does the scheme allow self-declaration without a formal employer?
- **Liveness Requirements**: Can it be done via digital API or does it require physical presence (Aadhaar Face Auth / thumbprint)?

### 4.5 Regression Test Suite
- Golden test set: 15 anchor schemes × 10 adversarial profiles = 150 test cases
- Each test case has expected output (qualified / near-miss / ineligible + specific rules)
- Automated regression: any change to rules or matching logic re-runs the full suite

### Deliverables
- 10 fully documented adversarial profiles with expected vs. actual results
- 30-ambiguity-type coverage report
- Cross-scheme conflict test results
- Hidden segment audit results per scheme
- Regression test suite (automated, runnable via `pytest`)
- Failure analysis: root causes, fixes applied, remaining known gaps

---

## PART 5: Conversational Interface

**Status**: ⬜ Not started
**Depends on**: Part 3 (matching engine)

### Core Functionality
Build a CLI or basic web UI where users describe their situation in natural language. The system asks intelligent follow-up questions. The conversation must work in Hindi. It must handle incomplete answers, contradictory answers, and users who don't know their own eligibility.

### 5.1 Natural Language Input Processing
- Accept freeform text descriptions of the user's situation
- Extract structured profile data (age, state, income, etc.) from unstructured input
- Detect gaps in the profile and generate contextual follow-up questions
- Handle contradictory inputs: ask clarifying questions instead of dropping data
- Adapt to user's knowledge level (don't assume they know government terminology)

### 5.2 Hindi Language Support
- Input acceptance in Hindi (Devanagari script)
- Question generation and response output in Hindi
- Transliteration support (Hindi ↔ English)
- Handle mixed-language input (Hinglish)
- Linguistic Translation Delta awareness: flag where Hindi/English legal text diverges

### 5.3 Intelligent Conversation Flow
- Progressive disclosure: ask only what's needed, in a logical order
- "What If" scenario mode: "What happens if I get a Jan Dhan account?" — re-run matching with modified profile
- Contradiction detection and resolution within the conversation
- Session management: track history, allow corrections, resume interrupted sessions

### 5.4 Output Presentation
- Present matching results in user-friendly language (not raw JSON)
- Highlight actionable next steps prominently
- Show confidence breakdowns in plain language
- Surface ambiguity warnings without causing confusion

### Deliverable
A complete architecture document with system diagram, three key technical decisions with rejected alternatives, and the two most critical production-readiness gaps.

---

## PART 6: Dynamic Infrastructure & Monitoring

**Status**: ⬜ Not started
**Depends on**: Parts 1, 2

### Problem This Solves
Government schemes change eligibility criteria frequently — income ceiling hikes, new state variations, scheme mergers, new notifications. Without automated monitoring and dynamic updates, the rule base becomes stale within weeks and produces silently wrong outputs.

### 6.1 Gazette Monitoring & Auto-Ingestion
- Monitor egazette.gov.in RSS/Atom feeds for new notifications
- Auto-detect eligibility-relevant changes (income ceiling changes, new schemes, scheme terminations)
- Parse new Gazette PDFs through the existing parsing pipeline (Part 2)
- Generate diff reports: what changed, which rules affected, which users impacted
- Version control: immutable rule snapshots with supersession chains

### 6.2 Policy-as-Code: Dynamic Rule Updates
- Move from static rule files to a dynamic rule engine that can hot-reload rule changes
- LLM-driven ingestion of Gazette PDFs into standardized DMN schemas
- State-specific rule variations: same scheme, different criteria across 28 states
- Rule change notifications: alert downstream systems (matching engine, conversational layer) of updates

### 6.3 Dormant Scheme Detection
- Periodic cross-reference against Dataful.in fund release data
- Auto-flag schemes with zero fund releases or no active beneficiaries in 2+ years
- Prevent matching engine from recommending dormant schemes
- Generate "scheme health" dashboard

### 6.4 Data Freshness & Staleness Tracking
- Every rule carries `last_verified` timestamp
- Auto-flag rules not verified in >90 days
- Staleness dashboard: which schemes need re-verification
- Priority queue: re-verify anchor schemes first

### Deliverables
- Gazette monitoring service (automated, scheduled)
- Rule versioning system with full change history
- Staleness tracking and alerting
- Dormant scheme filter (auto-updated)
- Diff reports for rule changes

---

## PART 7: B2B Middleware & Extended Use Cases

**Status**: ⬜ Not started
**Depends on**: Parts 3, 5, 6

### Problem This Solves
Individual citizen access is Part 5's job. But the biggest impact comes from embedding welfare eligibility into platforms where workers already exist — gig platforms, small businesses, migrant worker networks. This Part builds the middleware APIs and integrations that make that possible.

### 7.1 Welfare-as-a-Benefit (WaaS) API
- B2B API for platforms (Zomato, Swiggy, Flipkart, Urban Company) to check worker eligibility
- "Welfare Button" for small businesses: automated social security enrollment for employees
- Bulk eligibility checking: process thousands of workers in a single API call
- Privacy-preserving: return eligibility results without exposing worker PII to the platform

### 7.2 Migrant Worker Portability API
- Solve the "Welfare Dark Zone" for interstate migrant workers
- Input: worker's home state documents + current state of residence
- Output: which schemes apply in current state, which home-state benefits are portable
- Handle seasonal migration patterns and temporary residency proof
- Reverse lookup: "I'm in Karnataka with Bihar documents — what can I get?"

### 7.3 Platform Transaction Data as Social Proof
- Use gig worker transaction history (UPI, bank settlements) as income proof
- Replace salary slip requirement with platform transaction data for schemes like PM SVANidhi
- Validate income tier claims via transaction patterns
- Privacy-preserving: aggregate proof ("income < 2L") without exposing transaction details

### 7.4 Federated Eligibility Checking
- Query multiple government registries simultaneously (Aadhaar, Farmer Registry, Ration Card APIs)
- Triangulate eligibility without storing sensitive data centrally
- Consent-based data fetch across registries
- Handle timeout/unavailability of individual registries gracefully
- No central master database — federated by design

### 7.5 Zero-Knowledge Proof (ZKP) for Eligibility Verification
- Verify eligibility claims (e.g., "Income < 2L") without exposing private financial data
- Account Aggregator framework integration for secure proof generation
- Workflow: Issuer (Government) → Wallet/Verifier (Middleware) → Proof of Eligibility → Welfare Department
- Support for multiple proof types: income, land ownership, caste, disability

### 7.6 Beckn Protocol Integration
- Adopt Beckn Protocol to unbundle the welfare stack
- Enable interoperability: buyer apps (startups) handle UI/Discovery, government handles Registry/Fulfillment
- Design schema to be Beckn-compliant from the outset
- Common Welfare Architecture: data flow via Account Aggregators, eligibility flow via Rule Engines, seamlessly across all 28 states

### 7.7 Grievance & Escalation API
- Address the "Grievance Black Hole" — applications stuck in "pending" for months
- Track application status across government portals
- Automated escalation: route unresolved cases to higher authority after timeout
- Status notifications to applicants
- Public dashboard for grievance transparency

### 7.8 Workflow API Integration ("Apply Once")
- Move beyond document discovery to actual application submission
- Automated form filling and submission via government portal APIs (where available)
- Fallback: RPA/Playwright-based submission for portals without APIs (acknowledge brittleness)
- Track application status post-submission
- Distinguish Document APIs (DigiLocker) from Workflow APIs (application submission)
- Handle Authorized Agent liability requirements

### Deliverables
- WaaS API specification and reference implementation
- Migrant Portability API
- Federated eligibility checking prototype
- ZKP eligibility verification proof-of-concept
- Beckn-compliant schema and integration guide
- Grievance tracking system
- "Apply Once" workflow for top 5 anchor schemes

---

## PART 8: Production Readiness & Architecture Documentation

**Status**: ⬜ Not started
**Depends on**: All previous Parts

### 8.1 System Architecture Document
- Complete system diagram: all components, data flows, external integrations
- Architecture Decision Records (ADRs) for all key decisions across all Parts
- Database/data structure design documentation
- Deployment architecture (infrastructure, scaling, monitoring)

### 8.2 Security & Privacy
- DPDPA (Digital Personal Data Protection Act) compliance review
- PII handling audit: verify stateless evaluation, no data-at-rest for user profiles
- API security: authentication, rate limiting, input validation
- Liveness/Physicality verification: document which schemes require Aadhaar Face Auth / thumbprint vs. digital-only

### 8.3 Identified Constraints & Hard Blockers
- Identify constraints & hard blockers of your implementation in a high-level format.

### 8.4 Production Readiness Gap Analysis
- Gap 1: [Most critical issue — TBD after implementation]
- Gap 2: [Second most critical — TBD]
- Gap 3+: Other blocking issues
- Mitigation plan for each gap

### 8.5 Edge Case Documentation
- Full results from all 10 adversarial profiles (from Part 4)
- Failure analysis for each profile
- Known limitations and failure modes
- Coverage report: which of the 30 ambiguity types are handled vs. outstanding

### Deliverables
- Architecture document with system diagrams
- 3+ ADRs with rejected alternatives documented
- Security and privacy compliance report
- Production readiness gap analysis
- Complete edge case documentation

---

## Cross-Cutting Concerns (Apply to All Parts)

### Explainability Requirements
- Every output must be traceable to rule evaluations
- No black boxes — confidence scores must explain their basis
- Users must understand why they do/don't qualify
- All decisions logged for auditability

### Accuracy & Uncertainty
- Fail clearly on ambiguous data (don't silently guess)
- Flag hallucinations before providing false answers
- Distinguish "definitely qualifies" vs "probably qualifies" vs "unclear"
- Document all assumptions and uncertain inferences

### Data Integrity
- All eligibility rules tied to source documents
- No fabrication of government requirements
- Version control on document parsing
- Audit trail for rule changes

---

## Key Insight Reports (Must-Read for All Agents)

⚠️ **SOURCE OF TRUTH**: Insight reports + `high-level-features-checklist.md` ARE THE ULTIMATE SOURCE OF TRUTH when conflicts arise with specs.

These reports contain novel ideas and deep analysis that must inform implementation decisions. Agents should not ignore these during implementation. When an insight report contradicts a spec, **the insight report wins** — it represents deeper analysis and architectural thinking.

| Report | Key Insights | File |
|--------|-------------|------|
| Initial Landscape | Fulfillment > Discovery; Beckn Protocol; Federated Eligibility; ZKP | `docs/reports/insight-reports/insight-report-initial.md` |
| Ambiguity Map | 30 Ambiguity Types; DMN over JSON; Gray Area Flags; Hidden Segment Audit; Reverse-Audit workflow | `docs/reports/insight-reports/insight-report-ambiguity-map.md` |
| Scheme Data | Three-Tier Sourcing; Kaggle shortcut; Parsing Agent batches; Dormant vs Active schemes; API Setu variable alignment | `docs/reports/insight-reports/insight-report-scheme-data.md` |

**Features Checklist** (`docs/high-level-features-checklist.md`): Authoritative list of 14 novel features that differentiate this project from existing solutions. When a feature appears in the checklist, it MUST be implemented — do not treat it as optional.

### Novel Features That Must Be Implemented (Not Optional)

These features were surfaced in insight reports and the high-level features checklist. They are not "nice-to-haves" — they are differentiators that separate this project from existing solutions like myScheme:

1. **30 Ambiguity Types Framework** — Systematic edge-case detection (Part 1, validated in Part 4)
2. **Hidden Segment Audit** — Explicit checks for migrants, home-based workers, domestic workers (Part 4)
3. **Gray Area Flags Table** — Structured surface of vague/missing details in government PDFs (Part 1)
4. **Scheme Relationship Taxonomy** — Prerequisites, mutual exclusions, complementary schemes (Part 1, used by Part 3)
5. **"What If" Scenario Testing** — User asks "what if I opened a bank account?" and sees updated results (Part 5)
6. **Dormant Scheme Detection** — Don't recommend dead schemes (Part 6)
7. **Gazette Auto-Ingestion** — Automatic rule updates when government publishes new notifications (Part 6)
8. **Platform Transaction Data as Income Proof** — Gig workers prove income via UPI history (Part 7)
9. **Migrant Worker Portability** — Benefits that follow workers across state lines (Part 7)
10. **Zero-Knowledge Eligibility Proofs** — Verify "income < 2L" without exposing financial data (Part 7)
11. **Federated Eligibility Checking** — Query multiple registries without central data store (Part 7)
12. **Beckn Protocol Integration** — Interoperable welfare stack (Part 7)
13. **Grievance Escalation API** — Track and escalate stuck applications (Part 7)
14. **Reverse-Audit Workflow** — Source Anchor links proving AI-generated logic matches official PDFs (Part 1)
