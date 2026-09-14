# Documentations — Index

| Document | Status | Notes |
|---|---|---|
| [`Agent_Harness_PRD_Developer_README.md`](Agent_Harness_PRD_Developer_README.md) | **AUTHORITATIVE — VERBATIM, READ-ONLY** | The provided project vision: complete PRD (Part 1) + Developer README (Part 2). Copied exactly as provided; never edited by any plan or agent (SPEC-000 § 3.6). |
| `architecture-notes.md` | Planned — Plan 5, sub-phase 4.3 | Layer map, dependency rule, composition-root explanation |
| `testing-guide.md` | Planned — Plan 5, sub-phase 4.3 | Unit vs integration, determinism rules, test-double conventions |

## Precedence

- The vision document wins on **product intent**.
- [`../spec/`](../spec/) wins on **interface detail and module boundaries** (it refines and
  partitions the vision into frozen, implementable contracts).
- Additions to this directory must never contradict either; conflicts are resolved via the
  Spec Change Request process (SPEC-000 § 7).
