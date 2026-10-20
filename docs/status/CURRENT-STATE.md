# Current State

## Project Snapshot

- Project: Asterion composable multi-runtime framework; native Prime autonomous research infrastructure and P7 domain application.
- Branch: `main`. Prime/P7 development branches are consolidated; archive tags preserve ancestry. Retained P1–P3 worktrees and their unrelated changes remain operator-owned.
- Theme: Long-horizon, open-ended, falsifiable computational research with understandable, checkable, traceable and replayable evidence. P7 is the current domain reference. The structural program puts Prime and Native on one base Pi process.
- Project route: managed. `P-PI-1`, `P-NATIVE-1`, and `P-CITE-1` are done. The peer-foundation worklist has no pending package. Completion-worklist packages `P-NOTES-1`, `P-P2-1`, `P-LIVE-1`, `P-COMPOSE-1`, and `P-COMPACT-1` are done. That closure does not authorize a new experiment.
- Canonical worklist: `docs/superpowers/plans/2026-10-20-asterion-peer-foundation.md`. The 2026-10-20 completion worklist, the 2026-10-08 research-interface plan, and the P7 milestone handoff remain historical. They do not authorize a new experiment.
- Milestone: annotated `asterion-prime-p7-milestone-2026-10-13` → `aca76ed7`; baseline `asterion-prime-p7-baseline-2026-10-13` → `4107aefb`. State-only commits after the milestone do not change its code snapshot.

## Current Architecture

- Python owns orchestration, composition and execution; TypeScript validates shared contracts and registers Prime/application tools; Rust provides policy-controlled direct execution. Canonical schemas, exact identities, deterministic composition and closed authorization boundaries remain authoritative in `AGENTS.md`.
- The base owns protocols, composition, the runner, host services, and the Pi process in `PiRpcSession`. Prime and Native are peers. Prime supplies the IPython harness, exact tool allowlist, accepted notes, compaction content, and `prepare_prime_application`. Applications do not construct Pi/RPC objects. The one-shot `pi.reference` facade and the long-lived session share `PiChildProcess` for child start, signal, and reap. Provider `native` assembles `controlled-code@1.0.0` and `dci@1.0.0` as application `native.packages@1.0.0` on `pi.reference`. DCI remains the retrieval package. The six `prime-*-native` packages record a receipt's media type, digest, and run identity. They do not execute Prime. `prepare_prime_application` remains the Prime execution door. Operators P1 through P6 read that digest from the Prime runtime they already build.
- Existing P1 and P3–P7 model paths use the standard resource owner, including the P7 narrator. Independent applications need no central registration. P1–P6 target `deepseek/deepseek-flash`; P7 uses `openai-codex/gpt-6.1-sol`. P2's default run remains local model-free retrieval. `p2/program.py` interprets one model-written `retrieve` or `transform` statement, and `p2/inquiry.py` commits a note only after the fragment digest matches. `p2/live.py` is the separate finite flash inquiry. CLI purpose remains open. The writing map is `docs/guides/prime-application-writing.md`.
- Operator-owned configuration is resolved outside generic Prime and explicitly injected. Manifests carry compatibility, never prompts, commands, credentials, mutable state or execution authority.
- P7 exposes registered `ipython`, `p7_workspace`, `p7_execute_plan`. The model owns hypotheses, representations, programs, search, NOTES and strategy. P7 supplies real observations and a single action broker; model code cannot import hidden game mechanics.
- `ResearchNotes` is the Prime accepted-note epoch over `ResearchMemoryStore`. A save does not accept a document. Readable history is the application-committed revision and its ancestors. `ResearchRecordStore` is the passive evidence index. P7 commits `notes_revision` and validates game observation boundaries. World models, action labels, consoles, and probe admission stay in P7. Generic TypeScript still owns context projection. Hook bytes, provider tokens, cache counts, and estimated costs remain distinct measurements.

## Standard P7 per-action rollout

