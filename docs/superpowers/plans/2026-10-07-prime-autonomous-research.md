# Prime autonomous research implementation plan

> **For agentic workers:** Use subagent-driven-development for scoped implementation and independent review. Root integrates; application and framework ownership remain disjoint.

**Goal:** Enable bounded natural autonomous research through recoverable setbacks, and measure a frozen cold P7 BP35 run through six completed levels without external solving intervention.

**Architecture:** Reuse `PrimeExecutionKernel` and the same Pi session. A small domain-neutral continuation policy manages absolute time and natural rounds; application adapters supply authoritative task state, research references and domain tools. ARC observation, RESET, prediction and scoring stay under P7. No new runner, manifest authority or public protocol.

**Tech stack:** Python orchestration/unittest, existing Pi RPC and persistent Python workspace, packaged TypeScript tools, installed wheel in the existing Ubuntu guest.

## Global constraints

- Default Prime128 model callbacks/500 tool callbacks/3600 seconds and witness900 seconds retain their meaning.
- Explicit trusted research profile:5400 seconds total,1024 model callbacks,4096 tool callbacks; BP35 preset additionally six natural rounds/1000 primitive actions/target six/offline/fresh.
- The absolute deadline starts before application preparation and is not renewed by pause, continuation, RESET or kernel restoration. Individual tool limits and180-second cleanup remain separate.
- Tool registration stays exactly `ipython`, `p7_workspace`, `p7_execute_plan`; no prompts pretending to be tools.
- Actor chooses representation, experiment, computation and RESET. No forced cognitive stages, external game judgment or historical solution injection.
- Persist only accepted explicit exports on kernel loss; ordinary namespace is not promised durable. Uncertain external actions are never automatically repeated.
- Generic code cannot import ARC/P7; public events, identity checks, immutable observations and fail-closed permissions remain intact.
- The experiment is a single fixed-version cold L1–L6 run. No official card, L7 action, automatic budget expansion or hot code changes.

### Task 1: Generic finite continuation and research guidance

**Ownership:** `src/asterion/agents/prime/continuation.py`, `execution.py`, `session.py`, focused generic tests. Sol implementer; root integrates.

**Interfaces:** Export `ASTERION_PRIME_RESEARCH_LIMITS = AsterionPrimeLimits(1024,4096,5400000)` while retaining existing default. `PrimeContinuationBudget(deadline_monotonic: float,max_natural_rounds: int)` is frozen; `PrimeContinuationController(budget)` supplies `async admit(round_index,signal)->bool` and a copied/frozen metadata snapshot. Index is zero-based; model callbacks are not natural rounds. Export short `AUTONOMOUS_RESEARCH_GUIDANCE` that asks for optional durable facts/assumptions/open questions, prioritizes actual feedback and lets the actor choose research form.

- [x] Write and run failing generic tests: a non-ARC fake research goal continues on one Pi session; budget admits indices0..5 and rejects6; expired/cancelled refuses; pause/continuation do not renew deadline; invalid finite/mixed-None limits reject.
- [x] Implement the small helper and finite ceiling validation. Session accepts trusted validated finite limits; exact RPC duration/request/launch agreement remains checked. Add `reusable_session=False` opt-in and set it True for autonomy: the existing P7 wrapper had not enabled the kernel reusable mode. Preserve the existing all-None legacy contract without using it for this experiment.
- [x] Run `uv run python -m unittest -v tests.test_asterion_prime_session tests.test_prime_round_admission tests.test_pi_rpc_reusable` plus the new policy test module; report named results and modified paths.
- [x] Independent review of generic reuse and authority: two startup findings repaired;90 focused tests pass. Frozen deployment remains Task4.

Implementation contract:
```python
ASTERION_PRIME_RESEARCH_LIMITS = AsterionPrimeLimits(1024, 4096, 5_400_000)
# A natural round is admitted only while these conditions all hold:
allowed = not signal.cancelled and 0 <= round_index < budget.max_natural_rounds and time.monotonic() < budget.deadline_monotonic
# Snapshot/reporting cannot renew the immutable budget.
```

### Task 2: P7 finite cold preset and recoverable terminal adapter

**Ownership:** `src/asterion/applications/prime/p7/operator.py`, `runtime_binding.py`, `research_runtime.py`, `live.py` or prompt resource where necessary, `tools/run_prime_p7_guest.py`, `Makefile`, exact application tests and `tools/p7_guest_environment.txt`. Separate Sol implementer; no edits to generic files or solver/broker.

**Consumes:** Task1 generic research limits/controller/guidance. **Produces:** one explicit `autonomy` guest/operator entry selecting offline fresh target6 with the frozen finite profile; exact launch/runtime/Pi duration agreement and the same origin-absolute task deadline enforced by signal/control/guest. Pi has a separate fixed relative transport ceiling from session open; it cannot enlarge the absolute task authority. Do not silently reinterpret normal solve or witness. Outer-round admission composes generic controller with existing pause/stop, without treating post-tool `admit_round(0)` calls as new rounds.

