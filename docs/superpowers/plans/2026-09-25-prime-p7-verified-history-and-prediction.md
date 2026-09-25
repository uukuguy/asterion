# P7 Verified History and Prediction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add an application-owned, private, bounded history API and stepwise prediction checking to P7 so verified Level 1 prefixes become usable evidence during Level 2 solving.

**Architecture:** Preserve ARC actions, level order, broker identity, replay, action caps, and deadlines. Extend the P7 application broker with immutable settled-frame history and a checked action queue; expose those operations through the existing restricted socket and generated p7_client module. Replay a verified prefix into the same broker before the model starts, while raw frames and prediction details remain private run evidence.

**Tech Stack:** Python 3.10+, unittest, frozen dataclasses, existing ArcBroker, PrimeTraceRecorder, restricted IPython worker, Unix socket bridge, deterministic offline fake engines.

## Global Constraints

- Preserve the ARC SDK action set, ordered level progression, action caps, 30-minute deadline, and five-minute no-action stop line.
- Do not read game source, other games, unverified runs, credentials, network resources, or old session code.
- Keep this in application-layer P7 code; do not change generic framework protocols.
- act remains for one-step exploration; act_checked is the only multi-step prediction operation.
- A checked plan has at most 20 actions and every item has a distinguishing expected result.
- History and raw frames are private to one exact game ID, seed, and run ID; they never enter public receipts, webpages, or framework protocols.
- History or prediction validation failure stops the current plan with a fixed safe error and performs no implicit recovery.
- All tests are zero-model and offline until the final fixed DeepSeek Flash A/B study.

## File Map

- Create src/asterion/applications/prime/p7/verified_history.py: immutable records, bounded query validation, stable-frame diffs, expected-result validation.
- Modify src/asterion/applications/prime/p7/broker.py: capture sequence-zero and post-action settled observations; implement history/frame/checked-plan operations.
- Modify src/asterion/applications/prime/p7/operator.py: adapt the broker API, bind one run identity, replay and verify prefixes before model startup.
- Modify src/asterion/applications/prime/p7/live.py: extend the worker socket and generated module.
- Modify src/asterion/applications/prime/p7/ipython_host.py: validate and seal the expanded module surface.
- Modify src/asterion/applications/prime/p7/prompt.py: require history queries, falsifiable hypotheses, and checked plans after evidence.
- Create tests/test_prime_p7_verified_history.py.
- Modify tests/test_prime_p7_live_command.py and tests/test_prime_p7_native_broker.py.
- Modify docs/guides/prime-p7-games-and-official-results.md and, only with passing evidence, docs/status/PRIME-P7-ACCEPTANCE.md.

### Task 1: Define the private history and prediction contracts

Files:
- Create: src/asterion/applications/prime/p7/verified_history.py
- Test: tests/test_prime_p7_verified_history.py

Interfaces:
- Consumes broker observation grids, ArcAction, and ArcTransition shapes.
- Produces ArcHistoryRecord, ArcPredictionError, stable_changed_cells, validate_history_query, and validate_prediction.