- Modern standard solve/selected resume/sweep and supervised research bind the existing RolloutRuntime to shared IPython. Every primitive uses its latest actual observation, action and registration; batch suffixes are checked step by step. Frozen official/witness/autonomy and legacy paths retain their stated profiles.
- `predicted_death` and `conditional_fatal` stop the current action and suffix. Missing or incomplete models are unassessed; default advance returns `model-coverage-review` without dispatch. Model-declared coverage is not an independent safety proof.
- An unknown probe requires a prior returned review at the exact observation/action/model registration/kernel generation, one step, nonempty goal and risk/cost declarations, plus trusted finite application `unknown_probe_action_limit` (default **0**). Only valid evaluated registered models with explicit coverage gaps may use an allowance; missing checker/model, malformed/unavailable evidence or computation failures cannot.
- The allowance is injected through P7 operator → research runtime → Solver, never model prose/plan fields. Its scope is a newly constructed host/attempt; resume defaults zero. Spend immediately before submission, including uncertain execution; cached plan retrieval does not spend again. Positive allowance on disabled-auto/legacy paths rejects before resources.
- Fatal/applicability, observation/kernel freshness, cancellation, unresolved execution and ordinary budget boundaries remain stronger. RESET preserves its recovery exception and all counterexamples; it does not replenish probe authority.
- Registered models may include full automatic motion until a modeled stop or unknown. Risk recognition and terminal reconstruction remain separate. Backtests retain predicted outcome/risk, findings, coverage and trace references; incomplete reconstruction stays unknown/unresolved. Unassessed actual death is `death_not_assessed`, including feedback-persistence failure. New names or NOTES do not discharge cases.
- Retained fatal witnesses use their original checked narrow applicability. Unavailable applicability stops the candidate; identical public pixels do not establish hidden-state identity. Exact current-run observed deaths remain distinct facts.

## Runtime and Recovery Boundaries

- Ordinary solve/sweep callbacks default to model1024/tool4096 and accept explicitly configured finite limits; frozen profiles retain their limits. Diagnostic settlement headroom is separate from execution permission.
- Native failed-assistant context omissions are supported only with verified zero dispatch, including unique partial calls with no result/effect evidence. Unknown execution, duplicate identities, aborted/length stops and arbitrary edits fail closed. Private projection reasons distinguish producer errors from transport and integration stages; a file named RPC is not causal evidence.
- Large animations retain complete authenticated raw history, settled views and bounded pages. SDK-native reply materialization may still cause an upstream peak-memory cost. Public console projections preserve exact source identities and never authorize execution.
- Saved-route admission and certificates bind game/SDK/source/verifier identities. Source ancestry is checked without arbitrary resume cutoffs; bounds and cycles fail closed. Actual replay, sealing and cleanup establish route evidence, not new model authority.
- Console HUMAN play has separate journals and does not enter P7 research. Read-only cloud sharing consumes prepared public projections; private research/credentials stay external. Existing unrelated console services must not be stopped during session cleanup.

## Verified Capability Boundary

- Cold BP35 L1–L6: operator-defined successful checkpoint, 211 actions, zero deaths/paid RESETs. Selected continuation completed L7/L8, then the isolated eight-level prefix plus new L9 research reached **9/9/local100**, with a sealed replay-verified 458-action trace. Exact frozen identities, restoration/new-action accounting and receipts are in the handoff.
- The repaired packaged gate was checked against the real offline SDK at the exact L9 predeath checkpoint and the original actor model in shared IPython. Fresh full prediction evidence matched the original; the unknown probe was denied with zero target dispatch and unchanged frame.
- These establish cold six-level solving, selected-prefix full-game completion and exact candidate admission. They do not establish uninterrupted cold nine-level completion, a new full game under the stricter gate, general model accuracy or reliable zero-death solving.
- The October7 official100/25publicgames/183levels/6781selectedactions belongs to its historical accumulated-research campaign. It does not certify the later refactored system. Public result scope remains in `docs/results/arc-agi-3/README.md`.
- Implemented, source-verified, provider-free verified, packaged candidate checks and real model solving are separate claims. SDK estimates are not invoices; missing/partial measurements remain unknown. Historical failed/interrupted full gates are never rewritten as PASS.

## Open Problems