- [x] Write failing tests for preset identity and deadline agreement, incompatible witness/resume/competition rejection and state matrix: active/reset-required continue; goal/action cap/nonrecoverable stop.
- [x] Implement trusted preset across launch, binding and control. Completion checks task status, not whether `seal()` can produce a failure receipt. Actor performs any RESET. Cold mode explicitly excludes old experience/prefix; no hidden history loading.
- [x] Initial/continuation prompts include reusable guidance, actual latest state and retained research references; allow language notes, partial models, local experiments and optional computation. No BP35 solution details.
- [x] Validate launcher lifetime covers the same5400 task budget plus bounded cleanup; record metadata separate from solving time. Preserve900 witness and default behavior tests.
- [x] Run focused operator/binding/research-runtime/deadline tests and provide launch command/metadata contract for the frozen trial.

Completion contract:
```python
# status() may reject after terminal; use the real terminal snapshot then.
return terminal_reason not in {"active", "reset-required"}
# This is task-stop detection, never an instruction to auto-RESET.
```

### Task 3: Per-step current-observation grounding

**Ownership:** `src/asterion/applications/prime/p7/solver.py`, `broker.py` only if necessary, `tests/test_prime_p7_solver.py` and focused Broker tests. Root integrates a narrowly scoped patch; final Astra review.

- [x] Construct a two-step fake plan where the second step's distinguishing cell differs from the plan-start choice. Assert the Broker receives the choice derived from the actual pre-step observation and all cells still receive post-step scoring.
- [x] Validate every plan structurally before any dispatch; select the native grounding cell immediately before each action, using the current settled frame. Preserve original immutable candidate cells and full comparisons; mismatch stops suffix.
- [x] Examine current-bound no-change probes: only loosen a proven overblock while retaining exact observation identity, novel/preparation bounds, repeated no-effect rejection and unknown-result no-replay. If already admissible, do not add a bypass.
- [x] Solver/Broker106 focused tests pass, including per-step frame, one no-change probe and shared32 ceiling; Astra diff review has no blocker. No BP35 solution data in tests.

Selection contract:
```python
frame = observation["frame"][-1]
cell = next((c for c in cells if c["y"] < len(frame) and c["x"] < len(frame[c["y"]]) and frame[c["y"]][c["x"]] != c["value"]), cells[0])
# Selection happens per dispatch; post-dispatch scoring uses every original cell.
```

### Task 4: Frozen packaged verification and authorized cold comparison

**Ownership:** Root integration/status; trial agent private launch/evidence; Astra final review.

- [x] Review integrated diff and resolve important findings; run TypeScript extension tests, affected Python tests, `make promotion-check` and docs/diff checks. Commit complete implementation and plan/status before the trial.
- [x] Freeze source/wheel/extension hashes and actual `gpt-6.1-sol`/high argv. Use a new external operator root and dedicated provider profile; exclude old solutions, reports and game source from the research worker with an explicit supported filesystem boundary. Tool allowlists alone do not prove that boundary.
- [x] Real packaged deployment verification uses the authorized cold profile itself; record the required witness-equivalent package identities and explicit difference from the900-second level-witness command. Do not spend an unrecorded additional model trial.
- [x] Run once from zero completed levels and zero restored actions; host supplies only the initial generic task and preauthorized natural continuations. Stop at six or the first finite cap. Do not hot-modify code, notes or plans.
- [x] Preserve the trusted research-worker factory on kernel recreation; verify the actual worker protocol under the operator-owned Landlock wrapper before live startup. No unrestricted fallback.
- [x] Collect all actions/RESET, per-level edges, natural rounds/model/tool callbacks, real misses versus zero-dispatch rejects, wall time/host gaps, recoveries, stopping reason and cleanup. Preserve failed evidence without promoting partial progress to success.
- [x] Compare measured results with the prior arc-skill271-action trajectory and historic P7 successful32/43-action suffixes, explicitly retaining the old total-R&D-cost gap and noncontrolled budget differences. Update the existing standalone HTML and report if useful; synchronize CURRENT/RESUME/DECISIONS/INDEX/JOURNAL and commit.

## Measured outcome and current analysis

Frozen run ended at5400 seconds with5 completed/213paid; sixth-level target NOT achieved. L1–5 counts26/47/41/23/30; L6 unfinished46. Actor RESETs only L2/L3. User now requires actual arc-skill process comparison and main failure mechanisms before further implementation. Actual process audits completed: L6 research did not converge;15undo and serial negative experiments consumed actions,9/15 revisions gate-required. One natural round never ended, so no continuation was exercised. Request-level latency causality remains unmeasured. Report and HTML record failure and layered candidates; no new code or paid trial.

## Acceptance and limits

A passing cold run proves this frozen version can autonomously complete BP35 L1–L6 within the stated profile. Unit tests prove their named boundaries only. The earlier arc trial had staged goal updates and a host recovery, so this is not a controlled causal A/B or evidence for unknown games. If unfinished, report exact progress and cause with the same distinction between implemented, verified and externally limited.
