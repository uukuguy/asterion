# Prime P7 Controlled Game Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the installed P7 preset select either the existing ls20 game or the new tu93 game by exact operator-owned ID and seed, then verify the selected game without model actions.

**Architecture:** A P7 application selection value is resolved once before execution and passed to engine, broker, replay, score, and public receipt. Make forwards only game identity values; the model, limits, and framework contracts stay fixed.

**Tech Stack:** Python 3.12+, unittest, Make, Orb, official ARC-AGI-3 local wheels.

## Global Constraints

- Keep the authoritative Python application under `src/asterion/applications/prime/p7/` and game data outside the wheel.
- Permit only `ls20-9607627b` and `tu93-0768757b` until another action interface and score profile is reviewed.
- Do not call the model or perform an ARC action during preflight verification.
- Keep public errors and receipts free of private paths, payloads, and credentials.

---

### Task 1: Resolve one exact game selection

**Files:** Create `src/asterion/applications/prime/p7/game.py`; test in `tests/test_prime_p7_native_game.py`.

**Interfaces:** `P7GameSelection(game_id, seed, win_levels, first_level_baseline_actions)` and `resolve_game_selection(environment, arc_root) -> P7GameSelection`.

- [ ] Write a unittest matrix that resolves the default ls20 and explicit tu93 selections, then rejects an unknown ID, malformed seed, missing source/metadata, and mismatched metadata before execution.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p7_native_game` and confirm the new tests fail on the missing interface.
- [ ] Implement immutable selection, a two-game profile map, exact local asset checks, and bounded decimal seed parsing.
- [ ] Rerun the same unittest module and confirm it passes.

### Task 2: Carry selection through execution and evidence

**Files:** Modify `src/asterion/applications/prime/p7/{live,operator,broker,replay,private_trace,score}.py`; extend `tests/test_prime_p7_native_{broker,replay,provider}.py` and add score coverage.

**Interfaces:** `ArcadeEngine(..., game=selection)`, `ArcBroker(engine=..., game=selection)`, `replay_arc_run(..., game=selection)`; the receipt and score use the broker's sealed selection.

- [ ] Add a tu93 fake-engine test with 9 levels that seals and replays as tu93, and a mismatch test that rejects before observation. Add a first-level score assertion using baseline 19 and denominator 45.
- [ ] Run the focused unittest modules and confirm they fail for the current fixed ls20/7-level logic.
- [ ] Replace fixed game identity and level-count reads with the selected value across engine, broker, replay, operator, and receipt; calculate score from the selected profile.
- [ ] Rerun the focused unittest modules and confirm both old ls20 and new tu93 cases pass.

### Task 3: Forward the selection and verify the installed boundary

**Files:** Modify `Makefile`, `docs/status/PRIME-P1-P7-ACCEPTANCE.md`, and `src/asterion/applications/prime/p7/run_story/evidence.py`; test the Make recipe, installed application, and `tests/test_prime_arc_agi_3_run_story.py`.

**Interfaces:** `ASTERION_PRIME_P7_GAME_ID` and `ASTERION_PRIME_P7_SEED` are forwarded from Make to Orb; omitted values select ls20 seed 0.

- [ ] Correct the P7 recipe's literal `@exec`, forward both variables through shell arguments, and document the exact tu93 command.
- [ ] Add a 9-level run-story recording test that fails against the current 7-level reader, then preserve the recorded level count in validation and hashing.
- [ ] Run `make -n asterion-prime-p7-solve` and inspect the generated shell command for the two forwarded values and absence of `@exec`.
- [ ] Run P7-focused unittest modules and `make promotion-check` for the packaged application change.
- [ ] Construct and reset tu93 in the Orb offline engine with zero actions; confirm exact ID, actions `[1,2,3,4]`, and 9 levels.
- [ ] Review the diff for identity leaks or unrelated changes, then commit the focused implementation.
