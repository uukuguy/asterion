# P7 Saved Solutions and Official Submission Implementation Plan

> **For agentic workers:** Use subagent-driven development, with a failing focused test before each behavior change and a review after each independently testable task.

**Goal:** Let P7 solve a selected local game through a selected level, retain verified action prefixes, and execute selected saved solutions in a fresh ARC-AGI-3 Competition scorecard.

**Architecture:** The local operator owns immutable, private action evidence and replays prior levels from the beginning of a fresh local game. The official operator loads and locally verifies a selected prefix before card creation, then executes actions once in a fresh remote game while comparing every observation. The server score and card closure remain authoritative; skipped games never acquire invented runs.

**Tech Stack:** Python 3.12, `arc_agi==0.9.9`, `arcengine==0.9.3`, `unittest`, Make/Orb, Asterion installed wheel.

## Global Constraints

- Local game data and credentials remain outside the wheel; never expose source, actions, prompts, API keys, or private paths on public output.
- Full game IDs include version. A target `LEVEL=N` means completing levels 1 through N in order; the engine cannot jump to N.
- Submission of local work is action execution in a new official Competition game, never uploading an OFFLINE receipt.
- The remote wrapper does not accept a seed. Require initial and per-action observation digest equality; stop on mismatch without retrying `make` or an uncertain action.
- Normal official closure requires all *selected* games attempted. Service-returned score is authoritative and still covers the official catalog; unplayed games remain unplayed.
- Only an explicitly selected saved submission is allowed by the new command. `GAME=all` means all locally verified games, not 25 model runs.
- No real scorecard or model calls during implementation tests. Real paid/full evaluation requires separate authorization and finite budget under `AGENTS.md`.

## Task 1: Strict saved prefix loader

**Files:** Create `src/asterion/applications/prime/p7/solutions.py`; test `tests/test_prime_p7_solutions.py`.

**Interface:** `VerifiedPrefix(game_id, seed, win_levels, levels_completed, transitions, source_run_id, replay_sha256)` is immutable. `load_best_prefix(arc_root: Path, runs_root: Path, game_id: str, seed: int, *, max_level: int | None = None) -> VerifiedPrefix | None` reads a private run, reconstructs canonical `ArcTransition` values including ACTION6 coordinates, validates the sealed trace and summary, and verifies the complete prefix on a fresh OFFLINE engine. When `max_level` truncates a longer run, recompute the prefix replay digest and replay that prefix to its completed-level boundary. Rank candidates by more completed levels, then fewer actions, then lexical run ID. `list_verified_prefixes(arc_root: Path, runs_root: Path, game_ids: tuple[str, ...], seed: int) -> tuple[VerifiedPrefix, ...]` returns one best prefix per exact game ID, sorted.

