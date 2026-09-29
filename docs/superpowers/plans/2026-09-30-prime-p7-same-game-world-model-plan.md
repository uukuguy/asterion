# P7 Same-Game World Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a game-agnostic, same-game WorldModel with replay-verified TransitionModel hypotheses, durable private Playbook memory, and safe conversion of offline routes into checked online actions.

**Architecture:** Keep the raw broker history as the evidence authority. Add pure, validated model types and a retrodiction service that consumes `ArcHistoryRecord` values without executing model-provided code. Persist a bounded Playbook under the existing private P7 root, inject only capped projections into the operator/worker, and keep `ArcBroker.act_checked` as the final action gate.

**Tech Stack:** Python 3.10+, frozen dataclasses, JSON private evidence, existing `ArcBroker`/`ArcHistoryRecord` contracts, existing `ArcReplayOracle` and route optimizer, `unittest`.

## Global Constraints

- Persist only exact `(game_id, seed, win_levels)` same-game data; do not transfer facts between games.
- `WorldModel` is the semantic authority, while raw frames/actions remain the evidence source.
- Confirmed facts are reusable; hypotheses require one distinguishing probe and never become confirmed from model text alone.
- `TransitionModel` candidates must pass retrodiction over all supplied history before route planning.
- Every live batched action carries a distinguishing expected result; the first mismatch stops the batch.
- Offline candidates must replay in a fresh engine and fall back to the verified route on any rejection or error.
- Private frames, prompts, hypotheses, credentials, and local paths never enter public receipts.
- Action-slot meanings are learned per game from evidence; remove the global ACTION1–ACTION7 semantic claim.
- Keep framework modules domain-neutral and do not read `.env`, credentials, or provider settings from the new modules.

---

## File Map

### New files

- `src/asterion/applications/prime/p7/world_model.py` — validated facts, evidence references, immutable snapshots, and same-game model merge/branch operations.
- `src/asterion/applications/prime/p7/playbook.py` — private JSON persistence and capped projections for checked mechanics, level memory, and evidence index.
- `src/asterion/applications/prime/p7/transition_model.py` — declarative transition expectations and the retrodiction gate over `ArcHistoryRecord` history.
- `tests/test_prime_p7_world_model.py` — unit tests for validation, confirmation, level refresh, conflicts, and redaction.
- `tests/test_prime_p7_transition_model.py` — retrodiction acceptance/rejection and expected-action derivation tests.
- `tests/test_prime_p7_playbook.py` — exact-game storage, atomic writes, symlink rejection, caps, and branch tests.

### Existing files to modify

- `src/asterion/applications/prime/p7/broker.py` — expose current private history to the model service, record model updates after transitions, and retain per-level snapshots before clearing transient no-effect state.
- `src/asterion/applications/prime/p7/verified_history.py` — add strict conversion helpers from public/private records to transition observations without weakening existing validation.
- `src/asterion/applications/prime/p7/operator.py` — load/save the Playbook, build bounded model context, register read-only model/playbook tools, and record retrodiction/branch diagnostics.
- `src/asterion/applications/prime/p7/ipython_host.py` — add sealed facade methods for read-only model/playbook projections and validated hypothesis submission if the worker surface needs it.
- `src/asterion/applications/prime/p7/live.py` — add worker RPC names, argument-count checks, generated helper functions, and aliases for the new read-only tools.
- `src/asterion/applications/prime/p7/prompt.py` — require model/prior inspection, retrodiction before batching, per-action expectations, and evidence-derived action semantics.
- `src/asterion/applications/prime/p7/optimizer.py` — carry per-step `ActionExpectation` values with verified candidates.
- `src/asterion/applications/prime/p7/optimizer_arc.py` — derive expectations from fresh-engine replay witnesses and reject candidates that cannot produce them.
- `tests/test_prime_p7_native_broker.py` — broker/model lifecycle and first-conflict stop behavior.
- `tests/test_prime_p7_action_feedback.py` — expected-action feedback and branch/replan payloads.
- `tests/test_prime_p7_bridge_dispatch.py` — RPC dispatch and malformed-parameter rejection.
- `tests/test_prime_p7_live_command.py` — prompt and capped context assertions without game-specific leakage.
- `tests/test_prime_p7_optimizer.py` and `tests/test_prime_p7_optimizer_arc_witness.py` — candidate expectations and safe fallback.
- `tests/test_prime_p7_native_replay.py` and `tests/test_prime_p7_official_replay.py` — fresh replay identity and evidence compatibility.
- `tests/test_prime_p7_diagnostics.py` — private retrodiction and conflict diagnostics.

---

### Task 1: Add validated WorldModel data types

**Files:**
- Create: `src/asterion/applications/prime/p7/world_model.py`
- Create: `tests/test_prime_p7_world_model.py`

