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
| `DECISIONS.md` | 🟢 active | Indexed active architecture decisions and rationale. |
| `INDEX.md` (this file) | 🟢 active | Discovery hub. |
| `climb/research-tree.md` | 🟢 active | Generated Plan 4 task/hypothesis and in-flight summary. |
| `climb/session-state.json` | 🟢 active | Dynamic Plan 4 climb recovery state. |
| `climb/config.yaml` | 📦 storage | Provider-free Plan 4 climb adapter. |
| `climb/session-target.md` | 📦 storage | Machine-readable eight-task completion target. |
| `climb/hypotheses.yaml` | 📦 storage | Plan 4 task pool and append-only results. |
| `climb/runs.csv` | 📦 storage | Completed task-cycle ledger. |
| `climb/calibration.json` | 📦 storage | Explicitly empty online-calibration state. |
| `climb/pending-lb.json` | 📦 storage | Explicitly empty external-score queue. |
| `climb/adjudicator-log.md` | 📦 storage | Review/quorum decision history. |

## Decision history (kept for traceability — verdicts may be outdated)

| File | Status | What it recorded | Outcome / supersession |
|---|---|---|---|
| (empty initially) | | | |

## Archived

| Bucket | Files | Notes |
|---|---|---|
| (empty initially) | | |

> When adding new archive buckets, append a row here pointing to `_archive/<label>/`. Do not list individual files.

## Don't add new files unless they fit one of the categories above

If you want to record a **finding/lesson** that's a long-lived project fact → write to `CLAUDE.md` (structural facts section). If it's collaboration meta-information → write to the project's memory store. If it's a complete audit / experiment report → write a `docs/status/<topic>.md` here AND add its INDEX row.
