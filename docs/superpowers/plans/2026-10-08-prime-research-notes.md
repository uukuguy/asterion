# Prime research memory and P7 NOTES implementation plan

> Execute with subagent-driven-development; root integrates and Astra independently reviews the final changes.

**Goal:** Make model-curated current research memory actually control the LLM view while preserving queryable raw evidence.

**Architecture:** Domain-neutral immutable memory plus native Pi model-view projection; P7 binds current observations, workspace revisions and game lifecycle. Existing runner, bridge and three-tool registry remain authoritative.

**Tech stack:** Python unittest, TypeScript/Node extension tests, packaged wheel and installed Pi.

## Global constraints

- User-approved design: [research NOTES](../specs/2026-10-08-prime-research-notes-design.md).
- Free text at most16KiB UTF-8; no mandatory knowledge taxonomy, hardcoded BP35 rules or new runner.
- NOTES request exact keys: op/base_revision/observation_ref/text; existing workspace pointer is commit authority.
- Private envelope exact fields: version/revision/content/commit, version asterion.prime-context-memory/v1.
- Keep all action guards, raw evidence and model tool-call/result integrity; no restored execution authority.
- Modern P7 operator enables notes; legacy Solver defaults and historical paths remain compatible.

## Task1 — Python memory and P7 adapter

**Owner:** notes_python. Files: new agents/prime/memory.py; P7 research.py,solver.py,research_runtime.py,actor_projection.py,experience.py and narrowly necessary read bridge; focused new unittest files. Root owns operator,prompt,tool_registry,core allowlist.

**Consumes:** current observation/workspace revision and persistent kernel. **Produces:** immutable generic note snapshots; workspace notes adoption/readback; notes learner profile; `set_memory_instructions(prompt)`; successful method results carrying the exact private envelope.

- [x] Add meaningful failing tests: non-ARC free-text snapshots and immutable references; accepted notes replace current memory; stale parent/observation and failed pointer writes do not activate new memory; a notes-mode plan proceeds without full WorldMap but stale/calibration/uncertain/pause checks remain effective.
- [x] Implement generic storage without an active pointer; add optional note reference to current workspace ancestry and optional legacy-evidence reader support.
- [x] Implement exact notes op with16KiB UTF-8 bound, current-ref validation and revision acceptance; expose notes/history retrieval without another model tool.
- [x] Implement notes-aware actor context and trusted memory envelope; preserve model/task/code authority boundaries and public-safe events.
- [x] Run new tests and existing affected research/runtime/experience tests. Report commands, counts and coverage boundary; root reviews before commit.

## Task2 — Generic native model-view projection and tool contract

**Owner:** notes_extension. Files: new TS memory helper,ipython-extension.ts,package.json,TS tests/contract and packaged mjs resource.

**Consumes:** trusted private envelope plus actual callback ID/native raw branch. **Produces:** context-hook model view and checkpoint recovery; NOTES request schema/description; no raw history mutations.

- [x] Add failing tests for obsolete-prefix removal with complete sibling tool results, unchanged raw messages, missing/ambiguous/incomplete boundaries, latest snapshot refresh and compaction/restart recovery; use a non-ARC document research fixture.
- [x] Implement pure projector and receipt controller. Capture envelopes only from trusted method results; strip envelope from visible text, store validated metadata in details; ignore arbitrary stdout.
- [x] Wire native context hook and exact notes tool schema without new public tools; surface only safe projection outcome/count metadata.
- [x] Build, sync resource, run `npm --prefix packages/typescript/asterion-prime-extension test` and type/resource checks.
- [x] Run a provider-free installed-Pi probe to verify the actual hook/model request sees selected memory and paired results.

## Task3 — Root integration and final evidence

**Owner:** root; Astra final review. Files: operator.py,prompt.py,tool_registry.py,core module allowlist; spec/plan/status/review documents; targeted integration test if needed.

- [x] Select notes learner for modern P7 solve/witness/autonomy; set actual memory instructions before appending initial context. Prompt encourages short editable notes, evidence lookup and optional computation without forced phases.
- [x] Keep Python/TS metadata and packaged allowlist synchronized; register generic module in core boundary checks.
- [x] Inspect combined diff for instructions/control preservation, atomic adoption, protocol compatibility and raw-history retention. Resolve Astra findings.
- [x] Run extension tests → affected Python tests → `make promotion-check`; preserve logs and differentiate skips/failures.
- [x] Freeze package identity and run one isolated r11l L1 witness≤900s. Verify actual note use/context projection if observed, cleanup and tool/resource identities. No official card or BP35 full rerun.
- [x] Record implemented/verified/not-observed boundaries, update state/index/journal and commit all substantive changes.

Completion evidence: [implementation and bounded witness](../../reviews/2026-10-08-prime-research-notes.md). Production ebcefec9; installed fixture44091934. BP35 performance remains unmeasured.

## Task4 — Frozen cold BP35 L1–L6 comparison (user continued2026-10-08)

**Status:** one frozen run active07:45:31–09:15:31 CST; NOTES implementation and r11l deployment remain complete.

**Scope:** offline BP35/seed0 from an empty isolated root; exact deployed NOTES productionebcefec9, gpt-6.1-sol/high; existing5400-second absolute task budget, at most6 natural rounds,1000 primitive actions,1024 model callbacks,4096 tool callbacks. At target6 or any terminal/budget boundary stop and retain failure as evidence. Existing180-second cleanup grace is not more solving time. No L7–L9, official card, outer game hints, old answers or midrun repair.

- [x] Prepare new root/profile and frozen wheel/source/wrapper identities; verify actual provider-free worker restriction/recovery, then independent preflight.
- [ ] Run once through L6 or the finite boundary, keeping raw evidence and natural continuation; preserve the pre-existing console.
- [ ] Independently verify actions/RESET/per-level clocks, NOTES ancestry/size/current scope, model input usage, real context projection, source identity and owned-process cleanup.
- [ ] Compare actual research and outcomes with previous P7 and original arc-skill; distinguish context reduction from solving quality and measured correlation from causality. Commit report and recovery state.

Raw evidence stays private under `.asterion-private/p7-notes-bp35-20261008/`. Root owns public state/report; the trial agent owns only its private harness/evidence/isolated root. Source implementation stays frozen throughout this package.