- [ ] Step 1: Write failing contract tests.

    class TestVerifiedHistory(unittest.TestCase):
        def test_sequence_zero_has_no_action_and_public_view_has_no_frame(self):
            record = ArcHistoryRecord.initial(
                game_id="ls20-9607627b", seed=0, run_id="private-run",
                frame=((1, 2), (3, 4)), levels_completed=0, state="NOT_FINISHED",
            )
            self.assertEqual(record.sequence, 0)
            self.assertIsNone(record.action)
            self.assertIsNone(record.before_state_sha256)
            self.assertIsNone(record.before_frame_sha256)
            self.assertEqual(record.after_frame_sha256, record.stable_frame_sha256)
            public = record.public_view()
            self.assertNotIn("frame", public)
            self.assertNotIn("private-run", repr(public))

        def test_changed_cells_are_sorted_and_bounded(self):
            before = tuple(tuple(0 for _ in range(3)) for _ in range(3))
            after = tuple(tuple(1 for _ in range(3)) for _ in range(3))
            total, sample, omitted = stable_changed_cells(before, after)
            self.assertEqual(total, 9)
            self.assertEqual(sample, tuple(
                (x, y, 0, 1) for y in range(3) for x in range(3)
            ))
            self.assertEqual(omitted, 0)
            total, sample, omitted = stable_changed_cells(before, after, limit=8)
            self.assertEqual((total, len(sample), omitted), (9, 8, 1))

        def test_query_rejects_future_zero_and_oversize_pages(self):
            for start, limit in ((-1, 1), (0, 0), (0, 33), (4, 1)):
                with self.subTest(start=start, limit=limit), self.assertRaises(ArcPredictionError):
                    validate_history_query(start=start, limit=limit, latest_sequence=3)

        def test_prediction_requires_distinguishing_expectation(self):
            action = {"name": "ACTION1", "data": {}}
            with self.assertRaisesRegex(ArcPredictionError, "P7 prediction is unavailable"):
                validate_prediction(
                    {"action": action, "expect": {"levels_completed": 0}},
                    current_levels=0,
                )
            self.assertEqual(
                validate_prediction(
                    {"action": action, "expect": {"cell": {"x": 2, "y": 3, "value": 7}}},
                    current_levels=0,
                )[0],
                "ACTION1",
            )
            self.assertEqual(
                validate_prediction(
                    {"action": action, "expect": {"state": "WIN"}}, current_levels=0
                )[0],
                "ACTION1",
            )

- [ ] Step 2: Run the focused tests and confirm the contract is absent.

Run: uv run python -m unittest -v tests.test_prime_p7_verified_history

Expected: FAIL with an import error for the new application module.

- [ ] Step 3: Implement the immutable contract with these exact types and algorithms.

Use Grid = tuple[tuple[int, ...], ...], CellChange = tuple[int, int, int, int], and a frozen, slotted ArcHistoryRecord with fields game_id, seed, run_id, sequence, action (str or None), data, before_state_sha256, after_state_sha256, before_frame_sha256, after_frame_sha256, frame, changed_cell_count, changed_cells, changed_cells_omitted, levels_completed, and state. Sequence zero has action None and no before hash. The record property stable_frame_sha256 is an alias for after_frame_sha256; public_view includes state hashes, frame hashes, changed_cell_count, a bounded changed_cells sample, changed_cells_omitted, levels_completed, and state, but never frame, run_id, game_id, seed, or model data.

Implement stable_changed_cells(before, after, limit=80) by validating equal rectangular grids, scanning row-major, incrementing total for every difference, retaining only the first limit cells, and returning the pair (total, sample, total - len(sample)); a large diff is valid and is never rejected or silently truncated. Implement validate_history_query(start, limit, latest_sequence) by requiring integer start and limit, 0 <= start <= latest_sequence, and 1 <= limit <= 32. Serialize the public page with compact JSON and reject the query if its UTF-8 length exceeds 16384 bytes.

Implement validate_prediction(value, current_levels) by requiring an action object with name/data in the same canonical shape as ArcBroker, and an expect object containing at least one of: cell {x,y,value}; frame_sha256; levels_completed strictly greater than current_levels; or state equal to WIN/GAME_OVER. Reject an unchanged level-only expectation, malformed coordinates, unknown keys, and non-integer colors. Raise ArcPredictionError with the fixed message P7 prediction is unavailable.

- [ ] Step 4: Run tests and lint.

Run: uv run python -m unittest -v tests.test_prime_p7_verified_history && uv run ruff check src/asterion/applications/prime/p7/verified_history.py tests/test_prime_p7_verified_history.py

Expected: all tests PASS and Ruff reports no violations.

- [ ] Step 5: Commit the contract.

    git add src/asterion/applications/prime/p7/verified_history.py tests/test_prime_p7_verified_history.py
    git commit -m "feat(p7): define bounded verified history contracts"

### Task 2: Capture history in ArcBroker and implement checked plans

Files:
- Modify: src/asterion/applications/prime/p7/broker.py
- Test: tests/test_prime_p7_native_broker.py
- Test: tests/test_prime_p7_verified_history.py

