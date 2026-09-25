# Current State

Updated 2026-09-25. This file is the structural snapshot; the active session checkpoint and next actions are in `RESUME-NEXT-SESSION.md`. Historical decisions and receipts remain in `DECISIONS.md`, `JOURNAL.md`, and the named evidence files.

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
- P4 completed bounded local installed-wheel commit/recover pairs in separate processes. The new session consumed a verified checkpoint transcript and sealed generation 2. A simulated transient model failure now preserves generation 1 for same-root retry. This proves the fixed task-state recovery preset, not arbitrary IPython memory restoration or broad cross-session reliability.
- P7 has a prior bounded LS20 Level-1 solve; a later TU93 attempt reached `GAME_OVER` after 50 actions without clearing Level 1. The local `p7-solve GAME=<id> [LEVEL=N]` selects a whole game or sequential target level; saved action prefixes are verified from private evidence and re-executed into a fresh game before the model continues. A later-level failure can retain the earlier completed levels in a separately sealed and replay-verified prefix; each run retains its own private directory. A GET-only sync fills the operator-owned 25-game official catalog. Official Competition support has a scoreless gameplay package, one-card selected-game coordinator, saved-action execution with initial and per-step verification, SDK result validation, and read-only closed-card recovery. One authorized LS20 submission created a real Competition card; the validated public result shows Level 1 completed in 20 actions and overall score 0.14285714285714285 across 25 games, with 24 unselected games at zero. This is a partial official score, not a complete LS20 game win. See the active checkpoint and `docs/guides/prime-p7-games-and-official-results.md` for commands and limits.
- P7 本地 2026-09-25 首关轮次已完成：原有 LS20、AR25 两题首关前缀之外，23 题各尝试一次，15 题新增已验证首关，8 题到人类动作基准仍未解；25 题中现有 17 题具有首关前缀，整题通关数为 0。本轮 23 条独立运行的回放、封存和清理均通过检查，累计上报输入 41,713,134、输出 1,547,660 token，输入包含缓存，不能据此计算费用。逐题结果与命令在 `docs/guides/prime-p7-games-and-official-results.md`。
- P7 新一张官方 Competition 卡将上述 17 题的已验证首关动作逐题重新执行并正常关闭；本地 `closed-confirmed` 回执记载官方总分 `2.5044733044733043`，17 题各完成 1 关、8 题未选，整题通关数仍为 0。卡号和逐题官方成绩在 `docs/status/ASTERION-PRIME-P7-EVIDENCE.md`。17 题各有已校验中文讲解与离线单文件 run-story 网页制品，另保留历史 LS20 页面；本地目录由 `make asterion-prime-p7-stories` 打开。
- The P7 gameplay package/assembly passed `make promotion-check` after its resource declaration was fixed: 25 isolated commands, zero provider operations. Full benchmarks and paper reproduction remain outside this work and require separate finite authorization.

## Key paths

- `src/asterion/applications/provider.py`, `src/asterion/applications/prime/`, `src/asterion/capability_packages/`, `src/asterion/capabilities/`, `src/asterion/runner/`, `src/asterion/runtimes/pi_rpc.py`, `src/asterion/services/`, and `packages/rust/controlled-executor/` contain the relevant boundaries.
- `docs/status/INDEX.md` indexes active state and evidence. `docs/status/RESUME-NEXT-SESSION.md` records the current recovery point. `docs/status/ASTERION-PRIME-P7-EVIDENCE.md` contains the bounded P7 live evidence.

## Resume

Read `AGENTS.md`, `INDEX.md`, `RESUME-NEXT-SESSION.md`, then inspect `git status --short` and recent commits in both worktrees. Promote claims only to the exact boundary supported by a named command or receipt.
