# docs/status INDEX

Catalog of every file in `docs/status/`. Categorized so Claude knows which to read, which to skip, and which are decision history kept for traceability only.

**Status legend**:
- 🟢 **active** — read on resume; reflects current truth
- 🟡 **decision-history** — historical record of a decision/finding; don't act on the recommendations inside (they may be reversed by later sessions)
- 🔴 **superseded** — replaced by a newer file or by a memory entry; safe to ignore on resume
- ⚫ **scratch** — one-off experiment scratch / data dump; not meant to be read again

When adding a new file to `docs/status/`, **also add its row here** — otherwise it becomes orphan exhaust (HARD INVARIANT, see project-state skill).

## Active (read these on every resume)

| File | Status | Purpose |
|---|---|---|
| `JOURNAL.md` | 🟢 active | Append-only event log. `/project-state journal "..."` appends. |
| `RESUME-NEXT-SESSION.md` | 🟢 active | Session handoff baton. |
| `CURRENT-STATE.md` | 🟢 active | Structural snapshot. |
| `DCI-BENCHMARK-INSTANCES.md` | 🟢 active | DCI benchmark implementation and verification backlog. |
| `PATHLIGHT-DCI-DIAGNOSIS.md` | 🟢 active | Provider-free six-run DCI Pathlight diagnosis; safe numeric observations and unapproved follow-up proposals. |
| `PRIME-PARITY-LEDGER.md` | 🟢 active | Pinned Prime baseline, stable parity domains, evidence levels and provider gap status. |
| `PRIME-TYPICAL-APPLICATIONS.md` | 🟢 active | Canonical Prime seven-scenario closure worklist; Prime/Native parallel runtime scope, P1 resource aggregate verified, verified bundle admission, active Linux launch, scoped evidence and execution dependencies. |
| `../guides/pathlight-operator-guide.md` | 🟢 active | 中文 Pathlight 操作者手册：观察、追踪、评估、优化、Dashboard 与 Opik。 |
| `DECISIONS.md` | 🟢 active | Indexed active architecture, trust-boundary, cleanup, and Prime-first seven-scenario closure decisions. |
| `climb/` | 🟢 active | Prime autonomous verification loop state; read `research-tree.md` on resume. |
| `INDEX.md` (this file) | 🟢 active | Discovery hub. |

## Decision history (kept for traceability — verdicts may be outdated)

| File | Status | What it recorded | Outcome / supersession |
|---|---|---|---|
| `GIT-RECOVERY-CLOSURE-20260830.md` | 🟡 decision-history | Git recovery and worktree cleanup audit | Historical closure; current branch state is in `CURRENT-STATE.md`. |

## Archived

| Bucket | Files | Notes |
|---|---|---|
| (empty initially) | | |

> When adding new archive buckets, append a row here pointing to `_archive/<label>/`. Do not list individual files.

## Don't add new files unless they fit one of the categories above

If you want to record a **finding/lesson** that's a long-lived project fact → write to `CLAUDE.md` (structural facts section). If it's collaboration meta-information → write to the project's memory store. If it's a complete audit / experiment report → write a `docs/status/<topic>.md` here AND add its INDEX row.