Interfaces:
- Consumes Task 1 contracts and existing observation digest validation.
- Produces ArcBroker.history(start, limit), ArcBroker.frame_at(sequence), and ArcBroker.act_checked(plan).

- [ ] Step 1: Write failing broker tests.

Add a local _HistoryEngine fixture with game_id "ls20-9607627b", seed 0, one available ACTION1, a one-cell frame containing its call count, levels_completed 0, state NOT_FINISHED, and a calls list. Its step method increments the call count and returns the new observation. Use the existing _Engine and _ResetEngine fixtures for level and GAME_OVER cases.

    def test_history_starts_at_zero_and_records_settled_before_after_frames(self):
        broker = ArcBroker(
            engine=_HistoryEngine(),
            game=P7GameSelection("ls20-9607627b", 0, 2),
        )
        self.assertEqual(broker.history(0, 32)[0]["sequence"], 0)
        broker.act(("ACTION1",))
        page = broker.history(0, 32)
        self.assertEqual([item["sequence"] for item in page], [0, 1])
        self.assertEqual(broker.frame_at(0), [[0]])
        self.assertEqual(broker.frame_at(1), [[1]])
        page[1]["changed_cells"].append((0, 0, 0, 9))
        self.assertEqual(broker.history(0, 32)[1]["changed_cells"], [(0, 0, 0, 1)])

    def test_checked_plan_stops_at_first_mismatch_and_does_not_dispatch_tail(self):
        engine = _HistoryEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection("ls20-9607627b", 0, 2))
        result = broker.act_checked([
            {"action": {"name": "ACTION1", "data": {}},
             "expect": {"cell": {"x": 0, "y": 0, "value": 9}}},
            {"action": {"name": "ACTION1", "data": {}},
             "expect": {"cell": {"x": 0, "y": 0, "value": 2}}},
        ])
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["stop_reason"], "prediction-mismatch")
        self.assertEqual(engine.calls, ["ACTION1"])

    def test_checked_plan_stops_at_level_advance_and_game_over(self):
        advanced = ArcBroker(
            engine=_Engine(level_after=1),
            game=P7GameSelection("ls20-9607627b", 0, 2),
        )
        result = advanced.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"levels_completed": 1},
        }])
        self.assertEqual(result["stop_reason"], "level-advanced")
        self.assertEqual(result["applied_count"], 1)
        failed = ArcBroker(
            engine=_ResetEngine(game_over_after=1),
            game=P7GameSelection("ls20-9607627b", 0, 2),
        )
        result = failed.act_checked([{
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"state": "GAME_OVER"},
        }, {
            "action": {"name": "ACTION1", "data": {}},
            "expect": {"cell": {"x": 0, "y": 0, "value": 2}},
        }])
        self.assertEqual(result["stop_reason"], "game-over")
        self.assertEqual(result["applied_count"], 1)

- [ ] Step 2: Run the failing tests.

Run: uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_verified_history

Expected: FAIL because the broker has none of the history or checked-plan methods.

- [ ] Step 3: Capture sequence zero and each stable post-action observation without changing ArcBroker construction. Add bind_history(run_id: str) to ArcBroker; it validates one nonempty ASCII run ID, initializes sequence zero from self._initial.frame[-1], and is called by the application adapter immediately after constructing the broker. When history is bound, the existing act loop appends one ArcHistoryRecord per transition using the full observation digest for before_state_sha256/after_state_sha256 and a separate digest of before.frame[-1]/after.frame[-1] for frame hashes. Keep ArcTransition, trace events, replay hashes, and action count unchanged. If history is unbound, history/frame_at/act_checked raise the fixed unavailable error.

- [ ] Step 4: Implement bounded accessors and the checked loop. Add history(start: int, limit: int), frame_at(sequence: int), and act_checked(plan: object). history validates the page, checks the compact JSON byte bound, and deep-copies public dictionaries. frame_at rejects future sequences and returns a deep-copied 2-D list of the stable frame. act_checked first performs one structural precheck over the full 1–20 item list (shape, canonical actions, and expectation syntax) without inspecting future observations; then it dispatches one item at a time, compares the expected cell/frame/state/level result with the new history record, and returns applied_count, stop_reason, mismatch, observation, terminal, batch, and unexecuted_count. Stop immediately at mismatch, unavailable action, level boundary, GAME_OVER, or cap; do not dynamically inspect or dispatch any tail item after a stop, and never count it.

