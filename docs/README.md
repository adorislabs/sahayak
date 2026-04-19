# Claude Builder Club (CBC) Documentation & Framework

Central reference for the entire Claude Builder Club project: multi-part data structuring for Indian welfare schemes.

---

## ⚠️ SOURCE OF TRUTH HIERARCHY

**When documents conflict, resolve in this order:**

1. **`high-level-features-checklist.md`** ← AUTHORITY (features MUST be implemented)
2. **`reports/insight-reports/`** ← DEEP ANALYSIS (insights override specs)
3. **`partX-planning/spec/`** ← Reference (can be outdated, consult insights first)
4. **`project-overview.md`** ← Vision

**Rule**: If a spec contradicts an insight report or the features checklist, **follow the insight/checklist**.

This ensures we implement what actually matters (insights + defined features) rather than getting stuck on spec details that may be outdated.

---

## ⚠️ Key Distinction: Reference vs. Work

**`/docs/` Layer** (Reference/Anchoring Only)
- Framework guides, prompts, checklists
- Project specs and overview
- All LLM audit reports
- **No code generation here — read only**

**`/part{{PART_NUMBER}}-planning/` Layer** (Work/Implementation — at ROOT)
- Architecture contract (Phase 0)
- Test specifications (Agent A)
- Implementation code (Agent B)
- Session tracking (farts/)
- **All actual work happens here**

---

## Project Overview

**What**: CBC = Claude Builder Club  
**Goal**: Structure 28-state welfare schemes into machine-readable eligibility rules  
**Approach**: Multi-part system with reusable framework + part-specific specs  

See [project-overview.md](project-overview.md) for full context.

---

## Structure at a Glance

```
cbc/ (project root)
├── framework/ ← UNIVERSAL (same for all parts)
│   ├── guides/ (7 guides + INDEX)
│   ├── checklists/ (6 universal checklists)
│   ├── prompts/ (Agent A/B prompts + Phase 0)
│   └── templates/ (4 session templates)
│
├── docs/ ← PROJECT-WIDE (for all parts)
│   ├── README.md ← You are here
│   ├── project-overview.md ← Big picture
│   ├── agent-style.md ← Code conventions
│   ├── feats-log.md ← What's been built
│   ├── high-level-features-checklist.md ← Feature tracking
│   │
│   └── reports/ ← ALL LLM REPORTS & ANALYSIS
│       ├── INDEX.md ← Reports navigation
│       ├── framework-audits/ (audit templates & guides)
│       │   ├── OPUS-FRAMEWORK-AUDIT.md
│       │   └── OPUS-SPECS-AUDIT.md
│       ├── audit-results/ (generated audit reports)
│       │   └── OPUS-SPECS-AUDIT-RESULTS.md
│       └── insight-reports/ (domain research & analysis)
│           ├── INDEX.md
│           ├── insight-report-initial.md
│           ├── insight-report-ambiguity-map.md
│           └── insight-report-scheme-data.md
│
├── part1-planning/ ← PART 1 (Data Structuring)
│   ├── README.md ← Part 1 overview
│   ├── spec/ (01-08 specs)
│   ├── checklists/ (00-09 phase checklists)
│   ├── farts/ (sessions)
│   ├── 00-overview.md ← Part 1 goals
│   └── implementation-plan.md ← Part 1 roadmap
│
├── part2-planning/ (same structure, coming soon)
├── part3-planning/ (same structure, coming soon)
└── ...
```

---

## Quick Navigation by Role

### For Agents (Coding)

**First Time?**
1. Read [project-overview.md](project-overview.md) (5 min)
2. Read [framework/guides/](../framework/guides/) (40 min)
3. Read `part1/docs/` to focus on part 1
4. Start coding following framework checklists

**Starting a Session?**
1. Check [framework/checklists/agent-restrictions.md](../framework/checklists/agent-restrictions.md)
2. Create session folder in `partX/farts/[date]-run-###/`
3. Copy templates from `framework/templates/`
4. Follow [framework/checklists/two-agent-testing.md](../framework/checklists/two-agent-testing.md)

**Before Shipping?**
1. Run [framework/checklists/code-quality.md](../framework/checklists/code-quality.md)
2. Use phase checklists from `partX/docs/checklists/`

---

## Framework (Reusable Across All Parts)

The framework is the **backbone** for all parts. Every agent learns it once.

### Guides (How to Work)
- [framework/guides/principles.md](../framework/guides/principles.md) — Code quality standards
- [framework/guides/architecture.md](../framework/guides/architecture.md) — Scalability patterns
- [framework/guides/context-handling.md](../framework/guides/context-handling.md) — Reading specs
- [framework/guides/workflow.md](../framework/guides/workflow.md) — Blurts & checkpoints
- [framework/guides/escalation.md](../framework/guides/escalation.md) — Self-awareness

See [framework/guides/INDEX.md](../framework/guides/INDEX.md) for quick reference.

### Checklists (Actionable)
- [framework/checklists/agent-restrictions.md](../framework/checklists/agent-restrictions.md) — Archive rules, project restrictions
- [framework/checklists/code-quality.md](../framework/checklists/code-quality.md) — Pre-ship quality gates
- [framework/checklists/escalation-trigger.md](../framework/checklists/escalation-trigger.md) — Decision tree
- [framework/checklists/two-agent-testing.md](../framework/checklists/two-agent-testing.md) — TDD workflow
- [framework/checklists/pre-commit.md](../framework/checklists/pre-commit.md) — Detailed review

