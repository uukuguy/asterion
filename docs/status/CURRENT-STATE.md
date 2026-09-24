# Current State

Updated 2026-09-24. This file is the structural snapshot; the active session checkpoint and next actions are in `RESUME-NEXT-SESSION.md`. Historical decisions and receipts remain in `DECISIONS.md`, `JOURNAL.md`, and the named evidence files.

## Project and authority

- Project route: managed. Canonical historical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`. Most recent work package: 2026-09-22 R1–R9 review remediation, integrated into main and not declared as a new numbered phase.
- Asterion is a composable, multi-runtime research framework. The root wheel and `src/asterion/` are authoritative. DCI is a reference product; Pi, data, credentials, generated evidence, and the parent DCI baseline are external.
- Python owns composition and orchestration, TypeScript validates shared contracts and Node integration, and Rust owns controlled execution. Framework modules remain product neutral. Applications select exact package and runtime bindings; runners execute an already resolved plan.
- Protocols `asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, and `asterion.application-assembly/v1` remain closed. The 2026-09-22 remediation does not introduce protocol v2.
- Host services and model configuration are operator owned and injected. Metadata listing, acceptance, preflight, and provider-free gates do not authorize Agent/Judge execution.

## Active work

- The nine findings and priorities are recorded in `../reviews/2026-09-22-architecture-and-execution-review.md`. Their implementation is on main; `.worktrees/review-implementation` retains the reviewed source branch.
- R1/R6 repair Pi prompt ownership through an exact request acknowledgment and settlement barrier, and normalize wire responses before optional event compaction. The Phase 10 shared-session draft is historical and must be corrected before implementation.
- R2 connects Prime P3/P5/P6 selected assemblies to executable capabilities, injected hosts, and sealed receipts. The 2026-09-24 bounded live presets now exercise those composition paths with model-produced task content. P6 cancellation after admission must either complete a verified inverse or mark recovery required; it cannot label unverified effects rolled back.
- R3/R4 bind composition to the validated package snapshot and reject self-consumed event/artifact cycles. R5 bounds Python/Rust executor cleanup. R7 adds private diagnostic correlation while retaining public redaction. R8 coalesces validated journal reads without changing the canonical journal. R9 narrows Prime inventory and module ownership.

## Evidence boundary

- The native detachment program and its historical P1–P7 receipts remain documented. “Implemented” means code and entry point exist; it does not establish every application’s current end-to-end capability.
- P1 has prior live receipts and a later real-model failure report. The repaired prompt boundary has focused simulated-producer tests and one bounded installed-wheel live completion on the reviewed branch. This is one preset run, not a reliability estimate.
- P2 has local retrieval and oracle evidence; a zero-token operator witness alone does not prove model long-context performance.
- P3/P5/P6 each completed one bounded local installed-wheel model run on 2026-09-24: P3 admitted child and root each used a separate Pi session; P5's first model proposal passed local semantic verification, so its live repair count is zero; P6 evaluated a model-proposed rule on untouched holdout values and explicitly promoted it at project scope. Their former deterministic runs remain under `-witness` targets. One passing preset is not a reliability estimate or general task capability.
- P4 completed bounded local installed-wheel commit/recover pairs in separate processes. The new session consumed a verified checkpoint transcript and sealed generation 2. A simulated transient model failure now preserves generation 1 for same-root retry. This proves the fixed task-state recovery preset, not arbitrary IPython memory restoration or broad cross-session reliability. P7 has a recorded, bounded ls20 Level-1 solve. A later tu93 attempt reached `GAME_OVER` after 50 actions without clearing Level 1. Local code preserves a separate timestamped directory for every retry and projects terminal evidence into failed receipts. P7 now accepts a target level and keeps solving sequentially from Level 1; the Level-2 path has installed-wheel deterministic evidence only, with no paid Level-2 solve.
- `make promotion-check` is required after package/assembly edits. Full benchmarks and paper reproduction remain outside this work and require separate finite authorization.

## Key paths

- `src/asterion/applications/provider.py`, `src/asterion/applications/prime/`, `src/asterion/capability_packages/`, `src/asterion/capabilities/`, `src/asterion/runner/`, `src/asterion/runtimes/pi_rpc.py`, `src/asterion/services/`, and `packages/rust/controlled-executor/` contain the relevant boundaries.
- `docs/status/INDEX.md` indexes active state and evidence. `docs/status/RESUME-NEXT-SESSION.md` records the current recovery point. `docs/status/ASTERION-PRIME-P7-EVIDENCE.md` contains the bounded P7 live evidence.

## Resume

Read `AGENTS.md`, `INDEX.md`, `RESUME-NEXT-SESSION.md`, then inspect `git status --short` and recent commits in both worktrees. Promote claims only to the exact boundary supported by a named command or receipt.