- [ ] Step 5: Run regressions.

Run: uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_verified_history tests.test_prime_p7_multilevel_receipt

Expected: all tests PASS.

- [ ] Step 6: Commit the broker.

    git add src/asterion/applications/prime/p7/broker.py tests/test_prime_p7_native_broker.py tests/test_prime_p7_verified_history.py
    git commit -m "feat(p7): capture verified history and check action predictions"

### Task 3: Expose the application API through the restricted worker

Files:
- Modify: src/asterion/applications/prime/p7/operator.py
- Modify: src/asterion/applications/prime/p7/live.py
- Modify: src/asterion/applications/prime/p7/ipython_host.py
- Test: tests/test_prime_p7_live_command.py
- Test: tests/test_prime_p7_official_operator.py

Interfaces:
- Consumes Task 2 broker methods and the existing Unix socket protocol.
- Produces worker-visible history(start, limit), frame_at(sequence), and act_checked(plan) with fixed safe failures.

- [ ] Step 1: Add failing generated-module tests.

    def test_worker_exposes_history_frame_and_checked_plan(self):
        namespace = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        calls = []
        namespace["_call"] = lambda method, *args: (
            calls.append((method, args)) or {
                "history": [{"sequence": 0, "action": None, "data": {},
                             "before_state_sha256": None, "after_state_sha256": "sha256:" + "0" * 64,
                             "before_frame_sha256": None, "after_frame_sha256": "sha256:" + "1" * 64,
                             "changed_cells": [], "levels_completed": 0, "state": "NOT_FINISHED"}],
                "frame_at": [[1]],
                "act_checked": {"applied_count": 1, "stop_reason": "matched",
                                "mismatch": None, "unexecuted_count": 0},
            }[method]
        )
        history_fn = namespace["history"]
        frame_fn = namespace["frame_at"]
        checked_fn = namespace["act_checked"]
        self.assertEqual(history_fn(0, 1)[0]["sequence"], 0)
        self.assertEqual(frame_fn(0), [[1]])
        checked_fn([{"action": {"name": "ACTION1", "data": {}},
                    "expect": {"state": "WIN"}}])
        self.assertEqual([name for name, _ in calls], ["history", "frame_at", "act_checked"])

Add socket tests for unknown methods, malformed history pages, and a history-page response over 16 KiB; each returns only protocol, id, and ok:false. Preserve complete observe, act, act_checked, and frame_at responses, including valid multiframe observations larger than 16 KiB; a post-action response cap must never hide a committed action.

- [ ] Step 2: Run the failing boundary tests.

Run: uv run python -m unittest -v tests.test_prime_p7_live_command

Expected: FAIL because the generated module and validator expose only observe, status, and act.

- [ ] Step 3: Extend the sealed facade, server, and broker adapter. Add strict history(start, limit), frame_at(sequence), and act_checked(plan) methods to _P7BrokerClient. Each validates input, delegates to the bound ArcBroker, deep-copies returned values, and maps all internal failures to P7OperatorError("P7 host services are unavailable"). Give _P7BrokerClient an exact variant argument with values verified or legacy; verified mode rejects act batches longer than one, while legacy preserves the current batched act behavior for the A/B control. In build_p7_operator_resources, bind the enclosing run_id to the already-created broker before constructing the client; prefix replay and new actions therefore share one history. Refactor _P7BrokerClient.act so act_checked uses the exact same transition-to-arc.action recorder path, ensuring checked actions cannot bypass trace accounting. Extend the sealed facade and server allowlists to exactly six names: observe, status, act, history, frame_at, act_checked; reject all other methods and argument shapes.

