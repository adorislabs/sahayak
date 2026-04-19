# QA Audit for Data Structuring and Parsing

## AI

Now let me gather deeper context on all areas simultaneously:

---

## AI

Here is the full audit report:

---

# QA Audit Report — Parts 1 & 2 Combined
**Date:** 17 April 2026 | **Verdict: ❌ NOT READY TO SHIP**

---

## Quick Validation

| Check | Result |
|---|---|
| Tests pass (`pytest src/tests/ -v`) | ❌ **55 failed, 144 passed** (+ 9 collection errors) |
| All src modules present | ⚠️ **Partial** — 8 Part 1/2 modules present; `src/matching/` missing (Part 3) |
| `src/output/` exists with artifacts | ❌ **Directory does not exist** |
| `/src/output/PARSING-QUALITY-REPORT.md` | ❌ **Missing** |
| No TODO/FIXME in critical paths | ✅ None found |

---

## PART 1: Schema Completeness

### Schema Definition — ✅ MOSTLY COMPLETE

| Check | Result |
|---|---|
| Pydantic models: `Scheme`, `Rule`, `AmbiguityFlag`, `SchemeRelationship` | ✅ All defined in [src/schema.py](src/schema.py) |
| Rule has `rule_id`, `version`, `state_scope` | ✅ Present |
| Rule has `source_url` + `source_quote` | ✅ Via `SourceAnchor` (required field on `Rule`) |
| Rule has `source_section` | ⚠️ Lives as optional `SourceAnchor.section` — not a top-level `Rule.source_section` field |
| Rule has `last_verified` | ❌ **Missing** — only `notification_date` on `SourceAnchor` and `audit_status` on `Rule`; no `last_verified` timestamp |
| Immutable model (supersession chain) | ✅ `supersedes_rule_id` field present |
| DMN-renderable schema | ✅ `render_dmn_table()` / `render_dmn_row()` in [src/rule_expression.py](src/rule_expression.py) |

### Rule Base Population — ❌ NOT POPULATED

`src/output/` does not exist. No `rules/{scheme_id}.json` files. The implementation machinery is built but has never been run against real data. 0 of 15 anchor schemes processed.

### Ambiguity Map — ✅ IMPLEMENTATION COMPLETE, ❌ NOT POPULATED

| Check | Result |
|---|---|
| 30 Ambiguity Types enumerated | ✅ All 30 in `AMBIGUITY_TAXONOMY` (types 1–30) |
| `AmbiguityFlag` has `id`, `type`, `severity`, `description` | ✅ All present |
| `scheme_ids` (plural per spec) | ⚠️ Schema uses singular `scheme_id: str`, not `scheme_ids: List[str]` |
| Gray Area Flags / export functions | ✅ `export_ambiguity_map()` supports JSON/CSV/Markdown |
| `/src/output/ambiguity_map.json` + `.csv` | ❌ **Missing** — pipeline never run |

### Scheme Relationships — ✅ IMPLEMENTATION COMPLETE, ❌ NOT POPULATED

| Check | Result |
|---|---|
| PREREQUISITE, MUTUAL_EXCLUSION, COMPLEMENTARY, OVERLAP types | ✅ Documented on `SchemeRelationship.relationship_type` |
| Confidence scores | ✅ `confidence: float` on `SchemeRelationship` |
| `/src/output/relationships.json` | ❌ **Missing** |
| Hard-coded known admin rules (PMSYM/NPS/EPFO) | ❌ No `KNOWN_RELATIONSHIPS` constant in `scheme_relationships.py`; tests for PMSYM↔NPS, PMAY-G↔PMAY-U, EPFO↔PMSYM rely on runtime detection logic only |

### Data Integrity (Part 1) — ❌ CANNOT VERIFY

- No populated rule base = no rules to spot-check for hallucination
- No git repository (`fatal: not a git repository`) — version history requirement fails entirely

---

## PART 2: Parsing Pipeline

### Configuration — ✅

| Check | Result |
|---|---|
| Batch size 50 configured | ✅ `BATCH_SIZE=50`, `KAGGLE_BATCH_SIZE=50` in [src/config.py](src/config.py) |
| Sequential batch processing (no parallelism) | ✅ `for i in range(0, len(inputs), effective_batch_size): ... await dispatch_parsing_subagent(batch)` — sequential |
| Failed batches don't block subsequent ones | ✅ Per-scheme try/except in `dispatch_parsing_subagent()` |
| Review queue population | ✅ `review_queue` list in `RunManifest` |

### Quality Gate Thresholds — ⚠️ MISMATCH vs QA SPEC

| QA Spec says | Code implements |
|---|---|
| ≥0.95 → VERIFIED | ❌ `AUDIT_SIMILARITY_THRESHOLD = 0.90` (not 0.95) |
| 0.70–0.95 → NEEDS_REVIEW | ⚠️ 0.70–0.90 → NEEDS_REVIEW |
| <0.70 → DISPUTED | ✅ Correct |