**Interfaces:**
- Produces `EvidenceRef`, `WorldFact`, `WorldModelSnapshot`, and `WorldModelStore`.
- `WorldModelStore(game_id: str, seed: int, win_levels: int)` rejects invalid identity values and keeps `mechanics`, `entities`, `relations`, `current_level`, `version`, and `conflicts`.
- `record_hypothesis(layer, key, value, *, level, evidence) -> WorldFact` stores a capped hypothesis.
- `confirm(layer, key, *, evidence, observed_value=None) -> WorldFact` confirms only a matching observed fact.
- `conflict(layer, key, *, observed_value, evidence) -> WorldModelSnapshot` creates a local branch and leaves confirmed facts unchanged.
- `refresh_level(level) -> WorldModelSnapshot` replaces only level-local entities/relations.
- `projection(max_bytes=8192) -> dict[str, object]` returns a detached redacted view.

- [ ] **Step 1: Write failing validation tests** for malformed identities, unknown layers, mutable values, missing evidence, duplicate keys, and projection size limits.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_p7_world_model`; expect failures because the module does not exist.
- [ ] **Step 3: Implement** frozen dataclasses, canonical JSON-safe value validation, evidence-reference validation, copy-on-write updates, and deterministic sorted projections. Do not import broker or provider modules.
- [ ] **Step 4: Add tests** proving a confirmed fact survives `refresh_level`, a hypothesis does not appear in `confirmed`, and a conflict creates a branch without mutating the parent snapshot.
- [ ] **Step 5: Run** the focused test file and `git diff --check`; expect PASS.
- [ ] **Step 6: Commit** `git add src/asterion/applications/prime/p7/world_model.py tests/test_prime_p7_world_model.py && git commit -m "feat(p7): add validated same-game world model"`.

### Task 2: Implement replay-verified TransitionModel

**Files:**
- Create: `src/asterion/applications/prime/p7/transition_model.py`
- Modify: `src/asterion/applications/prime/p7/verified_history.py`
- Create: `tests/test_prime_p7_transition_model.py`

**Interfaces:**
- Produces `ActionExpectation`, `TransitionRule`, `TransitionModel`, and `RetrodictionReport`.
- `TransitionModel.from_history(records: Sequence[ArcHistoryRecord], *, world: WorldModelSnapshot) -> TransitionModel` builds only declarative rules from validated records.
- `retrodict(model: TransitionModel, records: Sequence[ArcHistoryRecord]) -> RetrodictionReport` checks sequence continuity, before/after hashes, action/data identity, levels, state, and all declared expectations.
- `TransitionModel.expectations() -> tuple[ActionExpectation, ...]` returns ordered live-check expectations.
- `verified_history.transition_observation(record) -> dict[str, object]` returns a detached internal observation and never exposes a raw frame through public projections.

- [ ] **Step 1: Add failing tests** for contiguous history acceptance, gap rejection, wrong before-hash rejection, state/level mismatch rejection, and a model whose rule cannot explain one observed transition.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_p7_transition_model`; expect failures.
- [ ] **Step 3: Implement** strict record conversion and a bounded declarative rule evaluator. Rules may compare action name/data and prior level/state/frame digest; effects are expected digest, changed-cell samples, level, and state. No `eval`, imports, filesystem, network, or arbitrary model code.
- [ ] **Step 4: Add tests** showing a rejected model cannot produce expectations, a valid model produces one expectation per planned action, and all report failures contain only safe sequence/reason codes.
- [ ] **Step 5: Run** focused tests plus `uv run python -m unittest -v tests.test_prime_p7_native_broker.TestNativeP7Broker`; expect PASS.
- [ ] **Step 6: Commit** `git add src/asterion/applications/prime/p7/transition_model.py src/asterion/applications/prime/p7/verified_history.py tests/test_prime_p7_transition_model.py && git commit -m "feat(p7): add transition retrodiction gate"`.

### Task 3: Persist same-game Playbook safely

**Files:**
- Create: `src/asterion/applications/prime/p7/playbook.py`
- Create: `tests/test_prime_p7_playbook.py`

**Interfaces:**
- Produces `PlaybookKey`, `PlaybookSnapshot`, `load_playbook(root, key)`, `save_playbook(root, snapshot)`, `append_checked_route(snapshot, route)`, and `branch_playbook(snapshot, reason)`.
- Storage path is `<operator_root>/.asterion-private/prime-p7-live/playbooks/<safe-game-id>-<seed>-<win-levels>.json`.
- Load/save must reject symlinks, non-regular files, mismatched identity, invalid schema, oversized JSON, and non-atomic writes.
- The JSON contains only confirmed model facts, checked route expectations, level memory, conflict metadata, and evidence digests; it never stores raw frames, prompts, credentials, or model output.

