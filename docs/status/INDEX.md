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
| `RESUME-NEXT-SESSION.md` | 🟢 active | Latest official25 receipt29.83/54officiallevels, ready-only183-level console, continuing two-game local research and current console deployment/verification boundaries. |
| `CURRENT-STATE.md` | 🟢 active | Structural snapshot. |
| `DCI-BENCHMARK-INSTANCES.md` | 🟢 active | DCI benchmark implementation and verification backlog. |
| `PATHLIGHT-DCI-DIAGNOSIS.md` | 🟢 active | Provider-free six-run DCI Pathlight diagnosis; safe numeric observations and unapproved follow-up proposals. |
| `PRIME-PARITY-LEDGER.md` | 🟡 decision-history | Pinned Prime-Gateway parity baseline and evidence; historical after native detachment (2026-09-14); `asterion.native` rows remain Missing. |
| `PRIME-TYPICAL-APPLICATIONS.md` | 🟡 decision-history | Historical Prime-backed P1-P7 behavior and traces; not native Asterion Prime closure. |
| `FRAMEWORK-INTEGRATION-WORKLIST.md` | 🟡 decision-history | Completed framework integration worklist; superseded as active route by the 2026-09-12 native reset. |
| `FRAMEWORK-PUBLIC-INVENTORY.md` | 🟢 active | Metadata-only inventory of application providers, capability refs, AgentRuntime IDs, separate control providers, and evidence boundaries. |
| `ASTERION-PRIME-P7-EVIDENCE.md` | 🟢 active | Native P7 evidence, official partial card, level results, world-model diagnosis, breadth recovery and realtime console process evidence and independent playable selection, direct human levels, remembered selection, reliable action feedback, manual history, per-level HUMAN save/resume and current-level clear/restart. |
| `../guides/pathlight-operator-guide.md` | 🟢 active | 中文 Pathlight 操作者手册：观察、追踪、评估、优化、Dashboard 与 Opik。 |
| `../guides/prime-p7-games-and-official-results.md` | 🟢 active | P7 本地题目、实时自主控制台、离线单 HTML 回放与官方结果操作指南。 |
| `DECISIONS.md` | 🟢 active | Native decisions: durable prepared replay/initial views, compact loading feedback, actor-sourced action meanings, partial cognition, generic Prime computation/P7 WorldMap ownership, semantic plan admission and independent HUMAN play/save behavior. |
| `../architecture/prime-p7-cognition-and-experience.md` | 🟢 active | Retained legacy cognition contract; the approved WorldMap/Prime redesign is authoritative for the default solver. |
| `../reviews/2026-10-05-p7-worldmap-solving-design-review.md` | 🟢 active | Pinned Tycho/Retrodict code comparison supporting the approved design; static research, not capability PASS. |
| `../reviews/2026-10-05-p7-worldmap-implementation-review.md` | 🟢 active | Implementation review, corrected integration boundaries, background console verification and packaged live evidence. |
| `../superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md` | 🟢 active | Prime/P7 solver, console and experience reuse worklist; console verified, current failure-experience and deployment evidence are indexed in the active checkpoint. |
| `../superpowers/specs/2026-10-05-p7-worldmap-solver-redesign.md` | 🟢 active | Whole solver/console redesign, evidence reuse and source-bound save-time replay preparation and ready-only25-game/183-level initial views; evaluation/deployment boundaries remain in the active checkpoint. |
| `../superpowers/specs/2026-10-05-prime-p7-console-modes-design.md` | 🟢 active | Approved P7-first design; packaged realtime decisions/actions/cognition and stop/cleanup verified; full gate non-PASS; independent manual play/direct levels, remembered choice, reliable controls and durable per-level HUMAN save/resume/history verified; current-level clear/restart verified; cooperative pause is implemented by the WorldMap solver/control redesign. |
| `PRIME-P1-P7-ACCEPTANCE.md` | 🟢 active | P1–P7 验收指南；记录 P7 组合失败与专用 provider 修复，区分无模型验证与真实求解。 |
| `climb/` | 🟢 active | Prime autonomous verification loop state; read `research-tree.md` on resume. |
| `INDEX.md` (this file) | 🟢 active | Discovery hub. |

## Decision history (kept for traceability — verdicts may be outdated)

| File | Status | What it recorded | Outcome / supersession |
|---|---|---|---|
| `GIT-RECOVERY-CLOSURE-20260830.md` | 🟡 decision-history | Git recovery and worktree cleanup audit | Historical closure; current branch state is in `CURRENT-STATE.md`. |
| `../reviews/2026-09-22-architecture-and-execution-review.md` | 🟡 decision-history | Baseline design/code review, nine findings, provider-free reproductions, and prioritized repair plan | Implementation evidence is tracked in the active `RESUME-NEXT-SESSION.md`; the baseline reproductions do not prove current application capability. |

## Archived

| Bucket | Files | Notes |
|---|---|---|
| (empty initially) | | |

> When adding new archive buckets, append a row here pointing to `_archive/<label>/`. Do not list individual files.

## Don't add new files unless they fit one of the categories above

If you want to record a **finding/lesson** that's a long-lived project fact → write to `CLAUDE.md` (structural facts section). If it's collaboration meta-information → write to the project's memory store. If it's a complete audit / experiment report → write a `docs/status/<topic>.md` here AND add its INDEX row.