The VERIFIED threshold is **0.90 in code vs 0.95 in the QA spec** — a real gap. Decide which is authoritative.

### Structured Output Fields — ⚠️ DESIGN MISMATCH

The QA spec expects per-rule flat fields (`age_min`, `age_max`, `residency`, `gender_req`, `income_ceiling`). The implementation encodes these structurally inside `Rule` objects (via `condition_type`, `field`, `operator`, `value`). No direct flat output with those field names. This may be intentional (more flexible) but diverges from the spec.

### All Output Artifacts — ❌ ALL MISSING

`src/output/` does not exist. None of these have ever been produced:
- `rules/{scheme_id}.json`
- `ambiguity_map.json` / `ambiguity_map.csv`
- `relationships.json`
- `dormant_schemes.json`
- `manifests/{run_id}.json`
- `review_queue.json`
- `PARSING-QUALITY-REPORT.md`

---

## Test Failures — Root Causes

### Category 1: Stale patch targets (52 failures across 5 files)

Tests use `patch("src.spec_01_data_sourcing.xxx")` but modules were implemented without the `spec_XX_` prefix. All 52 failures have **the same root cause**:

| Test file | Stale path | Correct path |
|---|---|---|
| [test_spec_01_data_sourcing.py](src/tests/test_spec_01_data_sourcing.py) | `src.spec_01_data_sourcing.*` | `src.data_sourcing.*` |
| [test_spec_02_parsing_agent.py](src/tests/test_spec_02_parsing_agent.py) | `src.spec_02_parsing_agent.*` | `src.parsing.*` |
| [test_spec_06_scheme_relationships.py](src/tests/test_spec_06_scheme_relationships.py) | `src.spec_06_scheme_relationships.*` | `src.scheme_relationships.*` |
| [test_spec_07_source_anchoring.py](src/tests/test_spec_07_source_anchoring.py) | `src.spec_07_source_anchoring.*` | `src.source_anchoring.*` |
| [test_spec_08_validation.py](src/tests/test_spec_08_validation.py) | `src.spec_08_validation.*` | `src.validation.*` |

This is a **mechanical fix** — a sed/rename pass across these 5 test files. No logic changes needed.

### Category 2: Missing `src/matching/` module (9 collection errors)

All tests in [src/tests/test_matching/](src/tests/test_matching/) fail to collect because `src.matching` doesn't exist. This is Part 3 — not yet started. Either skip this folder for now or mark it xfail.

### Category 3: Known relationships not hard-coded (3 failures in `TestKnownRelationships`)

`TestKnownRelationships` tests expect `detect_relationships("PMSYM", "NPS", ...)` to return MUTUAL_EXCLUSION purely from PMSYM's rules, but also depend on the stale patch path (Category 1). Fix Category 1 first, then re-check.

---

## Summary: What Blocks Ship

| Blocker | Severity | Fix |
|---|---|---|
| 52 test failures — stale `spec_XX_` patch paths | 🔴 CRITICAL | Rename patch targets in 5 test files |
| 9 test collection errors — `src.matching` missing | 🔴 CRITICAL | Skip or xfail `test_matching/` until Part 3 |
| `src/output/` empty — pipeline never run against real data | 🔴 CRITICAL | Run the pipeline against anchor schemes |
| No git repository | 🟡 HIGH | Initialize git and make incremental commits |
| `last_verified` field missing from `Rule` | 🟡 HIGH | Add to `Rule` or `SourceAnchor` schema |
| VERIFIED threshold: 0.90 (code) vs 0.95 (spec) | 🟡 HIGH | Resolve which is authoritative |
| `scheme_ids` (plural) on `AmbiguityFlag` | 🟠 MEDIUM | Align schema to spec or update spec |
| `ParseResult` flat fields (`age_min`, etc.) missing | 🟠 MEDIUM | Clarify whether Rule-based structure is accepted |
| No hard-coded `KNOWN_RELATIONSHIPS` | 🟠 MEDIUM | Add constant for PMSYM/NPS/EPFO admin rules |

**What's working well:** The schema design is solid, all 30 ambiguity types are implemented, batch sequencing is correct, quality gates are architecturally sound, and 144 tests pass — the core logic is good. The primary immediate fix is the stale patch targets in the test files.

---

## User

Fix all issues, audit the same. Ones that require Part 3 implementation will be alerted to you once Part 3 is done. Organise the codebase a bit. Really an eye-sore

---

## AI

Let me gather the context I need before making changes:

---

## AI

Now I have a clear picture. Let me check the `Scheme` model:

---

## AI

I have everything I need. Let me execute all the fixes now:

---

## AI

Good — all 0. Now skip the Part 3 test directory:

---

## AI

Now run the tests to see the current state:

---

## AI

199/199 passing. Now organize the codebase:

---

## AI

The root `part2-planning/` is the real data parsing pipeline planning (distinct from `docs/part2-planning/` which is the matching engine). Move root one under `docs/` with a clear name, and migrate the test architecture doc:

---

## AI

Now verify the root is clean and tests still pass:

---

