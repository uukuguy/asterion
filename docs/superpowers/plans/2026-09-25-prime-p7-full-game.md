# P7 Full-Game Solver Implementation Plan

> **For agentic workers:** Use test-driven development for each task; run the named test red before production changes and green afterward. Steps use checkbox syntax for tracking.

**Goal:** Make the normal P7 solve finish a complete selected ARC-AGI-3 game and never certify a partial level as a full win.

**Architecture:** An application-owned catalog resolves an exact game definition from external metadata. A game selection carries complete-game level count and a finite per-game action cap. The Broker, local replay, private receipt, and operator agree on a terminal `WIN`; legacy level witnesses remain separately identifiable.

**Tech Stack:** Python 3.12, `arc_agi`/`arcengine` installed wheels, `unittest`, Make, packaged-wheel test.

## Global Constraints

- Do not import ARC game source during metadata listing or selection.
- Preserve old partial receipts and replay hashes as historical evidence.
- Normal solve never claims PASS before `state == WIN` and `levels_completed == win_levels`.
- Do not execute a paid solve as a test.
- Keep the user's existing Makefile comments outside commits unless explicitly requested.

---

### Task 1: Catalog and full-game selection

**Files:** `src/asterion/applications/prime/p7/game.py`; `tests/test_prime_p7_native_game.py`; `tests/test_prime_p7_game_inventory.py`.

**Interface:** `resolve_game_selection(environment, arc_root)` loads exact `game_id`, `baseline_actions`, `win_levels`, and a full-game target from validated metadata. A short alias resolves only if exactly one version exists. A separate explicit development selector may set `target_level < win_levels`.

- [ ] Add a test with a new valid metadata game and assert it resolves without a hard-coded `_BASELINES` entry; add ambiguous alias, symlink, malformed baseline, and wrong identity cases.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p7_native_game` and confirm the new valid-game test fails because the ID is currently rejected.
- [ ] Implement the catalog read and immutable selected definition. Preserve the prior fixed metadata checks for historical receipt validation, but derive new selections from the exact metadata read.
- [ ] Run the named test and `tests.test_prime_p7_game_inventory`; commit catalog code/tests.

### Task 2: Finite full-game action budget and terminal proof

**Files:** `src/asterion/applications/prime/p7/score.py`, `broker.py`, `replay.py`, `private_trace.py`; `tests/test_prime_p7_native_broker.py`, `tests/test_prime_p7_native_replay.py`, `tests/test_prime_p7_multilevel_receipt.py`.

**Interface:** `action_cap = min(5000, max(1000, 2 * sum(baseline_actions)))` for a complete game. The selected game supplies the cap to Broker and replay. A complete-game receipt requires the final observation to be `WIN`; a level witness can continue using an explicitly marked partial terminal.

- [ ] Write a fake seven-level game test that reaches level 7 while still `NOT_FINISHED` and must fail full-game certification; write a `WIN` success test and one cap test above 500 actions.
- [ ] Run the focused new tests red; the current broker ends at target count and the fixed 500-action cap.
- [ ] Move cap checks to the selected game and distinguish complete `WIN` from partial level witness in Broker, replay, and private receipt. Keep old no-data journal digests unchanged.
- [ ] Run the focused tests, then `uv run python -m unittest discover -s tests -p 'test_prime_p7*.py' -q`; commit.

### Task 3: Normal solve and development witness routing

**Files:** `Makefile`, `src/asterion/applications/prime/p7/operator.py`, `prompt.py`, `live.py`, `src/asterion/capabilities/prime_arc_agi_3_solver/provider.py`; `tests/test_prime_make_presets.py`, `tests/test_prime_p7_live_command.py`, `tests/test_prime_p7_native_installed.py`.

**Interface:** `make asterion-prime-p7-solve GAME=<alias-or-exact-id>` selects a complete game. `LEVEL` is rejected on this production route with a clear message. A separate `asterion-prime-p7-level-witness` retains bounded partial checks. Worker terminal `GAME_SOLVED` requires SDK `WIN`; `LEVEL_ADVANCED` continues play.

- [ ] Write Make and installed-wheel tests showing default/full-game target, explicit witness target, and rejection of `LEVEL` on normal solve; run them red.
- [ ] Implement command routing and prompt wording; update the pinned prompt digest and full-game public status. Keep each run in its own private directory.
- [ ] Run the named tests, `make lint`, and `make docs-check`; commit code/tests.

### Task 4: User guidance and packaged verification

**Files:** `docs/guides/prime-p7-games-and-official-results.md`, `docs/status/CURRENT-STATE.md`, `docs/status/RESUME-NEXT-SESSION.md`, `docs/status/JOURNAL.md`.

- [ ] Explain `GAME`, full-game `WIN`, current-level `RESET`, historical partial evidence, and why ending a process cannot resume a local instance.
- [ ] Run `make promotion-check`; report the exact command result and provider operation count.
- [ ] Review final diff for ownership, redaction, compatibility, score/count identity, and user's Makefile comments; commit docs and recovery checkpoint.