- [ ] **Step 1: Write failing tests** for exact identity selection, missing file, symlink rejection, malformed schema, atomic replace, bounded file size, and branch isolation.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_p7_playbook`; expect failures.
- [ ] **Step 3: Implement** canonical JSON serialization, `0600` file creation, temporary sibling write plus `os.replace`, directory checks, and deterministic sorting. Do not reuse the module-global `hypothesis_store` singleton.
- [ ] **Step 4: Add tests** proving a completed level snapshots checked facts before transient per-level counters are cleared and that reloading with another game/seed returns unavailable.
- [ ] **Step 5: Run** the focused file and `git diff --check`; expect PASS.
- [ ] **Step 6: Commit** `git add src/asterion/applications/prime/p7/playbook.py tests/test_prime_p7_playbook.py && git commit -m "feat(p7): persist bounded same-game playbooks"`.

### Task 4: Integrate model lifecycle into broker and operator

**Files:**
- Modify: `src/asterion/applications/prime/p7/broker.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `tests/test_prime_p7_native_broker.py`
- Modify: `tests/test_prime_p7_action_feedback.py`
- Modify: `tests/test_prime_p7_diagnostics.py`

**Interfaces:**
- `ArcBroker` accepts an injected `WorldModelStore | None` and exposes `world_model()`, `transition_model()`, and `playbook_projection()` as read-only application methods.
- After each accepted transition, the broker records an evidence reference; after a level advance it snapshots checked facts before `_clear_no_effect_level` runs.
- `act_checked` returns bounded `retrodiction` status and `conflict` metadata on the first mismatch, while preserving existing `stop_reason`, `feedback`, and `unexecuted_count` fields.
- Operator loads the exact Playbook before prompt construction and saves only after sealed/replay-verified evidence; failed or interrupted runs write a branch record, not a checked route.

- [ ] **Step 1: Add failing broker tests** for a model projection, model update after a transition, snapshot-before-clear on level advance, first mismatch conflict branch, and unchanged legacy public receipt.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_action_feedback`; expect failures.
- [ ] **Step 3: Wire** the new store into `ArcBroker`, convert each private history record into evidence, call the pure retrodiction service before arming a checked route, and keep safe fallback behavior when the Playbook is unavailable.
- [ ] **Step 4: Add operator diagnostics** with counts/status only: `world_model_version`, `retrodiction_status`, `conflict_count`, `playbook_loaded`, `playbook_saved`; never include prompts, frames, or fact values in public receipts.
- [ ] **Step 5: Add tests** for sealed success saving a checked route, failed runs saving only conflict metadata, and malformed Playbook load falling back to baseline without dispatching extra actions.
- [ ] **Step 6: Run** the focused broker/action/diagnostics files and commit `git add src/asterion/applications/prime/p7/broker.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_native_broker.py tests/test_prime_p7_action_feedback.py tests/test_prime_p7_diagnostics.py && git commit -m "feat(p7): connect world model to broker lifecycle"`.

### Task 5: Expose bounded model/playbook tools and correct prompt semantics

**Files:**
- Modify: `src/asterion/applications/prime/p7/ipython_host.py`
- Modify: `src/asterion/applications/prime/p7/live.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `src/asterion/applications/prime/p7/prompt.py`
- Modify: `tests/test_prime_p7_bridge_dispatch.py`
- Modify: `tests/test_prime_p7_live_command.py`

**Interfaces:**
- Add read-only worker methods `p7_world_model()` and `p7_playbook(level=None)`; both return capped projections and accept no raw-frame arguments.
- Expose `p7_record_hypothesis(layer, key, value)` as the sole model-write method; the application attaches the current evidence sequence and never accepts a caller-supplied confirmation.
- Register tools as `world_model`, `playbook`, and `retrodiction_status`; keep old aliases and RPC argument counts compatible.

- [ ] **Step 1: Add failing bridge tests** for successful typed dispatch, unknown arguments, oversized projections, and worker-facing alias behavior.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_live_command`; expect failures.
- [ ] **Step 3: Implement** sealed facade methods, live RPC allow-list/arity checks, generated helper functions, and operator tool registration. Cap each serialized section before the 16 KiB host boundary.
- [ ] **Step 4: Replace the prompt’s fixed ACTION1–ACTION7 meanings** with instructions to infer mappings from `available_actions`, confirmed mechanics, and action feedback. Keep generic examples using symbolic action names only.
- [ ] **Step 5: Update prompt tests** to require retrodiction before batch use, confirmed-vs-hypothesis language, first-conflict stop behavior, same-game Playbook reuse, and absence of BP35/DC22-specific text.
- [ ] **Step 6: Run** focused bridge/live tests and commit `git add src/asterion/applications/prime/p7/ipython_host.py src/asterion/applications/prime/p7/live.py src/asterion/applications/prime/p7/operator.py src/asterion/applications/prime/p7/prompt.py tests/test_prime_p7_bridge_dispatch.py tests/test_prime_p7_live_command.py && git commit -m "feat(p7): expose bounded world model context"`.

### Task 6: Gate offline optimizer candidates with retrodiction and expectations

**Files:**
- Modify: `src/asterion/applications/prime/p7/optimizer.py`
- Modify: `src/asterion/applications/prime/p7/optimizer_arc.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `tests/test_prime_p7_optimizer.py`
- Modify: `tests/test_prime_p7_optimizer_arc_witness.py`