### Templates
- [framework/templates/blurts.md](../framework/templates/blurts.md) — Session thinking notes
- [framework/templates/checkpoint.md](../framework/templates/checkpoint.md) — Resume point

---

## Project Context (All Parts Use These)

### [Reports Folder](reports/)
**What's in it**: LLM-generated reports organized by type (framework audits, spec audits, audit results, insight reports)  
**Read when**: Before implementation (audits) and during planning (insights)  
**Structure**:
- `reports/framework-audits/` — Templates for framework & spec audits
- `reports/audit-results/` — Generated audit reports (read before Agent A starts)
- `reports/insight-reports/` — Domain research, brainstorm insights, decision history

**For Part 1 agents**: See [reports/INDEX.md](reports/INDEX.md) for guidance  
**Purpose**: Audits verify framework/specs are solid; insights provide domain context  
**Time**: ~1 hour (audits) + 15 min (insights per part)

### [project-overview.md](project-overview.md)
**What's in it**: CBC mission, why it matters, 28-state scope, three-tier data sourcing  
**Read when**: First time working on any part  
**Time**: 10 min

### [agent-style.md](agent-style.md)
**What's in it**: Python conventions, naming, type hints, documentation style  
**Read when**: Before coding for the first time  
**Time**: 5 min

### [feats-log.md](feats-log.md)
**What's in it**: Completed features, blockers, architectural decisions  
**Read when**: Resuming after time away; checking what's done  
**Time**: 5 min

---

## Part 1: Data Structuring

**Focus**: Convert 28-state schemes → machine-readable eligibility rules  
**Specs**: 8 documents (data sourcing, parsing, schema, rule expression, ambiguity, etc.)  
**Status**: In planning/specification phase  

**Start here**: [../part1-planning/README.md](../part1-planning/README.md)

---

## Part 2, Part 3, etc. (Coming Soon)

When new parts are created:
1. Create `partX/docs/` following part1 structure
2. Use framework (guides, checklists, templates) unchanged
3. Create part-specific specs and checklists
4. Update this file to reference new parts

---

## How to Use This Folder

### If You're New to CBC
1. Read [project-overview.md](project-overview.md)
2. Read [agent-style.md](agent-style.md)
3. Go to [part1-planning/README.md](part1-planning/README.md)
4. Follow that part's onboarding

### If You're Returning
1. Check [feats-log.md](feats-log.md) for recent progress
2. Find your part (part1, part2, etc.)
3. Read that part's README.md
4. Follow session restoration in `partX/farts/`

### If You're Creating a New Part
1. Create `partX/docs/` folder
2. Copy structure from `part1/docs/`
3. Create part-specific specs
4. Reference framework from `../../framework/`
5. Update this file to mention new part

---

## Key Concepts

### The Framework (Universal)
- **Same for all parts**
- Guides, checklists, templates
- Reusable across projects
- Change very rarely (only if all parts affected)

### Project Context (Shared)
- **Same for all parts**
- project-overview.md, agent-style.md, feats-log.md
- Shared conventions, big picture, progress
- Updated when milestones hit

### Part-Specific Content
- **Different for each part**
- Specs (what to build)
- Phase checklists (00-09)
- Sessions (farts/, work tracking)
- Implementation (src/, tests/)

---

## Restrictions for Agents

⛔ **NO ARCHIVE ACCESS** — Do not access `/archive/` unless told explicitly.

📌 **READ FIRST** — Every session, read [framework/checklists/agent-restrictions.md](../framework/checklists/agent-restrictions.md).

✅ **FOLLOW FRAMEWORK** — Use framework guides, checklists, templates for all parts.

📂 **RESPECT PARTS** — Part 1 specs are locked (reference only); only modify part-specific checklists/sessions.

---

## Contact / Questions

If unclear about structure:
1. Check [framework/guides/escalation.md](../framework/guides/escalation.md) for guidance
2. Follow [framework/checklists/escalation-trigger.md](../framework/checklists/escalation-trigger.md)
3. Read relevant part's README (e.g., [part1-planning/README.md](part1-planning/README.md))

---

## Summary

| Location | Purpose | Read? | Modify? |
|----------|---------|-------|---------|
| `framework/` | Universal (all parts) | Yes | Rare (affects all parts) |
| `docs/project-overview.md` | Big picture | Yes, first | Never (locked) |
| `docs/agent-style.md` | Code conventions | Yes, before coding | Never (locked) |
| `docs/feats-log.md` | Progress tracking | Yes, when returning | Update as you go |
| `partX/docs/spec/` | Part specs | Yes, reference only | Never (locked) |
| `partX/docs/checklists/` | Phase checklists | Yes, before each phase | Part-specific |
| `partX/farts/` | Session tracking | Yes, your sessions | Update continuously |

---

**Last Updated**: April 16, 2026  
**Framework Status**: Ready for multi-part development ✅  
**Parts in Use**: Part 1 (planning/spec) → More coming