- [ ] Step 4: Extend the generated worker module and validator. Add exact wrappers:

    def history(start, limit):
        return _call("history", start, limit)

    def frame_at(sequence):
        return _call("frame_at", sequence)

    def act_checked(plan):
        return _call("act_checked", plan)

Keep act_and_observe as an act helper. Update _valid_client_module to require exactly the six public functions and exact argument counts. Keep raw animation layers and private IDs out of helper summaries.

- [ ] Step 5: Run boundary and official tests.

Run: uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_operator tests.test_prime_p7_official_installed

Expected: all tests PASS; no frame sentinel or private path appears in public output.

- [ ] Step 6: Commit the boundary.

    git add src/asterion/applications/prime/p7/operator.py src/asterion/applications/prime/p7/live.py src/asterion/applications/prime/p7/ipython_host.py tests/test_prime_p7_live_command.py tests/test_prime_p7_official_operator.py
    git commit -m "feat(p7): expose bounded history and checked actions to worker"

### Task 4: Admit replayed history and update the shared prompt

Files:
- Modify: src/asterion/applications/prime/p7/operator.py
- Modify: src/asterion/applications/prime/p7/prompt.py
- Modify: src/asterion/applications/prime/p7/official_operator.py only if it duplicates prompt text
- Test: tests/test_prime_p7_live_command.py
- Test: tests/test_prime_p7_official_operator.py
- Modify: src/asterion/capabilities/prime_arc_agi_3_solver/provider.py
- Modify: src/asterion/capabilities/prime_arc_agi_3_gameplay/provider.py
- Test: tests/test_prime_arc_agi_3_solver_package.py
- Test: tests/test_prime_arc_agi_3_gameplay_package.py

Interfaces:
- Consumes existing VerifiedPrefix, Task 2 history, and one shared P7_SOLVE_PROMPT.
- Produces pre-model prefix/history admission, common instructions, and a research-only legacy/verified variant marker.

- [ ] Step 1: Add failing prefix-replay boundary tests to tests/test_prime_p7_live_command.py. Use the existing _FullGameEngine and _apply_saved_prefix fixture: bind a broker history to run-1, replay the verified transitions through _P7BrokerClient, assert history sequence zero plus one record per transition, and assert the final record's before/after state hashes exactly equal the corresponding ArcTransition hashes while its frame hashes are separately present. Mutate one expected transition digest and assert _apply_saved_prefix raises P7OperatorError before any model worker starts.

- [ ] Step 2: Run the failing tests.

Run: uv run python -m unittest -v tests.test_prime_p7_live_command

Expected: FAIL because prefix replay does not currently bind or expose history.

- [ ] Step 3: Keep load_best_prefix and solutions.py unchanged. Existing code already verifies identity, sealing, summary, and replay. In run_live, after resources create and bind the current run ID, replay the selected VerifiedPrefix through _apply_saved_prefix before resolving the application or starting the model. Assert the broker history length is len(prefix.transitions) + 1, every transition's state hashes match, the final level equals prefix.levels_completed, and the final frame is the settled frame captured after the last replay action. Any mismatch raises fixed P7OperatorError("P7 saved prefix is unavailable") before Pi/model execution begins; constructing and closing the host worker for admission is allowed.

- [ ] Step 4: Update P7_SOLVE_PROMPT with this exact behavior:

    For a target above Level 1, call p7_client.history(0, 32) before planning
    and request further pages until the sequence containing the Level 1
    boundary is returned; stop paging at that boundary. Each page contains
    observed facts only: action, stable before/after digests, changed cells,
    level count, and SDK state. Use p7_client.frame_at(sequence) only for a
    sequence already returned by history; it returns that occurred settled
    grid. Write hypotheses that history could disprove. Unknown
    mechanics require one action at a time. Once a plan has evidence, use
    p7_client.act_checked(plan), with no more than 20 items. Every item must
    include a distinguishing expected cell value, full settled-frame hash, level
    advance, or terminal state. The code result is authoritative: on first
    mismatch, unavailable action, level boundary, GAME_OVER, or cap, the
    remaining plan was not executed. Never claim an unchecked prediction passed
    from model text or count unexecuted items.