**Interfaces:**
- Extend `RouteResult`/`RouteCandidate` with `expectations: tuple[ActionExpectation, ...]` appended after existing fields so current positional constructors remain valid; new constructors should pass it by keyword.
- `ArcReplayOracle.replay` produces one expectation per candidate action from fresh-engine observation witnesses.
- `_optimize_verified_route` and `_optimize_partial_attempt` pass candidates through `retrodict` and publish `candidate_expectations` only when the candidate is shorter and fully verified.
- `arm_route_adoption` accepts both `PlannerAction` values and their expectations; adoption stops on the first expected mismatch and falls back to normal model control.

- [ ] **Step 1: Add failing optimizer tests** for expectation derivation, candidate rejection when a witness is missing, retrodiction failure fallback, and preserving baseline route metadata.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_p7_optimizer tests.test_prime_p7_optimizer_arc_witness`; expect failures.
- [ ] **Step 3: Implement** the new expectation dataclass, fresh-replay derivation, and candidate validation. Do not change the finite candidate budget or fresh-engine isolation.
- [ ] **Step 4: Add operator tests** proving an optimized candidate is armed only after the gate and a failed optimization keeps the baseline route with no extra live actions.
- [ ] **Step 5: Run** the focused optimizer tests and commit `git add src/asterion/applications/prime/p7/optimizer.py src/asterion/applications/prime/p7/optimizer_arc.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_optimizer.py tests/test_prime_p7_optimizer_arc_witness.py && git commit -m "feat(p7): require replay-verified route expectations"`.

### Task 7: Verify replay/public evidence boundaries and full P7 regressions

**Files:**
- Modify: `tests/test_prime_p7_native_replay.py`
- Modify: `tests/test_prime_p7_official_replay.py`
- Modify: `tests/test_prime_p7_diagnostics.py`
- Modify: `tests/test_prime_p7_game_inventory.py` only if the new model metadata changes inventory projections
- Documentation check: `docs/superpowers/specs/2026-09-30-prime-p7-same-game-world-model-design.md`

- [ ] **Step 1: Add replay tests** proving a model/playbook derived from a sealed trace is accepted only for the exact game/seed, and a raw-frame or unsealed-run injection is rejected.
- [ ] **Step 2: Add redaction tests** asserting public receipts and comparison reports contain neither `frame`, `prompt`, `hypothesis`, `playbook path`, nor private fact values.
- [ ] **Step 3: Run focused suites:**
  `uv run python -m unittest -v tests.test_prime_p7_world_model tests.test_prime_p7_transition_model tests.test_prime_p7_playbook tests.test_prime_p7_native_broker tests.test_prime_p7_action_feedback tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_live_command tests.test_prime_p7_optimizer tests.test_prime_p7_optimizer_arc_witness tests.test_prime_p7_native_replay tests.test_prime_p7_official_replay tests.test_prime_p7_diagnostics`.
- [ ] **Step 4: Run repository gates:** `make lint`, `make docs-check`, and the smallest applicable `make check` target; record exact pass/fail boundaries.
- [ ] **Step 5: Review the diff** for game-specific strings, global singleton leakage, unbounded JSON, action-slot assumptions, and any framework import of provider configuration.
- [ ] **Step 6: Commit** the final verification/test changes with `git add tests docs && git commit -m "test(p7): verify world model replay boundaries"`.

## Self-Review Against the Design

- WorldModel layers, evidence references, hypotheses, confirmations, local refresh, and conflicts are covered by Task 1.
- Executable transition behavior is bounded and retrodiction-gated by Task 2; no arbitrary model code is executed.
- Same-game private persistence and checked/working memory are covered by Task 3 and operator lifecycle wiring in Task 4.
- First-mismatch stop, expected results, and branch recovery are covered by Tasks 2, 4, and 6.
- Offline optimization is useful only after fresh replay plus retrodiction, covered by Task 6.
- Per-game action semantics and optional raw-frame access are covered by Task 5.
- Replay identity, redaction, and public/private boundaries are covered by Task 7.
- No task reads `.env`, changes provider registration, or transfers facts across games.
