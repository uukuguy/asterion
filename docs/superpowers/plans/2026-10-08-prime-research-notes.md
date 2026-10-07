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

- [ ] Add meaningful failing tests: non-ARC free-text snapshots and immutable references; accepted notes replace current memory; stale parent/observation and failed pointer writes do not activate new memory; a notes-mode plan proceeds without full WorldMap but stale/calibration/uncertain/pause checks remain effective.
- [ ] Implement generic storage without an active pointer; add optional note reference to current workspace ancestry and optional legacy-evidence reader support.
- [ ] Implement exact notes op with16KiB UTF-8 bound, current-ref validation and revision acceptance; expose notes/history retrieval without another model tool.
- [ ] Implement notes-aware actor context and trusted memory envelope; preserve model/task/code authority boundaries and public-safe events.
- [ ] Run new tests and existing affected research/runtime/experience tests. Report commands, counts and coverage boundary; root reviews before commit.

## Task2 — Generic native model-view projection and tool contract

**Owner:** notes_extension. Files: new TS memory helper,ipython-extension.ts,package.json,TS tests/contract and packaged mjs resource.

**Consumes:** trusted private envelope plus actual callback ID/native raw branch. **Produces:** context-hook model view and checkpoint recovery; NOTES request schema/description; no raw history mutations.

- [ ] Add failing tests for obsolete-prefix removal with complete sibling tool results, unchanged raw messages, missing/ambiguous/incomplete boundaries, latest snapshot refresh and compaction/restart recovery; use a non-ARC document research fixture.
- [ ] Implement pure projector and receipt controller. Capture envelopes only from trusted method results; strip envelope from visible text, store validated metadata in details; ignore arbitrary stdout.
- [ ] Wire native context hook and exact notes tool schema without new public tools; surface only safe projection outcome/count metadata.
- [ ] Build, sync resource, run `npm --prefix packages/typescript/asterion-prime-extension test` and type/resource checks.
- [ ] Run a provider-free installed-Pi probe to verify the actual hook/model request sees selected memory and paired results.

## Task3 — Root integration and final evidence

**Owner:** root; Astra final review. Files: operator.py,prompt.py,tool_registry.py,core module allowlist; spec/plan/status/review documents; targeted integration test if needed.

- [ ] Select notes learner for modern P7 solve/witness/autonomy; set actual memory instructions before appending initial context. Prompt encourages short editable notes, evidence lookup and optional computation without forced phases.
- [ ] Keep Python/TS metadata and packaged allowlist synchronized; register generic module in core boundary checks.
- [ ] Inspect combined diff for instructions/control preservation, atomic adoption, protocol compatibility and raw-history retention. Resolve Astra findings.
- [ ] Run extension tests → affected Python tests → `make promotion-check`; preserve logs and differentiate skips/failures.
- [ ] Freeze package identity and run one isolated r11l L1 witness≤900s. Verify actual note use/context projection if observed, cleanup and tool/resource identities. No official card or BP35 full rerun.
- [ ] Record implemented/verified/not-observed boundaries, update state/index/journal and commit all substantive changes.