- [ ] Write a failing `unittest` that imports the existing LS20 history fixture shape and a click-action fixture, then rejects a changed digest, wrong game version, malformed ACTION6, and a symlinked run.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p7_solutions`; expect a missing-module or failed-contract result.
- [ ] Implement the loader using `live.read_trace_entries`, `ArcTransition`, `ArcRunReceipt`, and `replay_arc_run`; bind recording identity, target level, seed and source trace digest before returning the prefix. Never execute a game source through an unvalidated path.
- [ ] Accept historical summaries that omit `game_id`, `seed`, `target_level`, and `win_levels`: derive exact version from validated recording identity and local metadata, then prove the chosen seed/level compatibility through a fresh replay. Accept legacy `sha256:` digest notation.
- [ ] Run the focused test and a no-network diagnostic against the existing LS20 first-level history; expect 20 verified actions and one completed level.
- [ ] Commit the loader and tests.

## Task 2: Local selection and continuation

**Files:** Modify `src/asterion/applications/prime/p7/operator.py`, `src/asterion/applications/prime/p7/game.py`, `Makefile`; test `tests/test_prime_p7_live_command.py` and `tests/test_prime_p7_native_replay.py`.

**Interface:** `make asterion-prime-p7-solve GAME=<short-or-full-id> LEVEL=N` resolves a target prefix; omitted `LEVEL` retains full-game solving. Before launching the model, replay the best verified shorter prefix (`max_level=target_level-1`) through the new run's broker and trace recorder, comparing each transition. Preserve `asterion-prime-p7-level-witness` as an alias.

- [ ] Write a failing test for `LEVEL=2` selection and replay of verified level 1 into a new level-2 run, including a mismatch that stops before model launch.
- [ ] Run the focused tests and confirm the failure describes the missing behavior.
- [ ] Wire the saved prefix into `build_p7_operator_resources` via the existing `_P7BrokerClient` so replayed actions enter the current broker journal and private trace; remove the solve-mode rejection of explicit `LEVEL`.
- [ ] Run focused tests; verify old whole-game command and the independent witness command remain valid.
- [ ] Commit local continuation and tests.

## Task 3: Selected Competition lifecycle and receipt

**Files:** Modify `src/asterion/applications/prime/p7/official.py`, `src/asterion/applications/prime/p7/official_result.py`; test `tests/test_prime_p7_official.py`, `tests/test_prime_p7_official_result.py`, and `tests/test_prime_p7_real_sdk_integration.py`.

**Interface:** A `CompetitionSession` accepts one nonempty exact selected-ID set before `open()`. `close()` requires selected IDs attempted, preserving one `make` per selected game. The receipt distinguishes catalog count, selected count, played runs, skipped count, completed count, and the unmodified server score. Validate one GUID-bound run for each successful selected `make`; skipped catalog entries may be absent from SDK `EnvironmentScorecard.environments` or appear with zero runs. Never read computed `score` or level properties from an empty SDK row (`max()` raises). Reject unknown, duplicate, or extra played rows. An uncertain `make` has no verified GUID and needs recovery, never a completed receipt.

- [ ] Write failing no-network tests for one selected game from a two-game catalog, both documented skipped-row shapes, partial completion, malformed extra runs, missing selected runs, and uncertain `make`.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Implement selected-vs-catalog bookkeeping and strict scorecard parsing without computing a local score or fabricating skipped runs.
- [ ] Run the focused tests and installed SDK HTTP-intercept integration.
- [ ] Commit lifecycle and receipt changes.

## Task 4: Official saved-action executor and operator command

**Files:** Create `src/asterion/applications/prime/p7/official_replay.py`; modify `src/asterion/applications/prime/p7/official_operator.py` and `Makefile`; test `tests/test_prime_p7_official_pipeline.py`, `tests/test_prime_p7_official_operator.py`, and new `tests/test_prime_p7_official_replay.py`.

**Interface:** `execute_saved_prefix(engine: CompetitionEngine, prefix: VerifiedPrefix) -> None` validates exact game/version and level count, compares initial digest before the first action, then dispatches each action once with before/after digest and level checks. `make asterion-prime-p7-official-submit GAME=ls20` loads and verifies saved evidence before card creation; `GAME=all` selects every locally verified game. The saved-action path does not start Pi or call a model. The prior live model evaluation is named `asterion-prime-p7-official-live-eval` and keeps its existing finite bounds.

- [ ] Write failing tests for matching and divergent initial/after observations, ACTION6 coordinates, single dispatch on uncertain failure, partial level scorecard, and model-host absence.
- [ ] Run focused tests and confirm failures.
- [ ] Implement saved execution and operator selection with a separate minimal preflight that needs ARC credentials, local assets, and evidence but no Node, Pi, or model key. Never call `reset()` after official `make`, and never translate local `replay_verified` directly into official success.
- [ ] Run focused tests, installed-wheel tests, lint, and docs checks with all HTTP/model calls intercepted.
- [ ] Commit the selected official command and tests.

## Task 5: Public game sync and operator guide

**Files:** Create `tools/sync_prime_p7_games.py`; modify `Makefile` and `docs/guides/prime-p7-games-and-official-results.md`; test `tests/test_prime_p7_game_sync.py`.

**Interface:** `make asterion-prime-p7-sync-games` obtains the authenticated official catalog, exact metadata, and `/source` bytes through GET only, placing validated game files under the operator-owned external ARC root. It never invokes SDK `NORMAL make` (which would create a scorecard), rejects differing bytes for an existing exact version, never follows a symlink, validates `class_name` against the source filename, and publishes metadata/source together. The SDK derives filenames from `class_name.lower()` while local discovery expects `<short-id>.py`; sync must preserve both lookups. The guide shows list, sync, local `GAME`/`LEVEL`, saved progress, selected submission, and official receipt lookup.

- [ ] Write failing injected-HTTP tests for 25-game catalog parsing, exact version/source paths, symlink and overwrite rejection, and public output redaction.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p7_game_sync`; expect missing behavior.
- [ ] Implement the GET-only sync with atomic writes and strict operator root/path validation.
- [ ] Run focused tests and docs-check; perform one controlled sync only after the tests pass and confirm the local inventory matches the official 25-ID catalog.
- [ ] Commit source sync, guide, and tests.

## Integration gate

- [ ] Run the focused P7 `unittest` set, `make lint`, `make docs-check`, `make promotion-check`, and `git diff --check`; inspect changed code with a critical reviewer.
- [ ] Run installed-wheel, no-model, HTTP-intercept end-to-end selected saved-prefix submission for partial LS20 and skipped games.
- [ ] Run `make asterion-prime-p7-official-preflight`; report selected catalog and bounds. Creating a real official scorecard remains a separate externally visible step and is never inferred from green tests.
- [ ] Update `docs/status/RESUME-NEXT-SESSION.md` with verified facts, remaining real-submit boundary, and exact commands; journal commits and leave Git clean.