Use the same prompt in local and official entry points. Define P7_HISTORY_VARIANT_ENV = "ASTERION_PRIME_P7_HISTORY_VARIANT" and resolve only the exact values verified (default) and legacy. A local research invocation may select legacy; official mode rejects legacy before model execution. Pass the resolved variant into _P7BrokerClient and write it only to private diagnostics. In verified mode, unknown mechanics must use one-item act calls and evidence-backed multi-step plans must use act_checked; legacy mode retains the current batched act behavior for the paired research comparison. Add a zero-model test covering default verified, explicit legacy in solve mode, and official rejection. Compute the new prompt digest and replace P7_SOLVE_PROMPT_SHA256 in both solver/provider.py and gameplay/provider.py. The package tests must calculate the digest from P7_SOLVE_PROMPT rather than retaining the old literal.

- [ ] Step 5: Run integration tests.

Run: uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_operator tests.test_prime_arc_agi_3_solver_package tests.test_prime_arc_agi_3_gameplay_package

Expected: all tests PASS; malformed prefixes fail before worker creation; prompt identity is shared and output remains redacted.

- [ ] Step 6: Commit prefix and prompt integration.

    git add src/asterion/applications/prime/p7/operator.py src/asterion/applications/prime/p7/prompt.py src/asterion/applications/prime/p7/official_operator.py src/asterion/capabilities/prime_arc_agi_3_solver/provider.py src/asterion/capabilities/prime_arc_agi_3_gameplay/provider.py tests/test_prime_p7_live_command.py tests/test_prime_p7_official_operator.py tests/test_prime_arc_agi_3_solver_package.py tests/test_prime_arc_agi_3_gameplay_package.py
    git commit -m "feat(p7): replay verified history before level-two solving"

### Task 5: Record private accounting for targeted A/B runs

Files:
- Modify: src/asterion/applications/prime/p7/live.py
- Modify: src/asterion/applications/prime/p7/operator.py
- Test: tests/test_prime_p7_live_command.py
- Test: tests/test_prime_p7_official_pipeline.py

Interfaces:
- Consumes checked results and private history from Tasks 2–4.
- Produces private history/prediction counters and a comparable legacy/verified record without changing scorecard payloads, the fixed sweep campaign schema, or campaign resume behavior.

- [ ] Step 1: Add failing accounting/privacy tests.

    def test_unexecuted_checked_tail_is_absent_from_trace(self):
        result = client.act_checked(plan_with_first_mismatch)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["unexecuted_count"], 1)
        self.assertEqual(
            len(tuple(e for e in recorder.snapshot() if e.kind == "arc.action")), 1
        )

    def test_public_receipt_has_no_frames_hypotheses_or_private_path(self):
        rendered = json.dumps(public_receipt, sort_keys=True)
        self.assertNotIn("frame", rendered)
        self.assertNotIn("hypothesis", rendered)
        self.assertNotIn(str(private_root), rendered)

Add an operator-summary test that two timestamped runs retain equal model, game, seed, target, cap, deadline, and stall fields while their private prediction_variant markers differ. Do not modify tools/run_prime_p7_sweep.py, its campaign JSON schema, or resume identity.

- [ ] Step 2: Run the failing tests.

Run: uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_pipeline

Expected: FAIL because summaries have no prediction accounting or variant.

- [ ] Step 3: Persist bounded private diagnostics. Extend write_summary with counts, first/last sequence, checked-plan count, matched expectations, mismatches, and unexecuted items. Store no grids, changed-cell lists, model text, hypotheses, or paths in public output. Add private experiment fields and keep official scorecard assembly unchanged.

- [ ] Step 4: Keep campaign accounting unchanged. For a later targeted A/B, launch two ordinary timestamped P7 run directories with identical game, seed, target, cap, deadline, and stall settings and a private prediction_variant marker. Read action and token counts from each existing summary and sealed trace; do not add fields to tools/run_prime_p7_sweep.py, alter campaign resume identity, or overwrite either run.

- [ ] Step 5: Run privacy tests and lint.

Run: uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_pipeline && uv run ruff check src/asterion/applications/prime/p7