- General autonomous modeling quality, full-game reliability under default-zero probe authority and transfer beyond P7 are unmeasured. Finite application risk acceptance permits exploration but cannot certify an inaccurate model's claimed coverage.
- Repeated source reconstruction and repeated case summaries add reasoning/context overhead. Dedicated code-aware compaction is on the Prime compact hook. The low-threshold P1 witness and one later `oracle.pass` exist. Continuation stability is not a measured rate, and the P7 low-threshold compaction test has not run. Causal efficiency gains remain unproven.
- Inherited P1 manual-compaction actual-request token/reservation/billing certification is unresolved, distinct from P7's verified resource controls. No actual overspend has been established.
- SDK upstream animation materialization memory, generic sandbox strength and complete historical migration/long-horizon cognition equivalence remain separate boundaries.
- P1 continuation evidence is one `oracle.pass`, one tool-callback stop at 5 of 4, and one `oracle.reject.final_result`. Prompts and `AsterionPrimeLimits(8, 4, 600000)` stayed unchanged. That is not a stability rate. The P7 low-threshold compaction test, moving effectful probe admission into Prime, and Prime CLI positioning remain open. The program-shaped P2 inquiry has one verified receipt and is one run, not a stability rate. The named orb machine `ubuntu` is absent; Orb presets use `ubuntu-fusion-control`. `make promotion-check` is not a pass on a Node 24 symlink host.

## Key Files

- `AGENTS.md`, `CLAUDE.md`, `MEMORY.md` — repository contracts and collaboration preferences.
- `docs/status/INDEX.md`, `DECISIONS.md`, `JOURNAL.md`, `RESUME-NEXT-SESSION.md` — discovery, rationale, append-only events and next-session baton.
- `docs/architecture/agent-framework.md` — Prime purpose and generic/domain separation.
- `docs/superpowers/specs/2026-10-10-prime-standard-application-entry-design.md` — standard application ownership.
- `docs/superpowers/plans/2026-10-13-p7-coverage-decision.md`, `2026-10-13-p7-death-prediction-repair.md` — completed coverage and authority repairs.
- `src/asterion/agents/prime/application.py`, `backend.py`, `ipython.py`, `execution.py`, `session.py` — generic owner/computation/session boundaries.
- `src/asterion/agents/prime/research_notes.py`, `memory.py`, `research_record.py` — accepted-note epoch, immutable documents, and passive research index.
- `src/asterion/applications/prime/p2/program.py`, `inquiry.py`, `live.py` — one interpreted retrieval statement, digest-gated notes, and the finite flash entry. The zero-token preset stays separate.
- `docs/guides/prime-application-writing.md` — writing map for the seven existing Prime applications.
- `docs/superpowers/plans/2026-10-20-asterion-peer-foundation.md` — peer-foundation worklist. `P-PI-1`, `P-NATIVE-1`, and `P-CITE-1` are done. No package is pending.
- `src/asterion/applications/native/provider.py` — Native application `native.packages@1.0.0` on `pi.reference`, packages `controlled-code@1.0.0` and `dci@1.0.0`.
- `src/asterion/capabilities/prime_native_receipt.py` — the six `prime-*-native` packages record media type, digest, and run identity.
- `src/asterion/runtimes/pi_rpc.py` — the base Pi process and session, including `PiChildProcess` and forced close.
- `src/asterion/runtimes/pi.py` — one-shot public events, redaction, and evidence. Child start and reap go through `PiChildProcess`.
- `docs/superpowers/plans/2026-10-20-prime-application-completion.md` — closed P1–P6 completion and generic-lift worklist.
- `src/asterion/agents/prime/code_summary.py`, `src/asterion/applications/prime/p1/operator.py`, `src/asterion/applications/prime/p1/oracle.py` — dedicated compaction witness and closed public stage-two clause labels.
- `src/asterion/applications/prime/p7/operator.py`, `research_runtime.py`, `solver.py`, `rollout_runtime.py`, `rollout.py`, `prompt.py` — application wiring, per-action admission and model evidence.
- `src/asterion/applications/prime/p7/research.py`, `research_chain.py`, `solutions.py`, `solution_certificates.py` — memory, research references and source-bound routes.
- `packages/typescript/asterion-prime-extension/`, `src/asterion/applications/prime/resources/` — typed tools and synchronized wheel resources.
- `docs/guides/prime-p7-games-and-official-results.md`, `prime-p7-private-research-archive.md`; `tools/p7_research_archive.py` — console/result operations and external private evidence.
- Historical detailed snapshot: commit `045d8ae3` of this file. Trial reports and durable technical decisions remain indexed; they are not the current execution policy.

## Resume Instructions

1. Read INDEX, this snapshot, the final handoff, recent JOURNAL and AGENTS/MEMORY.
2. Confirm Git, remote/tag identity and recorded cleanup before new work. Preserve unrelated worktrees/services.
3. `P-PI-1`, `P-NATIVE-1`, and `P-CITE-1` are done. The peer-foundation worklist has no pending package. A paid run, benchmark, official card, or L9 rerun needs a separate authorization.
