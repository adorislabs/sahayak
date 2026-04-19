# Quick Start: Framework Paradox Fix + Opus Audits

## ⚠️ SOURCE OF TRUTH (READ FIRST)

When docs conflict, resolve in this order:

1. **`docs/high-level-features-checklist.md`** ← AUTHORITY (features MUST be implemented)
2. **`docs/reports/insight-reports/`** ← DEEP ANALYSIS (insights override specs)
3. **`partX-planning/spec/`** ← Reference (can be outdated)
4. **`docs/project-overview.md`** ← Vision

**If a spec contradicts an insight report or features checklist: follow the insight/checklist.**

---

## ⚠️ Directory Structure (Critical)

**Reference & Anchoring** (`/docs/`, `/framework/`)
```
/docs/
  ├── reports/          ← All LLM audit outputs
  └── part1-planning/   ← Specs for reference only (read-only)

/framework/
  ├── guides/           ← Workflow principles
  ├── checklists/       ← Validation gates
  └── prompts/          ← Agent prompts
```
**No code generation in `/docs/` or `/framework/`**

**Work & Implementation** (`/part1-planning/` at ROOT)
```
/part1-planning/
  ├── ARCHITECTURE-CONTRACT.md  ← Phase 0 lockdown (human)
  ├── spec/                     ← Specs (from docs, copied for reference)
  ├── tests/                    ← Agent A output (test code)
  ├── src/                      ← Agent B output (implementation)
  └── farts/                    ← Session tracking
```
**All work happens here**

---

## What Changed

### 1. Framework Paradox Fixed
**Before**: Agent A writes tests → Agent B chooses framework → Tests fail because interface mismatch

**After**: Phase 0 locks architecture → Agent A writes tests to contract → Agent B implements contract → Tests pass

### 2. New Files Created

| File | Purpose | Location |
|------|---------|----------|
| `phase-0-architecture-contract.md` | Template for locking language, framework, signatures | `framework/prompts/` |
| `OPUS-FRAMEWORK-AUDIT.md` | Prompt for Opus to audit framework solidity | `framework/prompts/` |
| `OPUS-SPECS-AUDIT.md` | Prompt for Opus to audit specs & implementation plan | `docs/` |
| `FRAMEWORK-PARADOX-FIX.md` | Full explanation of the fix | `docs/` |

### 3. Updated Prompts

| File | Change |
|------|--------|
| `agent-a-test-writer.md` | Added Phase 0: Lock architecture before writing tests |
| `agent-b-implementer.md` | Added Phase 0: Read locked contract before implementing |

---

## Before You Start Part 1: Run 3 Audits

### Audit 1: Framework Solidity (30 min)

```
What to do:
1. Copy: framework/prompts/OPUS-FRAMEWORK-AUDIT.md
2. Paste into Claude (use Opus if available)
3. Include: /cbc/framework/ folder structure + key files
4. Ask: Run the 10 questions from the prompt
5. Fix: Any Critical/High severity issues

Success: Opus says "Framework is solid, ready to use"
```

### Audit 2: Specs & Implementation Plan (30 min)

```
What to do:
1. Copy: docs/OPUS-SPECS-AUDIT.md
2. Paste into Claude (use Opus if available)
3. Include: part1-planning/spec/ + part1-planning/implementation-plan.md
4. Ask: Run the 10 questions from the prompt
5. Fix: Any Critical/High severity issues

Success: Opus says "Specs are clear, testable, and aligned"
```

### Audit 3: Create Architecture Contract (1-2 hours)

```
What to do:
1. Copy: framework/prompts/phase-0-architecture-contract.md
2. Fill in:
   - Language: Python? JavaScript? Rust?
   - Framework: FastAPI? Raw asyncio? Express?
   - Function signatures (exact names, types, exceptions)
   - Data boundaries (input/output formats)
   - Quality assumptions (async? DB? coverage?)
3. Get human approval
4. Save as: part1-planning/ARCHITECTURE-CONTRACT.md
5. Lock it (mark read-only if possible)

Success: ARCHITECTURE-CONTRACT.md exists and is approved
```

---

## Then: Start Implementation

### Phase 1: Agent A (Test Writer)

```
Use: framework/prompts/agent-a-test-writer.md
Read first:
  - part1-planning/ARCHITECTURE-CONTRACT.md
  - All 8 specs (spec/01-08.md)
  - Insight reports (docs/insight-reports/)

Write:
  - Test specs in pseudocode (not real code)
  - Test fixtures (sample data)
  - One test spec file per spec (spec_01_data_sourcing.md, etc.)

Output location: part1-planning/tests/

Lock: Freeze test specs (no changes)
Time: 6-8 hours
```

### Phase 2: Agent B (Implementer)

```
Use: framework/prompts/agent-b-implementer.md
Read first:
  - part1-planning/ARCHITECTURE-CONTRACT.md (locked by Agent A)
  - part1-planning/tests/ (locked specs)

Steps:
  1. Convert pseudocode specs to actual test code
  2. Implement code to pass tests (TDD: Red → Green → Refactor)
  3. Ensure quality (type hints, docstrings, error handling)
  4. Run final audit: docs/OPUS-SPECS-AUDIT.md on code + tests

Output location: part1-planning/src/

Lock: Code review + merge
Time: 8-12 hours
```

---

## Key Files to Reference

### Framework (agents read these)
- `framework/guides/` — Principles, architecture, workflow, escalation
- `framework/checklists/` — Agent restrictions, code quality, escalation triggers
- `framework/prompts/` — Agent A, Agent B, Phase 0 architecture contract
- `framework/templates/` — Blurts, checkpoints, insight reports

### Project Context (agents read these)
- `docs/project-overview.md` — CBC mission & structure
- `docs/agent-style.md` — Code conventions
- `docs/insight-reports/` — Project insights & ambiguities

### Part 1 Planning (agents read/write these)
- `part1-planning/spec/` — 8 locked specifications
- `part1-planning/implementation-plan.md` — Phased roadmap
- `part1-planning/ARCHITECTURE-CONTRACT.md` — **NEW: Locked by Phase 0**
- `part1-planning/tests/` — Test specs (written by Agent A)
- `part1-planning/src/` — Implementation code (written by Agent B)
- `part1-planning/farts/` — Session tracking (blurts + checkpoints)

---

## Summary

| Step | Who | Output | Time |
|------|-----|--------|------|
| Audit 1: Framework | You | Issues fixed | 30 min |
| Audit 2: Specs | You | Issues fixed | 30 min |
| Phase 0: Contract | You + Agent A | ARCHITECTURE-CONTRACT.md | 1-2 hours |
| Phase 1: Tests | Agent A | test_specs/ (pseudocode) | 6-8 hours |
| Phase 2: Code | Agent B | src/ (implementation) | 8-12 hours |

**Total**: ~20-30 hours to working code (including audits)

---

## Status Check

- [x] Framework created (guides, checklists, prompts, templates)
- [x] Framework paradox fixed (Phase 0: Architecture Contract)
- [x] Opus audit prompts created (framework + specs)
- [x] Agent prompts updated (Phase 0 added)
- [x] Ready for audits
- [ ] Run Audit 1 (Framework)
- [ ] Run Audit 2 (Specs)
- [ ] Create Phase 0 contract
- [ ] Agent A writes tests
- [ ] Agent B implements code

**Next**: Copy OPUS-FRAMEWORK-AUDIT.md prompt, paste framework folder into Opus, get audit report.