Expected: all tests PASS and no private frame or hypothesis appears in public JSON.

- [ ] Step 6: Commit accounting.

    git add src/asterion/applications/prime/p7/live.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_live_command.py tests/test_prime_p7_official_pipeline.py
    git commit -m "feat(p7): record private prediction diagnostics for A/B runs"

### Task 6: Document and verify the complete implementation

Files:
- Modify: docs/guides/prime-p7-games-and-official-results.md
- Modify: docs/status/PRIME-P7-ACCEPTANCE.md only with passing command results

- [ ] Step 1: Document the operator procedure.

    make asterion-prime-p7-games
    ASTERION_PRIME_P7_GAME_ID=ls20-9607627b ASTERION_PRIME_P7_TARGET_LEVEL=2 make asterion-prime-p7-level-witness
    ASTERION_PRIME_P7_GAME_ID=ls20-9607627b ASTERION_PRIME_P7_TARGET_LEVEL=2 make asterion-prime-p7-solve

Explain history facts, settled frame_at, one-step act, checked act_checked, mismatch stopping, separate timestamped retries, and private A/B metrics. State that one successful run cannot prove a strategy improvement.

- [ ] Step 2: Run provider-free documentation checks.

Run: make docs-check

Expected: PASS with no generated untracked files.

- [ ] Step 3: Run focused P7 verification.

Run: uv run python -m unittest -v tests.test_prime_p7_verified_history tests.test_prime_p7_native_broker tests.test_prime_p7_live_command tests.test_prime_p7_official_operator tests.test_prime_p7_official_pipeline tests.test_prime_arc_agi_3_solver_package tests.test_prime_arc_agi_3_gameplay_package

Expected: all tests PASS with no provider or ARC network call.

- [ ] Step 4: Run repository gates.

Run: make promotion-check && make lint && make check

Expected: every promotion command, lint, and check passes; record exact results in the status document.

- [ ] Step 5: Run one no-model installed-wheel preflight.

Run: make asterion-prime-p7-official-preflight

Expected: official catalog readiness and action/deadline limits are reported without opening a scorecard or invoking a model.

- [ ] Step 6: Commit docs and verified status.

    git add docs/guides/prime-p7-games-and-official-results.md docs/status/PRIME-P7-ACCEPTANCE.md
    git commit -m "docs(p7): document verified history and prediction checks"

## Final A/B Run Gate

After provider-free gates pass, run a finite pair only from an already saved Level 2 starting point. Use the same DeepSeek Flash model, game ID, seed, action cap, 30-minute deadline, and five-minute no-action stop for legacy and verified. Use fresh timestamped run IDs, never overwrite prior runs, and record:

    game_id, seed, target_level, variant, run_id, outcome,
    completed_levels, level_two_new_actions, first_effective_action_sequence,
    repeated_noop_count, input_tokens, output_tokens, elapsed_seconds

Do not submit an official scorecard from this experiment. Compare private records only after both attempts close; every claimed improvement must be supported by action and token evidence.

## Self-Review

- Spec coverage: Task 1 covers bounded records, stable diffs, separate state/frame hashes, expected-result validation, and immutable projections; Task 2 covers same-broker prefix replay history, sequence zero, settled frames, checked execution, level/GAME_OVER/cap stops, and exact action accounting; Task 3 covers restricted socket and worker API; Task 4 covers prompt variant routing and both provider digests; Task 5 covers safe failures, privacy, usage accounting, and paired targeted runs without touching the campaign; Task 6 covers documentation and named gates.
- Placeholder scan: no implementation step depends on TBD, TODO, or an unspecified edge-case instruction. Test snippets are concrete and contain no ellipsis marker.
- Type consistency: ArcHistoryRecord is produced by Task 1, stored by Task 2, projected by Task 3, consumed by Task 4, and counted by Task 5. act_checked(plan) and its result keys are identical across broker, operator, socket, module, prompt, and tests.
- Boundary limitation: this plan does not claim prediction checks improve ARC scores until the paired DeepSeek Flash A/B run supplies evidence.
