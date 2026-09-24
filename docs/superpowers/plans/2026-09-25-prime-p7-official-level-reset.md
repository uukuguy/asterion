# P7 Official Level Reset Implementation Plan

> **For agentic workers:** Use test-driven development for each task and review the diff before committing. Steps use checkbox syntax for tracking.

**Goal:** Continue a P7 game after `GAME_OVER` by resetting the failed level on the same ARC environment, and pass official click coordinates through the complete action evidence path.

**Architecture:** The P7 Broker remains the sole action authority. It accepts canonical `ACTION1`–`ACTION7` and guarded `RESET`, journals each primitive action and result, and hands exact inputs to the SDK adapter. The existing fresh-engine replay validates the same sequence. Worker-facing status distinguishes recoverable `GAME_OVER` from P7's finite terminal boundaries.

**Tech Stack:** Python 3.12, local `arc_agi`/`arcengine` 0.9.9/0.9.3, `unittest`, installed-wheel verification.

## Global Constraints

- Keep `OperationMode.OFFLINE`; no online scorecard or paid model run in verification.
- `RESET` is one counted primitive action and may not cause `levels_completed` to decrease.
- Forbid zero-action `RESET` to avoid the SDK's full-game reset in OFFLINE mode.
- Retain the 500-action cap and separate run directory per attempt.
- Preserve old no-data action digests and historical run evidence.
- Public output must not expose frames, prompts, private paths, credentials, or click histories.

---

### Task 1: Canonical actions and click coordinates

**Files:** `src/asterion/applications/prime/p7/broker.py`, `score.py`, `live.py`, `operator.py`, `replay.py`; tests in `tests/test_prime_p7_native_broker.py`, `tests/test_prime_p7_native_replay.py`, `tests/test_prime_p7_live_command.py`.

**Interface:** `ArcAction(name: str, data: tuple[tuple[str, int], ...] = ())` is immutable. `ArcBroker.act()` accepts existing strings and canonical `ArcAction` values. Only `ACTION6` has data `(("x", x), ("y", y))`, where each coordinate is an exact integer in `0..63`.

- [ ] Write tests showing `ACTION6` reaches the engine with `x,y`, is recorded and replayed, and rejects missing, extra, boolean, negative, and out-of-range data.
- [ ] Run the named tests and confirm they fail on the missing data path.
- [ ] Implement the immutable action value, strict validation, SDK `step(action, data)` forwarding, and replay hash inclusion for nonempty data. Keep old hashes unchanged when data is empty.
- [ ] Run tests and review action data redaction in public receipts.
- [ ] Commit the tested action path.

### Task 2: Same-instance current-level reset

**Files:** `src/asterion/applications/prime/p7/broker.py`, `replay.py`, `private_trace.py`; tests in `tests/test_prime_p7_native_broker.py`, `tests/test_prime_p7_native_replay.py`, `tests/test_prime_p7_multilevel_receipt.py`.

**Interface:** `ArcBroker.act(("RESET",))` uses the existing engine after at least one ordinary action on the current level. `GAME_OVER` becomes recoverable while actions remain; only `RESET` is then accepted. Reset preserves `levels_completed`, returns `NOT_FINISHED`, and consumes one action. Cap and target completion remain final.

- [ ] Write a fake-engine test for Level 1 completion → Level 2 `GAME_OVER` → `RESET` → Level 2 completion, with no new engine construction and an action count that includes reset.
- [ ] Run it and confirm the current broker closes at `GAME_OVER`.
- [ ] Implement guarded `RESET`, current-level action tracking, batch stopping at death/reset, and cap precedence.
- [ ] Write and run replay tests for the same trajectory and for rejected reset divergence/full-game reset.
- [ ] Verify the existing private receipt counts failed attempts and reset against the completed level; commit the tested broker/replay path.

### Task 3: Worker behavior and package route

**Files:** `src/asterion/applications/prime/p7/live.py`, `prompt.py`, `src/asterion/capabilities/prime_arc_agi_3_solver/provider.py`, `tests/test_prime_p7_live_command.py`, `tests/test_prime_p7_native_installed.py`, `docs/guides/prime-p7-games-and-official-results.md`.

**Interface:** Worker `act("RESET")` returns an updated view. After `GAME_OVER` with remaining budget, `terminal` is `RESET_REQUIRED`; after reset it is `ACTIVE`. Prompt directs a new plan for the reset level. `ACTION_CAP` and `LEVEL_SOLVED` remain final.

- [ ] Write a worker test that observes `RESET_REQUIRED`, resets, then completes the target level; run it red.
- [ ] Implement terminal mapping and prompt, update the pinned prompt digest, and extend installed-wheel fake-engine test with a reset episode.
- [ ] Run focused tests, lint, docs-check, and promotion-check without provider operations.
- [ ] Update the user guide to explain same-run retry and the ended-process boundary; commit code, tests, and guide.

### Task 4: Review and state

**Files:** `docs/status/CURRENT-STATE.md`, `docs/status/RESUME-NEXT-SESSION.md`, `docs/status/JOURNAL.md`.

- [ ] Review ownership, identity, action data, reset count, replay, score, redaction, and historical compatibility against the final diff.
- [ ] Record exactly which no-model commands passed and that no paid LS20/TU93 continuation has been observed.
- [ ] Commit the recovery checkpoint while preserving the user's existing Makefile comments.
