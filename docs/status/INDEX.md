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
| `../reviews/2026-10-08-p7-autonomous-bp35-comparison.md` | 🟢 active | Completed trial:2levels/166committed, stderr diagnostic overflow; L2 exploration regression, source-retrieval gap, exact replay/cleanup boundaries. |
| `../reviews/2026-10-08-p7-notes-bp35-comparison.md` | 🟢 active | Completed comparison: four levels/335 committed actions plus partial late response; actual ARC process, memory regression, clock limits and redesign direction. |
| `../superpowers/specs/2026-10-08-prime-research-notes-design.md` | 🟢 active | Implemented generic/P7 NOTES contract; post-trial research-gate/cut direction is revised by D-2026-10-08-02. |
| `../superpowers/plans/2026-10-08-prime-research-notes.md` | 🟢 active | NOTES implementation/r11l deployment and Task4 comparison closed; failure boundaries and unimplemented redesign criteria. |
| `../superpowers/plans/2026-10-07-prime-autonomous-research.md` | 🟡 decision-history | Completed cold BP35 comparison ended5/6; implementation and measurement boundaries. |
| `../reviews/2026-10-08-prime-autonomous-research-interface.md` | 🟢 active | Implemented autonomy/support layers; promotion/r11l verified; subsequent failed BP35 trial is separately indexed. |
| `../superpowers/specs/2026-10-08-prime-autonomous-research-interface-design.md` | 🟢 active | Authorized LLM-owned research interface and genuine execution boundaries. |
| `../superpowers/plans/2026-10-08-prime-autonomous-research-interface.md` | 🟢 active | Task5 interrupted target failure archived; Task7 generic computation/context continuity and P7 adaptation implemented, combined deployment verification active. |
| `JOURNAL.md` | 🟢 active | Append-only event log. `/project-state journal "..."` appends. |
| `RESUME-NEXT-SESSION.md` | 🟢 active | Live checkpoint: BP35 trial ended2levels/166actions, cleanup verified; logging/source-retrieval issues remain unimplemented. |
| `CURRENT-STATE.md` | 🟢 active | Structural snapshot, complete source-ancestry contracts, deployed/source repair distinction and unresolved SDK memory/reasoning boundaries. |
| `../superpowers/specs/2026-10-06-p7-dynamic-evidence-capacity.md` | 🟢 active | Complete dynamic animation storage, canonical hash identity, error stages and old-certificate compatibility design. |
| `../superpowers/plans/2026-10-06-p7-dynamic-evidence-capacity.md` | 🟢 active | Core/integration implementation and focused verification; exact deployment and finite BP/G live trial boundaries. |
| `../superpowers/specs/2026-10-06-p7-vercel-console-sync.md` | 🟢 active | User-authorized local-to-cloud readonly console synchronization boundary. |
| `../superpowers/plans/2026-10-06-p7-vercel-console-sync.md` | 🟢 active | Private Blob publisher, Vercel cloud reads and actual deployment acceptance. |
| `DCI-BENCHMARK-INSTANCES.md` | 🟢 active | DCI benchmark implementation and verification backlog. |
| `PATHLIGHT-DCI-DIAGNOSIS.md` | 🟢 active | Provider-free six-run DCI Pathlight diagnosis; safe numeric observations and unapproved follow-up proposals. |
| `PRIME-PARITY-LEDGER.md` | 🟡 decision-history | Pinned Prime-Gateway parity baseline and evidence; historical after native detachment (2026-09-14); `asterion.native` rows remain Missing. |
| `PRIME-TYPICAL-APPLICATIONS.md` | 🟡 decision-history | Historical Prime-backed P1-P7 behavior and traces; not native Asterion Prime closure. |
| `FRAMEWORK-INTEGRATION-WORKLIST.md` | 🟡 decision-history | Completed framework integration worklist; superseded as active route by the 2026-09-12 native reset. |
| `FRAMEWORK-PUBLIC-INVENTORY.md` | 🟢 active | Metadata-only inventory of application providers, capability refs, AgentRuntime IDs, separate control providers, and evidence boundaries. |
| `ASTERION-PRIME-P7-EVIDENCE.md` | 🟡 decision-history | Historical native implementation, partial-card and console acceptance evidence; final official result is in the result record and current handoff. |
| `../guides/pathlight-operator-guide.md` | 🟢 active | 中文 Pathlight 操作者手册：观察、追踪、评估、优化、Dashboard 与 Opik。 |
| `../guides/prime-p7-games-and-official-results.md` | 🟢 active | P7 本地题目、实时自主控制台、离线单 HTML 回放与官方结果操作指南。 |
| `../guides/prime-p7-community-reproduction.md` | 🟢 active | Producing-system setup, finite witness and certificate-bound official replay; no private roster bundled. |
| `../guides/prime-p7-private-research-archive.md` | 🟢 active | Offline private snapshots, exclusions, hashes, retention and isolated restoration. |
| `../results/arc-agi-3/README.md` | 🟢 active | Final official100 result, producing versions and scoped API-equivalent cost assumptions. |
| `DECISIONS.md` | 🟢 active | Native decisions, provenance and result/archive boundaries; D-2026-10-07-03/04 distinguish outer assistance, failed cold capability and layered research candidates. Includes historical D-2026-10-08-01 memory and current D-2026-10-08-02 LLM-owned research plus implementation/deployment boundaries. |
| `../architecture/prime-p7-cognition-and-experience.md` | 🟢 active | Retained legacy cognition contract; the approved WorldMap/Prime redesign is authoritative for the default solver. |
| `../reviews/2026-10-05-p7-worldmap-solving-design-review.md` | 🟢 active | Pinned Tycho/Retrodict code comparison supporting the approved design; static research, not capability PASS. |
| `../reviews/2026-10-07-arc-skill-autonomy-and-bp35-comparison.md` | 🟢 active | Original arc-skill/gpt-6.1-sol r11l: WIN/6of6/108actions after one generic continuation; BP35 outer assistance and concrete code/transcript comparison. |
| `../reviews/2026-10-07-arc-skill-bp35-l5-l6-trial.md` | 🟢 active | Fresh original-skill BP35 reaches6of9/271actions: L5=45/L6=102; outer P7 reasoning diagnosis, Git evidence and actual autonomous correction comparison. |
| `../reviews/2026-10-07-p7-cold-autonomy-bp35.md` | 🟢 active | Layered research implementation and frozen cold BP35 target6: deadline5completed/213paid, completed actual-process comparison: research nonconvergence, revision amplification, unused continuation, NOTES scale and external-memory/model-history mismatch. |
| `../reviews/2026-10-07-bp35-autonomy-explainer.html` | 🟢 active | Standalone offline interactive explanation: original arc-skill trajectory, outer diagnosis, layered implementation and nonrenewing budget; P7 target6 failure5/213 and interactive actual-process comparison; NOTES/current-memory versus execution-history audit; no new implementation claimed. |
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

Research memory implementation evidence: [generic/P7 NOTES](../reviews/2026-10-08-prime-research-notes.md).
