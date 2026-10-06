from __future__ import annotations

import json
import contextlib
import io
import asyncio
import logging
from collections.abc import Mapping
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7 import live as live_module
from asterion.applications.prime.p7.ipython_host import p7_client_facade
from tools.compare_prime_p7_runs import build_parser as build_compare_parser
from tools.compare_prime_p7_runs import main as compare_main


def _sealed_trace(path: Path, *, outcome: str, action_count: int = 1) -> Path:
    trace_root = path / outcome
    trace_root.mkdir()
    recorder = PrimeTraceRecorder(trace_root)
    identities = {"model_id": "gpt-6-sol", "reasoning_id": "asterion.prime"}
    for index in range(action_count):
        recorder.append(
            "arc.action",
            identities,
            {
                "action": "ACTION1",
                "before_sha256": "sha256:" + f"{index:064x}"[-64:],
                "after_sha256": "sha256:" + f"{index + 1:064x}"[-64:],
                "levels_completed": 0,
            },
        )
    recorder.append("session.terminal", identities, {"outcome": outcome})
    recorder.seal()
    return trace_root / "prime-trace.jsonl"


class TestPrimeP7LiveCommand(unittest.TestCase):
    def test_explicit_resume_selector_is_separate_from_provider_environment(self) -> None:
        from asterion.applications.prime.p7 import operator

        resolver = getattr(operator, "_resolve_resume_run_id", None)
        self.assertTrue(callable(resolver), "explicit resume selector is required")
        key = "ASTERION_PRIME_P7_RESUME_RUN_ID"
        self.assertIsNone(resolver({}))
        self.assertEqual(resolver({key: "p7-live-selected"}), "p7-live-selected")
        for value in ("", "../private", "/private", "p7/run", ".", "..", "secret\npath"):
            with self.subTest(value=value), self.assertRaisesRegex(operator.P7OperatorError, "^P7 resume source is unavailable$"):
                resolver({key: value})

    def test_resume_budget_covers_each_remaining_level(self) -> None:
        from asterion.applications.prime.p7 import operator
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.solutions import VerifiedPrefix

        binder = getattr(operator, "_resume_game", None)
        self.assertTrue(callable(binder), "resume budget binding is required")
        game = P7GameSelection("sp80-589a99af", 0, 6, (6, 10, 51, 73, 93, 204), 6)
        prefix = VerifiedPrefix(game.game_id, 0, 6, 2, (object(),) * 16, "p7-live-selected", "sha256:" + "a" * 64)
        resumed = binder(game, prefix)
        self.assertEqual(resumed.action_cap, 437)
        self.assertEqual(game.action_cap, 1000)
        for invalid in (None, SimpleNamespace(**{**{name: getattr(prefix, name) for name in prefix.__slots__}, "seed": 1}),
                        VerifiedPrefix(game.game_id, 0, 6, 6, (), prefix.source_run_id, prefix.replay_sha256)):
            with self.subTest(prefix=invalid), self.assertRaisesRegex(operator.P7OperatorError, "^P7 resume source is unavailable$"):
                binder(game, invalid)

    def test_explicit_witness_clips_verified_full_source_before_target(self) -> None:
        from asterion.applications.prime.p7 import operator
        from asterion.applications.prime.p7.broker import ArcTransition
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.score import replay_sha256
        from asterion.applications.prime.p7.solutions import VerifiedPrefix

        game = P7GameSelection("sp80-589a99af", 0, 3, (6, 10, 51, 73, 93, 204), 6)
        transitions = tuple(ArcTransition(i, "ACTION1", f"before-{i}", f"after-{i}", i)
                            for i in range(1, 7))
        source = VerifiedPrefix(game.game_id, 0, 6, 6, transitions, "source", "full-digest")
        clipped = operator._resume_prefix_for_target(game, source, witness_only=True)
        self.assertEqual(clipped.transitions, transitions[:2])
        self.assertEqual(clipped.levels_completed, 2)
        self.assertEqual(clipped.source_run_id, source.source_run_id)
        self.assertEqual(clipped.replay_sha256, replay_sha256(transitions[:2], terminal_reason="level-completed"))
        self.assertEqual(operator._resume_game(game, clipped).action_cap, 53)
        self.assertEqual(source.transitions, transitions)
        self.assertEqual(source.replay_sha256, "full-digest")
        with self.assertRaises(operator.P7OperatorError):
            operator._resume_prefix_for_target(game, source, witness_only=False)
        from dataclasses import replace
        for invalid_game, invalid_prefix in (
            (replace(game, target_level=1), source),
            (replace(game, seed=1), source),
            (game, replace(source, transitions=(transitions[-1],))),
        ):
            with self.subTest(game=invalid_game), self.assertRaises(operator.P7OperatorError):
                operator._resume_prefix_for_target(invalid_game, invalid_prefix, witness_only=True)
        self.assertIs(operator._resume_prefix_for_target(game, clipped, witness_only=True), clipped)

    def test_console_logging_resets_terminal_column_on_newlines(self) -> None:
        from asterion.applications.prime.p7 import operator

        class Stream:
            def __init__(self) -> None:
                self.newline = None

            def reconfigure(self, *, newline: str) -> None:
                self.newline = newline

        stdout = Stream()
        stderr = Stream()
        with mock.patch.object(operator.sys, "stdout", stdout), mock.patch.object(operator.sys, "stderr", stderr):
            operator._configure_console_logging()
        self.assertEqual(stdout.newline, "\r\n")
        self.assertEqual(stderr.newline, "\r\n")

    def test_console_logging_quiets_repeated_arc_scorecard_info(self) -> None:
        from asterion.applications.prime.p7.operator import _configure_console_logging

        logger = logging.getLogger("arc_agi.scorecard")
        previous = logger.level
        try:
            logger.setLevel(logging.INFO)
            _configure_console_logging()
            self.assertGreaterEqual(logger.level, logging.WARNING)
        finally:
            logger.setLevel(previous)

    def test_prefix_diagnostics_separate_context_from_applied_replay(self) -> None:
        from asterion.applications.prime.p7.operator import (
            _prefix_action_diagnostics, _prefix_replayed_count,
        )

        prefix = SimpleNamespace(transitions=(object(), object()))
        self.assertEqual(
            _prefix_action_diagnostics(prefix, applied=False),
            {"replayed_prefix_actions": 0, "prior_prefix_actions": 2},
        )
        self.assertEqual(
            _prefix_action_diagnostics(prefix, applied=True),
            {"replayed_prefix_actions": 2, "prior_prefix_actions": 2},
        )
        self.assertEqual(_prefix_replayed_count(prefix, 10, 11), 1)
        self.assertEqual(_prefix_replayed_count(prefix, 10, 12), 2)
        self.assertEqual(_prefix_replayed_count(prefix, 10, 15), 2)

    def test_failure_classification_is_explicit_and_evidence_backed(self) -> None:
        from asterion.applications.prime.p7.operator import classify_failure_cause

        self.assertEqual(
            classify_failure_cause(
                failure=RuntimeError("incomplete"),
                broker_status={"terminal_reason": "human-baseline", "actions_remaining": 0},
                pi_private={"error_events": [], "cancel_requested": False, "process_returncode": 0},
                bridge_method_failures={},
                cleanup_failed=False,
            ),
            {"category": "action_cap", "evidence": {"terminal_reason": "human-baseline", "actions_remaining": 0}},
        )
        self.assertEqual(
            classify_failure_cause(
                failure=asyncio.CancelledError(),
                broker_status={"terminal_reason": "active"},
                pi_private={"error_events": [], "cancel_requested": False, "process_returncode": 143},
                bridge_method_failures={},
                cleanup_failed=False,
            )["category"],
            "external_cancel",
        )
        self.assertEqual(
            classify_failure_cause(
                failure=RuntimeError("failed"),
                broker_status={"terminal_reason": "active"},
                pi_private={"error_events": [{"type": "message_end", "stop_reason": "error"}], "cancel_requested": False, "process_returncode": 0},
                bridge_method_failures={},
                cleanup_failed=False,
            )["category"],
            "model_rpc_error",
        )
        self.assertEqual(
            classify_failure_cause(
                failure=RuntimeError("cap"),
                broker_status={"terminal_reason": "human-baseline", "actions_remaining": 0},
                pi_private={"error_events": [], "cancel_requested": False, "process_returncode": 0},
                bridge_method_failures={
                    "method_failures_total": 3,
                    "method_failures_observe_output_too_large": 2,
                    "method_failures_act_checked_output_too_large": 1,
                },
                cleanup_failed=False,
            )["category"],
            "action_cap",
        )
        self.assertEqual(
            classify_failure_cause(
                failure=RuntimeError("terminal status query"),
                broker_status={"terminal_reason": "human-baseline", "actions_remaining": 0},
                pi_private={"error_events": [], "cancel_requested": False, "process_returncode": 0},
                bridge_method_failures={"method_failures_status": 1},
                cleanup_failed=False,
            )["category"],
            "action_cap",
        )
        self.assertEqual(
            classify_failure_cause(
                failure=None,
                broker_status={"terminal_reason": "level-completed", "actions_remaining": 33},
                pi_private={"error_events": [], "cancel_requested": False, "process_returncode": 0},
                bridge_method_failures={},
                cleanup_failed=False,
            ),
            {"category": "none", "evidence": {}},
        )
        self.assertEqual(
            classify_failure_cause(
                failure=RuntimeError("Pi RPC prompt execution failed"),
                broker_status={"terminal_reason": "active"},
                pi_private=None,
                pi_last_failure="Pi RPC prompt execution failed",
                bridge_method_failures={},
                cleanup_failed=False,
            ),
            {
                "category": "model_rpc_error",
                "evidence": {"last_failure": "Pi RPC prompt execution failed"},
            },
        )

    def test_failure_diagnostic_summary_is_bounded_and_body_free(self) -> None:
        from asterion.services.diagnostics import FailureDiagnostic
        from asterion.applications.prime.p7.operator import _safe_failure_diagnostic

        diagnostic = FailureDiagnostic(
            "diagnostic-id",
            "pi.prompt",
            "RuntimeError",
            "private-subject-digest",
            "private-capability-digest",
            "pi-provider-execution",
        )

        self.assertEqual(
            _safe_failure_diagnostic(diagnostic),
            {
                "diagnostic_id": "diagnostic-id",
                "stage": "pi.prompt",
                "exception_type": "RuntimeError",
                "failure_code": "pi-provider-execution",
            },
        )
        self.assertIsNone(_safe_failure_diagnostic(RuntimeError("private detail")))

    def test_partial_route_hint_does_not_claim_level_completion(self) -> None:
        from asterion.applications.prime.p7.optimizer import PlannerAction
        from asterion.applications.prime.p7.operator import _summarize_partial_route_actions

        hint = _summarize_partial_route_actions((PlannerAction("ACTION1"),), target_level=2)
        self.assertIn("incomplete", hint.lower())
        self.assertNotIn("selected level boundary", hint)
        self.assertNotIn("upper bound", hint)

    def test_partial_optimizer_exports_candidate_for_live_adoption(self) -> None:
        from asterion.applications.prime.p7.optimizer import PlannerAction, RouteCandidate, RouteResult
        from asterion.applications.prime.p7.operator import _optimize_partial_attempt

        prefix_action = SimpleNamespace(action="ACTION1", data=())
        route_actions = tuple(SimpleNamespace(action="ACTION2", data=()) for _ in range(2))
        candidate_action = PlannerAction("ACTION2")
        replay = RouteResult(
            success=False, action_count=1, terminal_state="NOT_FINISHED",
            identity=("cd82-fb555c5d", 0), replay_complete=True,
        )
        candidate = RouteCandidate(
            actions=(candidate_action,), replay=replay, removed_indices=(1,),
            candidates_replayed=1, proofs=(),
        )
        prefix = SimpleNamespace(transitions=(prefix_action,))
        attempt = SimpleNamespace(transitions=(prefix_action, *route_actions))
        with mock.patch(
            "asterion.applications.prime.p7.operator.optimize_arc_route",
            return_value=candidate,
        ):
            _, metadata = _optimize_partial_attempt(
                attempt, prefix=prefix, game=SimpleNamespace(),
                arc_root=Path("/tmp"), target_level=3,
            )
        self.assertEqual(metadata["status"], "partial-optimized")
        self.assertEqual(metadata["candidate_actions"], [{"name": "ACTION2", "data": {}}])

    def test_route_adoption_tracker_records_exact_follow_and_completion(self) -> None:
        from asterion.applications.prime.p7.optimizer import PlannerAction
        from asterion.applications.prime.p7.operator import RouteAdoptionTracker

        tracker = RouteAdoptionTracker()
        tracker.arm((PlannerAction("ACTION1"), PlannerAction("ACTION6", (("x", 2), ("y", 3)))), target_level=1)
        tracker.record((SimpleNamespace(action="ACTION1", data=(), levels_completed=0),))
        tracker.record((SimpleNamespace(action="ACTION6", data=(("x", 2), ("y", 3)), levels_completed=1),))
        self.assertEqual(tracker.summary(), {
            "armed": True,
            "expected_actions": 2,
            "followed_actions": 2,
            "first_divergence": None,
            "reached_target": True,
            "completed": True,
            "target_level": 1,
        })

    def test_route_adoption_tracker_stops_at_first_divergence(self) -> None:
        from asterion.applications.prime.p7.optimizer import PlannerAction
        from asterion.applications.prime.p7.operator import RouteAdoptionTracker

        tracker = RouteAdoptionTracker()
        tracker.arm((PlannerAction("ACTION1"), PlannerAction("ACTION2")), target_level=1)
        tracker.record((SimpleNamespace(action="ACTION3", data=(), levels_completed=0),))
        tracker.record((SimpleNamespace(action="ACTION1", data=(), levels_completed=0),))
        self.assertEqual(tracker.summary()["followed_actions"], 0)
        self.assertEqual(tracker.summary()["first_divergence"], {"index": 0, "expected": "ACTION1", "actual": "ACTION3"})
        self.assertFalse(tracker.summary()["completed"])

    def test_route_adoption_tracker_does_not_call_action_prefix_a_win(self) -> None:
        from asterion.applications.prime.p7.optimizer import PlannerAction
        from asterion.applications.prime.p7.operator import RouteAdoptionTracker

        tracker = RouteAdoptionTracker()
        tracker.arm((PlannerAction("ACTION1"),), target_level=1)
        tracker.record((SimpleNamespace(action="ACTION1", data=(), levels_completed=0),))
        self.assertFalse(tracker.summary()["completed"])
        self.assertFalse(tracker.summary()["reached_target"])

    def test_route_adoption_stops_on_replay_expectation_mismatch(self) -> None:
        from asterion.applications.prime.p7.optimizer import ActionExpectation, PlannerAction
        from asterion.applications.prime.p7.operator import RouteAdoptionTracker

        expectation = ActionExpectation(
            action="ACTION1",
            data=(),
            prior_state_sha256="sha256:" + "1" * 64,
            after_state_sha256="sha256:" + "2" * 64,
            after_frame_sha256="sha256:" + "3" * 64,
            changed_cells=(),
            levels_completed=0,
            state="NOT_FINISHED",
        )
        tracker = RouteAdoptionTracker()
        tracker.arm(
            (PlannerAction("ACTION1"),), target_level=1, expectations=(expectation,)
        )
        tracker.record(
            (SimpleNamespace(action="ACTION1", data=(), after_sha256="sha256:" + "9" * 64, levels_completed=0),)
        )
        self.assertEqual(
            tracker.summary()["first_divergence"],
            {"index": 0, "expected": "ACTION1", "actual": "ACTION1", "reason": "expectation-mismatch"},
        )

    def test_adopted_route_enforces_full_witness_before_next_dispatch(self) -> None:
        from dataclasses import replace
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.optimizer import PlannerAction
        from asterion.applications.prime.p7.transition_model import TransitionModel
        from asterion.applications.prime.p7.world_model import WorldModelStore
        from tests.test_prime_p7_native_broker import _HistoryEngine

        reference = _HistoryEngine()
        source = ArcBroker(engine=reference, world_model=WorldModelStore(reference.game_id, 0, 7))
        source.bind_history("reference")
        source.act(("ACTION1", "ACTION1"))
        expectations = TransitionModel.from_history(source._bound_history(), world=source.world_model()).expectations()
        for change, expected_count in (("after", 1), ("before", 0), ("none", 2)):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                engine = _HistoryEngine()
                broker = ArcBroker(engine=engine)
                broker.bind_history("live")
                recorder = PrimeTraceRecorder(Path(directory))
                client = _P7BrokerClient(broker, recorder)
                modified = expectations
                if change != "none":
                    field = "after_state_sha256" if change == "after" else "prior_state_sha256"
                    modified = (replace(expectations[0], **{field: "sha256:" + "9" * 64}), expectations[1])
                client.arm_route_adoption((PlannerAction("ACTION1"),) * 2, target_level=1, expectations=modified)
                # A weaker caller cell prediction matches; the replay witness
                # must still stop the batch when another part of state differs.
                result = client.act_checked([
                    {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": n}}}
                    for n in (1, 2)
                ])
                self.assertEqual(result["applied_count"], expected_count)
                self.assertEqual(len(engine.calls), expected_count)
                self.assertEqual(result["unexecuted_count"], 2 - expected_count)
                if change != "none":
                    self.assertEqual(result["stop_reason"], "route-expectation-mismatch")
                recorder.close()

    def test_replay_route_exposes_bounded_checked_plan_through_registered_playbook(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.optimizer import PlannerAction
        from asterion.applications.prime.p7.transition_model import TransitionModel
        from asterion.applications.prime.p7.world_model import WorldModelStore
        from tests.test_prime_p7_native_broker import _HistoryEngine

        engine = _HistoryEngine()
        source = ArcBroker(engine=engine, world_model=WorldModelStore(engine.game_id, 0, 7))
        source.bind_history("reference")
        source.act(("ACTION1", "ACTION1"))
        expectations = TransitionModel.from_history(source._bound_history(), world=source.world_model()).expectations()
        with tempfile.TemporaryDirectory() as directory:
            broker = ArcBroker(engine=_HistoryEngine())
            broker.bind_history("live")
            recorder = PrimeTraceRecorder(Path(directory))
            client = _P7BrokerClient(broker, recorder)
            client.arm_route_adoption((PlannerAction("ACTION1"),) * 2, target_level=1, expectations=expectations)
            projection = client.playbook()
            plan = projection["checked_plan"]
            self.assertEqual(plan[0]["expect"]["frame_sha256"], expectations[0].after_frame_sha256)
            self.assertLess(len(json.dumps(projection).encode()), 8192)
            result = client.act_checked(plan[:1])
            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(len(client.playbook()["checked_plan"]), 1)
            recorder.close()

    def test_process_cancellation_signal_starts_clear_and_can_cancel(self) -> None:
        signal = live_module.ProcessCancellation()
        self.assertFalse(signal.cancelled)
        signal.cancel()
        self.assertTrue(signal.cancelled)

    def test_playbook_prior_visuals_survive_level_filter_and_large_route(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.playbook import CheckedFact, CheckedRoute, PlaybookKey, PlaybookSnapshot
        from asterion.applications.prime.p7.transition_model import ActionExpectation
        from tests.test_prime_p7_native_broker import _HistoryEngine

        engine = _HistoryEngine()
        witness = ActionExpectation("ACTION1", (), "sha256:" + "a" * 64,
                                    "sha256:" + "b" * 64, "sha256:" + "c" * 64,
                                    (), 1, "NOT_FINISHED")
        prior = CheckedFact("entities", "visual.level.0.palette",
                            {"candidate_roles": ["floor_or_background"]}, 0, ("a" * 64,))
        book = PlaybookSnapshot(PlaybookKey(engine.game_id, 0, 7),
                               checked_routes=(CheckedRoute(0, (witness,) * 40, "sha256:" + "a" * 64),),
                               visual_hypotheses=(prior,))
        with tempfile.TemporaryDirectory() as directory:
            broker = ArcBroker(engine=engine)
            broker.load_playbook(book)
            recorder = PrimeTraceRecorder(Path(directory))
            client = _P7BrokerClient(broker, recorder)
            for level in (None, 1):
                with self.subTest(level=level):
                    value = client.playbook(level)
                    self.assertEqual(value["prior_visual_hypotheses"][0]["key"], prior.key)
                    self.assertEqual(value["prior_visual_hypotheses"][0]["status"], "hypothesis")
                    self.assertLessEqual(len(json.dumps(value).encode()), 8192)
            recorder.close()

    def test_witness_level_cap_excludes_replayed_prefix(self) -> None:
        from asterion.applications.prime.p7.operator import _bound_witness_level_actions
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection(
            "vc33-5430563c", 0, 2,
            _metadata_baseline_actions=(7, 18),
            _metadata_win_levels=2,
        )
        route_source = SimpleNamespace(
            transitions=(
                SimpleNamespace(levels_completed=0),
                SimpleNamespace(levels_completed=0),
                SimpleNamespace(levels_completed=1),
                *([SimpleNamespace(levels_completed=1)] * 13),
                SimpleNamespace(levels_completed=2),
            )
        )
        current_prefix = SimpleNamespace(
            transitions=(
                SimpleNamespace(levels_completed=0),
                SimpleNamespace(levels_completed=0),
                SimpleNamespace(levels_completed=1),
            )
        )
        bounded = _bound_witness_level_actions(game, current_prefix, route_source=route_source)
        self.assertEqual(bounded.baseline_actions, (7, 14))
        self.assertEqual(bounded.action_cap, 17)

    def test_witness_without_route_source_keeps_official_baseline(self) -> None:
        from asterion.applications.prime.p7.operator import _bound_witness_level_actions
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection(
            "vc33-5430563c", 0, 2,
            _metadata_baseline_actions=(7, 18),
            _metadata_win_levels=2,
        )
        prefix = SimpleNamespace(
            transitions=(
                SimpleNamespace(levels_completed=0),
                SimpleNamespace(levels_completed=0),
                SimpleNamespace(levels_completed=1),
            )
        )

        bounded = _bound_witness_level_actions(game, prefix)

        self.assertEqual(bounded.baseline_actions, (7, 18))
        self.assertEqual(bounded.action_cap, 21)

    def test_subprocess_worker_bootstraps_from_live_client_facade(self) -> None:
        """The local worker must use the operator socket, not module-source mode."""

        class _Client:
            def observe(self):
                return {
                    "available_actions": [6],
                    "frame": [[0]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"levels_completed": 0}

            def mechanics_prior(self):
                return {}

            def act(self, actions):
                return {}

            def history(self, start, limit):
                return []

            def frame_at(self, sequence):
                return [[0]]

            def act_checked(self, plan):
                return {}

            def tried_actions(self, level):
                return []

            def last_outcome_summary(self, level):
                return {}

        async def exercise() -> str:
            with tempfile.TemporaryDirectory() as directory:
                worker = live_module.SubprocessPythonWorker(root=Path(directory))
                signal = SimpleNamespace(cancelled=False)
                await worker.start(
                    p7_client_facade(_Client()), signal=signal
                )
                try:
                    result = await worker.execute_cell(
                        "import p7_client\nprint(p7_client.status())",
                        signal=signal,
                    )
                    return result.output
                finally:
                    await worker.close()

        self.assertIn("levels_completed", asyncio.run(exercise()))

    def test_pi_command_allows_registered_p7_application_tools(self) -> None:
        command = live_module.pi_base_command(
            node=Path("/usr/bin/node"), pi_entry=Path("/tmp/rpc-entry.js")
        )
        tools = command[command.index("--tools") + 1].split(",")
        self.assertEqual(tools, list(live_module.P7_APPLICATION_TOOL_NAMES))
        self.assertEqual(tools, ["ipython", "p7_execute_plan", "p7_workspace"])

    def test_verified_l1_route_hint_is_bounded_and_replayable(self) -> None:
        from asterion.applications.prime.p7.operator import _summarize_verified_route

        prefix = SimpleNamespace(
            levels_completed=1,
            transitions=(
                SimpleNamespace(action="ACTION4", data=(), levels_completed=0),
                SimpleNamespace(
                    action="ACTION6", data=(("x", 45), ("y", 33)), levels_completed=1
                ),
            ),
        )
        hint = _summarize_verified_route(prefix, target_level=1)
        self.assertIn("Replay-verified L1 route hypothesis", hint)
        self.assertIn('"name": "ACTION6"', hint)
        self.assertEqual(_summarize_verified_route(prefix, target_level=2), "")

    def test_verified_route_hint_selects_only_requested_level(self) -> None:
        from asterion.applications.prime.p7.operator import _summarize_verified_route

        prefix = SimpleNamespace(
            levels_completed=2,
            transitions=(
                SimpleNamespace(action="ACTION4", data=(), levels_completed=0),
                SimpleNamespace(action="ACTION3", data=(), levels_completed=1),
                SimpleNamespace(action="ACTION6", data=(("x", 7), ("y", 9)), levels_completed=1),
                SimpleNamespace(action="ACTION4", data=(), levels_completed=2),
            ),
        )
        hint = _summarize_verified_route(prefix, target_level=2)
        self.assertIn("Replay-verified L2 route hypothesis", hint)
        self.assertIn('"name": "ACTION6"', hint)
        self.assertIn('"name": "ACTION4"', hint)
        self.assertNotIn('"name": "ACTION3"', hint)

    def test_multilevel_optimizer_requires_route_source_to_match_live_prefix(self) -> None:
        from asterion.applications.prime.p7.operator import _route_source_matches_prefix

        prefix = SimpleNamespace(
            source_run_id="run-a",
            transitions=(SimpleNamespace(action="ACTION4"),),
        )
        matching = SimpleNamespace(
            source_run_id="run-a",
            transitions=(SimpleNamespace(action="ACTION4"), SimpleNamespace(action="ACTION3")),
        )
        divergent = SimpleNamespace(
            source_run_id="run-b",
            transitions=(SimpleNamespace(action="ACTION9"), SimpleNamespace(action="ACTION3")),
        )
        self.assertTrue(
            _route_source_matches_prefix(matching, prefix, target_level=2)
        )
        self.assertFalse(
            _route_source_matches_prefix(divergent, prefix, target_level=2)
        )

    def test_multilevel_optimizer_replays_same_game_suffix_after_new_prefix(self) -> None:
        from asterion.applications.prime.p7.operator import _route_source_matches_prefix

        prefix = SimpleNamespace(
            game_id="aa11-bb22", seed=0, win_levels=3, levels_completed=1,
            source_run_id="new-run",
            transitions=(SimpleNamespace(action="ACTION4"),),
        )
        older_route = SimpleNamespace(
            game_id="aa11-bb22", seed=0, win_levels=3, levels_completed=2,
            source_run_id="old-run",
            transitions=(SimpleNamespace(action="ACTION9"), SimpleNamespace(action="ACTION3")),
        )
        self.assertTrue(_route_source_matches_prefix(older_route, prefix, target_level=2))

    def test_live_optimizer_replaces_verified_route_only_when_shorter(self) -> None:
        from asterion.applications.prime.p7.operator import _optimize_verified_route
        from asterion.applications.prime.p7.optimizer import ActionExpectation, PlannerAction, RouteCandidate, RouteResult

        expectation = ActionExpectation(
            action="ACTION4",
            data=(),
            prior_state_sha256="sha256:" + "1" * 64,
            after_state_sha256="sha256:" + "2" * 64,
            after_frame_sha256="sha256:" + "3" * 64,
            changed_cells=(),
            levels_completed=1,
            state="NOT_FINISHED",
        )

        prefix = SimpleNamespace(
            levels_completed=1,
            transitions=(
                SimpleNamespace(action="ACTION4", data=(), levels_completed=0),
                SimpleNamespace(action="ACTION3", data=(), levels_completed=1),
            ),
        )
        game = SimpleNamespace(game_id="aa11-bb22", seed=0, target_level=1)
        optimized = RouteCandidate(
            actions=(PlannerAction("ACTION4"),),
            replay=RouteResult(
                True, 1, "NOT_FINISHED", ("aa11-bb22", 0), expectations=(expectation,)
            ),
            expectations=(expectation,),
            removed_indices=(1,),
            candidates_replayed=4,
        )
        with mock.patch(
            "asterion.applications.prime.p7.operator.optimize_arc_route",
            return_value=optimized,
        ) as optimize:
            hint, metadata = _optimize_verified_route(
                prefix, game=game, arc_root=Path("/tmp/arc"), target_level=1
            )
        optimize.assert_called_once()
        self.assertIn('"name": "ACTION4"', hint)
        self.assertNotIn('"name": "ACTION3"', hint)
        self.assertEqual(metadata["status"], "optimized")
        self.assertEqual(metadata["baseline_actions"], 2)
        self.assertEqual(metadata["optimized_actions"], 1)

    def test_route_compression_proof_prompt_is_bounded_and_generic(self) -> None:
        from asterion.applications.prime.p7.operator import _summarize_route_proofs
        from asterion.applications.prime.p7.optimizer import (
            PlannerAction, RouteCompressionProof,
        )

        proof = RouteCompressionProof(
            "delete_span", 1, 2, (PlannerAction("ACTION2"),), (), (1,),
            ("aa11-bb22", 0), 3, 2, "sha256:source", "sha256:candidate",
            "sha256:prefix", "sha256:suffix", "WIN",
        )
        prompt = _summarize_route_proofs((proof,), target_level=1)
        self.assertIn("Route compression evidence", prompt)
        self.assertIn("delete_span", prompt)
        self.assertNotIn("bp35", prompt.lower())
        self.assertLessEqual(len(prompt.encode()), 16384)

    def test_live_optimizer_falls_back_when_offline_replay_fails(self) -> None:
        from asterion.applications.prime.p7.operator import _optimize_verified_route

        prefix = SimpleNamespace(
            levels_completed=1,
            transitions=(
                SimpleNamespace(action="ACTION4", data=(), levels_completed=0),
                SimpleNamespace(action="ACTION3", data=(), levels_completed=1),
            ),
        )
        game = SimpleNamespace(game_id="aa11-bb22", seed=0, target_level=1)
        with mock.patch(
            "asterion.applications.prime.p7.operator.optimize_arc_route",
            side_effect=RuntimeError("offline unavailable"),
        ):
            hint, metadata = _optimize_verified_route(
                prefix, game=game, arc_root=Path("/tmp/arc"), target_level=1
            )
        self.assertIn('"name": "ACTION4"', hint)
        self.assertIn('"name": "ACTION3"', hint)
        self.assertEqual(metadata["status"], "fallback-error")
        self.assertEqual(metadata["optimized_actions"], 2)

    def test_live_optimizer_rejects_candidate_with_wrong_action_count(self) -> None:
        from asterion.applications.prime.p7.operator import _optimize_verified_route
        from asterion.applications.prime.p7.optimizer import PlannerAction, RouteCandidate, RouteResult

        prefix = SimpleNamespace(
            levels_completed=1,
            transitions=(
                SimpleNamespace(action="ACTION4", data=(), levels_completed=0),
                SimpleNamespace(action="ACTION3", data=(), levels_completed=1),
            ),
        )
        game = SimpleNamespace(game_id="aa11-bb22", seed=0, target_level=1)
        malformed = RouteCandidate(
            actions=(PlannerAction("ACTION4"),),
            replay=RouteResult(True, 99, "NOT_FINISHED", ("aa11-bb22", 0)),
            removed_indices=(1,),
            candidates_replayed=4,
        )
        with mock.patch(
            "asterion.applications.prime.p7.operator.optimize_arc_route",
            return_value=malformed,
        ):
            hint, metadata = _optimize_verified_route(
                prefix, game=game, arc_root=Path("/tmp/arc"), target_level=1
            )
        self.assertIn('"name": "ACTION3"', hint)
        self.assertEqual(metadata["status"], "baseline-only")

    def test_live_optimizer_passes_verified_prefix_to_later_level_replay(self) -> None:
        from asterion.applications.prime.p7.operator import _optimize_verified_route
        from asterion.applications.prime.p7.optimizer import PlannerAction, RouteCandidate, RouteResult

        prefix = SimpleNamespace(
            levels_completed=2,
            transitions=(
                SimpleNamespace(action="ACTION4", data=(), levels_completed=0),
                SimpleNamespace(action="ACTION3", data=(), levels_completed=1),
                SimpleNamespace(action="ACTION6", data=(("x", 7), ("y", 9)), levels_completed=1),
                SimpleNamespace(action="ACTION4", data=(), levels_completed=2),
            ),
        )
        game = SimpleNamespace(game_id="aa11-bb22", seed=0, target_level=2)
        optimized = RouteCandidate(
            actions=(PlannerAction("ACTION4"),),
            replay=RouteResult(True, 1, "NOT_FINISHED", ("aa11-bb22", 0)),
            removed_indices=(1,),
            candidates_replayed=4,
        )
        with mock.patch(
            "asterion.applications.prime.p7.operator.optimize_arc_route",
            return_value=optimized,
        ) as optimize:
            _optimize_verified_route(
                prefix, game=game, arc_root=Path("/tmp/arc"), target_level=2
            )
        self.assertEqual(
            optimize.call_args.kwargs["warmup"],
            (PlannerAction("ACTION4"), PlannerAction("ACTION3")),
        )
        self.assertEqual(optimize.call_args.kwargs["time_budget_seconds"], 8.0)

    def test_generic_prompt_uses_feedback_and_has_no_game_route(self) -> None:
        from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT, P7_CONTINUE_PROMPT
        for term in ('p7_research', 'p7_workspace', 'p7_execute_plan', 'WorldMap', 'counterexample_sequence', '未知目标', 'predictions', 'checked_count', 'RESET', 'target_level', 'actions_remaining'):
            self.assertIn(term, P7_SOLVE_PROMPT)
        for term in ('p7_client', 'p7_cognition_update', 'fallback', 'replay-verified', 'bp35'):
            self.assertNotIn(term, P7_SOLVE_PROMPT)
        self.assertIn('失配先修订模型并重算', P7_CONTINUE_PROMPT)

    def test_initial_context_keeps_settled_frame_and_learning_hint(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7, 0]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 2,
                    "learning_hint": {
                        "recommendation": "inspect_candidate_and_probe",
                        "compiled_candidates": [{"key": "candidate"}],
                    },
                }

            def status(self):
                return {
                    "actions_remaining": 500,
                    "primitive_actions": 0,
                    "target_level": 2,
                    "terminal_reason": "active",
                }

        context = _initial_game_context(Client(), include_prior=False)
        self.assertIn('"frame":[[7,0]]', context)
        self.assertIn("inspect_candidate_and_probe", context)
        self.assertIn("compiled_candidates", context)

    def test_initial_context_uses_unified_planning_background(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"actions_remaining": 20, "primitive_actions": 0, "target_level": 1}

            def planning_background(self):
                return {
                    "schema": "asterion.prime.p7-planning-background/v1",
                    "execution_authority": "none",
                    "revision": {"world_model_version": 2},
                    "worldmap": {"version": 2},
                    "semantic_cognition": {"semantic": {"natural_language_context": "bar is movable"}},
                }

        context = _initial_game_context(Client(), include_prior=False)
        self.assertIn("WorldMap planning background", context)
        self.assertIn("asterion.prime.p7-planning-background/v1", context)
        self.assertIn("bar is movable", context)

    def test_initial_context_keeps_background_when_old_16k_budget_would_have_dropped_it(self) -> None:
        from asterion.applications.prime.p7.operator import (
            _P7_INITIAL_CONTEXT_BYTES, _initial_game_context,
        )

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"actions_remaining": 20, "primitive_actions": 0, "target_level": 1}

            def planning_background(self):
                return {
                    "schema": "asterion.prime.p7-planning-background/v1",
                    "execution_authority": "none",
                    "worldmap": {"evidence": "x" * 14800},
                    "semantic_cognition": {
                        "semantic": {
                            "scope": {"level": 0},
                            "confirmed_knowledge": [{
                                "id": "scene", "kind": "game_type",
                                "claim": "这是网格游戏。", "status": "certain",
                            }],
                            "stable_game_description_zh": "稳定游戏认知（规划背景）\n游戏类型：这是网格游戏。",
                        },
                        "cognition_session": {},
                    },
                }

            def cognition(self):
                return {
                    "semantic": {
                        "scope": {"level": 0},
                        "confirmed_knowledge": [{
                            "id": "scene", "kind": "game_type",
                            "claim": "这是网格游戏。", "status": "certain",
                        }],
                    },
                    "cognition_session": {},
                }

        context = _initial_game_context(Client(), include_prior=False)
        self.assertLessEqual(len(context.encode()), _P7_INITIAL_CONTEXT_BYTES)
        self.assertIn("稳定游戏认知（规划背景）", context)
        self.assertIn("WorldMap planning background", context)
        self.assertNotIn("Initial optional projections omitted", context)

    def test_initial_context_keeps_20k_background_and_current_cognition(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"actions_remaining": 20, "primitive_actions": 0, "target_level": 1}

            def planning_background(self):
                return {
                    "schema": "asterion.prime.p7-planning-background/v1",
                    "execution_authority": "none",
                    "worldmap": {"noise": "x" * 20000},
                    "semantic_cognition": {"semantic": {"natural_language_context": "background-marker"}},
                }

            def cognition(self):
                return {"semantic": {"natural_language_context": "fallback-cognition-marker"}}

        context = _initial_game_context(Client(), include_prior=False)
        self.assertIn("background-marker", context)
        self.assertIn("WorldMap planning background", context)
        self.assertIn("fallback-cognition-marker", context)

    def test_initial_context_logs_cognition_refresh(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"actions_remaining": 20, "primitive_actions": 0, "target_level": 1}

            def cognition(self):
                return {"semantic": {"natural_language_context": "startup-cognition-marker"}}

        stderr = io.StringIO()
        with mock.patch.dict('os.environ', {'ASTERION_PRIME_P7_COLOR': 'never'}), contextlib.redirect_stderr(stderr):
            _initial_game_context(Client(), include_prior=False)
        refresh_lines = [
            line for line in stderr.getvalue().splitlines()
            if line.startswith("[p7-cognition] cognition-refresh ")
        ]
        self.assertEqual(len(refresh_lines), 1)
        self.assertIn('"phase":"startup"', refresh_lines[0])
        self.assertIn("startup-cognition-marker", stderr.getvalue())
        self.assertIn("当前游戏认知", stderr.getvalue())
        self.assertNotIn('"natural_language_context"', stderr.getvalue())
        display_lines = [
            line for line in stderr.getvalue().splitlines()
            if line.startswith("[p7-cognition] cognition-display ")
        ]
        self.assertEqual(len(display_lines), 1)
        self.assertIn("phase=startup", display_lines[0])
        self.assertNotIn("startup-cognition-marker", display_lines[0])

    def test_initial_context_marks_cognition_refresh_failure(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"actions_remaining": 20, "primitive_actions": 0, "target_level": 1}

            def cognition(self):
                raise RuntimeError("private cognition failure")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            context = _initial_game_context(Client(), include_prior=False)
        self.assertIn("refresh unavailable", context)
        self.assertIn('"status":"unavailable"', stderr.getvalue())

    def test_initial_context_automatically_queries_confirmed_model_plan(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def __init__(self):
                self.search_calls = 0

            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7, 0]]],
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 1,
                }

            def status(self):
                return {"actions_remaining": 500, "primitive_actions": 0, "target_level": 1}

            def simulator_status(self):
                return {"confirmed_model": True, "status": "verified"}

            def model_search(self):
                self.search_calls += 1
                return {
                    "status": "found",
                    "plan": [{
                        "action": {"name": "ACTION1", "data": {}},
                        "expect": {"frame_sha256": "sha256:" + "a" * 64},
                    }],
                }

        client = Client()
        context = _initial_game_context(client, include_prior=False)
        self.assertEqual(client.search_calls, 1)
        self.assertIn("Automatic verified model plan", context)
        self.assertIn('"status":"found"', context)

    def test_initial_context_keeps_board_and_model_within_64k_budget(self) -> None:
        from asterion.applications.prime.p7.operator import _initial_game_context

        class Client:
            def observe(self):
                return {
                    "available_actions": ["ACTION1"],
                    "frame": [[[7] * 64 for _ in range(64)]],
                    "levels_completed": 1,
                    "state": "NOT_FINISHED",
                    "win_levels": 6,
                    "learning_hint": {"recommendation": "inspect_candidates"},
                }

            def status(self):
                return {"actions_remaining": 50, "primitive_actions": 6, "target_level": 2}

            def world_model(self):
                return {"hypotheses": "x" * 8192}

            def cognition(self):
                return {"experience": "y" * 8192}

        from asterion.applications.prime.p7.operator import _P7_INITIAL_CONTEXT_BYTES

        context = _initial_game_context(Client(), include_prior=False)
        self.assertLessEqual(len(context.encode()), _P7_INITIAL_CONTEXT_BYTES)
        self.assertIn('"frame":[[7,7,7', context)
        self.assertIn("inspect_candidates", context)
        self.assertIn("Same-game world model", context)

    def test_continue_prompt_reestablishes_action_whitelist_after_retry(self) -> None:
        from asterion.applications.prime.p7.prompt import P7_CONTINUE_PROMPT
        self.assertIn('真实 observation/ref', P7_CONTINUE_PROMPT)
        self.assertIn('不重派旧起点或未知结果', P7_CONTINUE_PROMPT)
        self.assertNotIn('p7_client', P7_CONTINUE_PROMPT)

    def test_offline_optimization_is_disabled_without_explicit_integration_mode(self) -> None:
        from asterion.applications.prime.p7.operator import _offline_optimization_enabled

        self.assertFalse(_offline_optimization_enabled({}))
        self.assertFalse(_offline_optimization_enabled({"ASTERION_PRIME_P7_OFFLINE_OPTIMIZATION": "diagnostic"}))
        self.assertTrue(_offline_optimization_enabled({"ASTERION_PRIME_P7_OFFLINE_OPTIMIZATION": "integration"}))

    def test_retry_replan_required_is_returned_without_trace_dispatch(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _SettledNoEffectEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _SettledNoEffectEngine()
            broker = ArcBroker(
                engine=engine,
            )
            client = _P7BrokerClient(broker, recorder)
            # Reach the runtime guard threshold with three successive
            # no-effect actions; the fourth must be rejected.
            for _ in range(3):
                client.act([{"name": "ACTION1", "data": {}}])
            result = client.act([{"name": "ACTION1", "data": {}}])
            self.assertEqual(result["stop_reason"], "REPLAN_REQUIRED")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(engine.calls, ["ACTION1"] * 3)
            self.assertEqual(len([entry for entry in recorder.snapshot() if entry.kind == "arc.action"]), 3)
            recorder.close()

    def test_retry_checked_replan_required_is_structured(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _SettledNoEffectEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(
                engine=_SettledNoEffectEngine(),
            )
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            # Same runtime-guard semantics: three raw no-effect actions,
            # then a checked probe matching the current frame is rejected.
            for _ in range(3):
                client.act([{"name": "ACTION1", "data": {}}])
            result = client.act_checked([
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 7}}},
            ])
            self.assertEqual((result["stop_reason"], result["applied_count"]), ("REPLAN_REQUIRED", 0))
            recorder.close()

    def test_observe_and_checked_action_return_fresh_planning_background(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _Engine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _Engine()
            broker = ArcBroker(engine=engine)
            broker.bind_history("background-refresh")
            client = _P7BrokerClient(broker, recorder)
            before = client.observe()["planning_background"]
            result = client.act_checked([{
                "action": {"name": "ACTION1", "data": {}},
                "expect": {"cell": {"x": 0, "y": 0, "value": 1}},
            }])
            after = result["planning_background"]
            self.assertEqual(after["execution_authority"], "none")
            self.assertNotEqual(after["revision"]["frame_sha256"], before["revision"]["frame_sha256"])
            self.assertEqual(after["revision"]["primitive_actions"], 1)
            recorder.close()

    def test_solve_client_can_extend_cognition_without_exploration_gate(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.semantic_cognition import SemanticCognitionStore
        from tests.test_prime_p7_native_broker import _Engine

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace_root = root / "trace"
            trace_root.mkdir()
            recorder = PrimeTraceRecorder(trace_root)
            engine = _Engine()
            broker = ArcBroker(
                engine=engine,
                semantic_cognition_store=SemanticCognitionStore(
                    root, engine.game_id, engine.seed, engine.win_levels, level=0
                ),
                semantic_cognition_read_only=False,
            )
            broker.bind_history("solve-feedback")
            client = _P7BrokerClient(broker, recorder, cognition_mode=False)
            result = client.cognition_update({
                "op": "propose",
                "proposal": {"claims": [{
                    "id": "solve-feedback-claim",
                    "kind": "control",
                    "subject": "ACTION1",
                    "claim": "ACTION1 may change the scene.",
                    "reason": "It is available.",
                    "falsifier": "The frame remains unchanged.",
                    "next_test": "Apply ACTION1 once.",
                }]},
            })
            self.assertEqual(result["status"], "ok")
            self.assertIn("planning_background", result)
            recorder.close()

    def test_cognition_experiment_mismatch_is_recoverable_after_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.semantic_cognition import SemanticCognitionStore
        from tests.test_prime_p7_native_broker import _Engine

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = _Engine()
            store = SemanticCognitionStore(root, engine.game_id, engine.seed, engine.win_levels, level=0)
            broker = ArcBroker(engine=engine, semantic_cognition_store=store)
            broker.bind_history("cognition-mismatch")
            broker.cognition_update({"op": "propose", "proposal": {"claims": [{
                "id": "control", "kind": "control", "subject": "ACTION1",
                "claim": "ACTION1 changes the scene.", "reason": "It is available.",
                "falsifier": "No scene change.", "next_test": "Apply ACTION1.",
            }]}})
            broker.cognition_update({"op": "select_experiment", "experiment": {
                "claim_ids": ["control"], "question": "Does ACTION1 change the scene?",
                "information_gain": "Tests the control hypothesis.",
                "action": {"name": "ACTION1"}, "expected": {"frame_changed": True},
            }})
            trace_root = root / "trace"
            trace_root.mkdir()
            recorder = PrimeTraceRecorder(trace_root)
            try:
                client = _P7BrokerClient(broker, recorder, cognition_mode=True)
                result = client.act_checked([{
                    "action": {"name": "ACTION2", "data": {}},
                    "expect": {"state": "NOT_FINISHED"},
                }])
            finally:
                recorder.close()
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["reason"], "experiment-mismatch")
            self.assertTrue(result["retryable"])

    def test_checked_mismatch_accounts_only_dispatched_action(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_HistoryEngine())
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            result = client.act_checked([
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 9}}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 2}}},
            ])
            self.assertEqual((result["applied_count"], result["unexecuted_count"]), (1, 1))
            self.assertEqual(len([entry for entry in recorder.snapshot() if entry.kind == "arc.action"]), 1)
            self.assertEqual(client.private_accounting(), {
                "history_queries": 0, "history_records_returned": 0, "frame_queries": 0,
                "checked_plans": 1, "matched_expectations": 0, "mismatches": 1,
                "unexecuted_items": 1, "checked_plan_errors": 0, "uncertain_items": 0,
                "first_sequence": 0, "last_sequence": 1,
            })
            recorder.close()

    def test_checked_engine_error_keeps_prior_match_and_marks_tail_uncertain(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import P7OperatorError, _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_HistoryEngine(raises_on=2))
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            plan = [
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 2}}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 3}}},
            ]
            with self.assertRaises(P7OperatorError):
                client.act_checked(plan)
            self.assertEqual(len([entry for entry in recorder.snapshot() if entry.kind == "arc.action"]), 1)
            accounting = client.private_accounting()
            self.assertEqual(accounting["checked_plans"], 1)
            self.assertEqual(accounting["matched_expectations"], 1)
            self.assertEqual(accounting["checked_plan_errors"], 1)
            self.assertEqual(accounting["uncertain_items"], 1)
            self.assertEqual(accounting["unexecuted_items"], 1)
            self.assertEqual(accounting["last_sequence"], 1)
            recorder.close()

    def test_checked_precheck_rejection_counts_only_unexecuted_items(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import P7OperatorError, _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_HistoryEngine())
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            plan = [
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"levels_completed": 0}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"state": "WIN"}},
            ]
            with self.assertRaises(P7OperatorError):
                client.act_checked(plan)
            self.assertEqual(len(broker.journal), 0)
            accounting = client.private_accounting()
            self.assertEqual(accounting["checked_plans"], 1)
            self.assertEqual(accounting["checked_plan_errors"], 1)
            self.assertEqual(accounting["matched_expectations"], 0)
            self.assertEqual(accounting["uncertain_items"], 0)
            self.assertEqual(accounting["unexecuted_items"], 3)
            recorder.close()

    def test_experiment_uses_selected_runtime_deadline(self) -> None:
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.operator import _private_experiment

        bounded = _private_experiment("verified", DEFAULT_GAME, {"deadline_ms": "3600000"})
        unbounded = _private_experiment("legacy", DEFAULT_GAME, {"deadline_ms": "none"})
        self.assertEqual(bounded["deadline_ms"], 3600000)
        self.assertIsNone(unbounded["deadline_ms"])
        self.assertIsNone(unbounded["stall_seconds"])

    def test_private_summary_preserves_paired_configuration_and_public_receipt_redacts(self) -> None:
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.operator import _public_receipt

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for variant in ("legacy", "verified"):
                private = root / variant
                private.mkdir()
                live_module.write_summary(
                    root, private, run_id=f"p7-20260925-{variant}", receipt={},
                    broker_receipt=None, game=DEFAULT_GAME, replay_verified=False,
                    sealed_trace=False, cleanup_complete=True, comparison_report=None,
                    reason=None, failure=None, diagnostics={},
                    experiment={"prediction_variant": variant, "model": "gpt-6-sol",
                                "game_id": DEFAULT_GAME.game_id, "seed": DEFAULT_GAME.seed,
                                "target_level": DEFAULT_GAME.target_level, "action_cap": DEFAULT_GAME.action_cap,
                                "deadline_ms": 3600000, "stall_seconds": 300},
                    prediction_accounting={"checked_plans": 1, "mismatches": 1},
                )
                rows.append(json.loads((private / "summary.json").read_text()))
            self.assertEqual(rows[0]["experiment"]["prediction_variant"], "legacy")
            self.assertEqual(rows[1]["experiment"]["prediction_variant"], "verified")
            for key in ("model", "game_id", "seed", "target_level", "action_cap", "deadline_ms", "stall_seconds"):
                self.assertEqual(rows[0]["experiment"][key], rows[1]["experiment"][key])
            rendered = json.dumps(_public_receipt("unsuccessful", "p7-public", game=DEFAULT_GAME))
            for secret in ("frame", "hypothesis", str(root), "prediction_variant"):
                self.assertNotIn(secret, rendered)

    def test_generated_module_facade_accepts_helpers_and_rejects_unknown_public_name(self) -> None:
        from asterion.applications.prime.p7.ipython_host import P7ClientError, p7_client_module_facade

        source = live_module.client_module_source("/tmp/test-p7.sock").encode()
        self.assertIsNotNone(p7_client_module_facade(source))
        with self.assertRaises(P7ClientError):
            p7_client_module_facade(source + b"\ndef extra():\n    return 1\n")

    def test_checked_trace_keeps_success_before_later_engine_error(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import P7OperatorError, _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_HistoryEngine(raises_on=2))
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            plan = [
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 1}}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 2}}},
            ]
            with self.assertRaises(P7OperatorError):
                client.act_checked(plan)
            self.assertEqual(len(broker.journal), 1)
            self.assertEqual([entry.kind for entry in recorder.snapshot()], ["arc.action"])
            recorder.close()

    def test_terminal_status_and_observe_are_readable_after_action_cap(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(
                engine=_HistoryEngine(),
                game=P7GameSelection("ls20-9607627b", 0, 1, action_cap_override=1),
            )
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            client.act([{"name": "ACTION1", "data": {}}])
            with self.assertRaises(ArcBrokerError):
                broker.status()
            self.assertEqual(client.status()["terminal_reason"], "human-baseline")
            self.assertEqual(client.observe()["terminal_reason"], "human-baseline")
            recorder.close()

    def test_socket_returns_multiframe_action_result_over_history_page_cap(self) -> None:
        from asterion.applications.prime.p7.ipython_host import p7_client_facade

        class Client:
            def __init__(self) -> None:
                self.actions = 0

            def observe(self) -> dict[str, object]:
                return {}

            def status(self) -> dict[str, object]:
                return {}

            def act(self, actions: object) -> dict[str, object]:
                self.actions += 1
                return {"applied_count": 1, "observation": {"frame": [[[1] * 64 for _ in range(64)] for _ in range(4)]}}

            def history(self, start: int, limit: int) -> list[dict[str, object]]:
                return []

            def frame_at(self, sequence: int) -> list[list[int]]:
                return [[1] * 128 for _ in range(128)]

            def act_checked(self, plan: object) -> dict[str, object]:
                return {}

            def tried_actions(self, level: int | None = None) -> list[dict[str, object]]:
                return []

            def last_outcome_summary(
                self, level: int | None = None
            ) -> dict[str, object]:
                return {"attempts": {}, "no_effect": {}}

        client = Client()
        server = live_module.P7ClientServer(p7_client_facade(client))
        try:
            request = {"protocol": live_module.WORKER_PROTOCOL, "id": 1, "method": "act", "args": [[{"name": "ACTION1", "data": {}}]]}
            response = json.loads(server._dispatch(json.dumps(request).encode()))
            self.assertEqual(client.actions, 1)
            self.assertTrue(response["ok"])
            self.assertEqual(response["value"]["applied_count"], 1)
            self.assertGreater(len(json.dumps(response).encode()), 16384)
            frame_request = {"protocol": live_module.WORKER_PROTOCOL, "id": 2, "method": "frame_at", "args": [0]}
            frame_response = json.loads(server._dispatch(json.dumps(frame_request).encode()))
            self.assertTrue(frame_response["ok"])
            self.assertEqual(len(frame_response["value"]), 128)
        finally:
            server.close()

    def test_socket_rejects_unknown_malformed_and_oversize_responses(self) -> None:
        from asterion.applications.prime.p7.ipython_host import p7_client_facade

        class Client:
            def observe(self) -> dict[str, object]:
                return {}

            def status(self) -> dict[str, object]:
                return {}

            def act(self, actions: object) -> dict[str, object]:
                return {}

            def history(self, start: int, limit: int) -> list[dict[str, object]]:
                if start < 0 or limit < 1:
                    raise ValueError("private history sentinel")
                return [{"data": "x" * 17000}]

            def frame_at(self, sequence: int) -> list[list[int]]:
                return [[sequence]]

            def act_checked(self, plan: object) -> dict[str, object]:
                return {}

            def tried_actions(self, level: int | None = None) -> list[dict[str, object]]:
                return []

            def last_outcome_summary(
                self, level: int | None = None
            ) -> dict[str, object]:
                return {"attempts": {}, "no_effect": {}}

        server = live_module.P7ClientServer(p7_client_facade(Client()))
        try:
            for method, args in (("unknown", []), ("history", [-1, 1]), ("history", [0]), ("history", [0, 1])):
                with self.subTest(method=method, args=args):
                    request = {"protocol": live_module.WORKER_PROTOCOL, "id": 1, "method": method, "args": args}
                    reply = json.loads(server._dispatch(json.dumps(request).encode()))
                    self.assertEqual(reply, {"protocol": live_module.WORKER_PROTOCOL, "id": None, "ok": False})
                    self.assertNotIn("private history sentinel", repr(reply))
        finally:
            server.close()

    def test_worker_exposes_history_frame_and_checked_plan(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        calls: list[tuple[str, tuple[object, ...]]] = []
        replies: dict[str, object] = {
            "history": [{"sequence": 0}], "frame_at": [[1]],
            "act_checked": {"applied_count": 1, "stop_reason": "matched"},
        }
        namespace["_call"] = lambda method, *args: calls.append((method, args)) or replies[method]
        self.assertEqual(namespace["history"](0, 1), [{"sequence": 0}])  # type: ignore[operator]
        self.assertEqual(namespace["frame_at"](0), [[1]])  # type: ignore[operator]
        plan = [{"action": {"name": "ACTION1", "data": {}}, "expect": {"state": "WIN"}}]
        self.assertEqual(namespace["act_checked"](plan), replies["act_checked"])  # type: ignore[operator]
        self.assertEqual(calls, [("history", (0, 1)), ("frame_at", (0,)), ("act_checked", (plan,))])

    def test_socket_exposes_global_experience_tools_without_dispatching_actions(self) -> None:
        class Client:
            def observe(self) -> dict[str, object]:
                return {"state": "NOT_FINISHED"}

            def status(self) -> dict[str, object]:
                return {"terminal_reason": "active"}

            def act(self, actions: object) -> dict[str, object]:
                raise AssertionError("bridge probe must not dispatch actions")

            def history(self, start: int, limit: int) -> list[dict[str, object]]:
                return []

            def frame_at(self, sequence: int) -> list[list[int]]:
                return [[sequence]]

            def act_checked(self, plan: object) -> dict[str, object]:
                raise AssertionError("bridge probe must not dispatch checked actions")

            def tried_actions(self, level: int | None = None) -> list[dict[str, object]]:
                return []

            def last_outcome_summary(self, level: int | None = None) -> dict[str, object]:
                return {"attempts": {}, "no_effect": {}}

            def observation_state(self) -> dict[str, object]:
                return {"frame": [], "entities": [], "relations": [], "events": []}

            def game_mechanics(self) -> dict[str, object]:
                return {"identity": "ls20-9607627b:0:1", "records": []}

            def counterfactual_search(self) -> dict[str, object]:
                return {"branches": [], "dispatch": "never"}

            def planning_background(self) -> dict[str, object]:
                return {"schema": "asterion.prime.p7-planning-background/v1", "execution_authority": "none"}

        server = live_module.P7ClientServer(p7_client_facade(Client()))
        try:
            namespace: dict[str, object] = {}
            exec(live_module.client_module_source(str(server.path)), namespace)
            self.assertEqual(
                namespace["observation_state"](),
                {"frame": [], "entities": [], "relations": [], "events": []},
            )
            self.assertEqual(
                namespace["game_mechanics"](),
                {"identity": "ls20-9607627b:0:1", "records": []},
            )
            self.assertEqual(
                namespace["counterfactual_search"](),
                {"branches": [], "dispatch": "never"},
            )
            self.assertEqual(
                namespace["planning_background"](),
                {"schema": "asterion.prime.p7-planning-background/v1", "execution_authority": "none"},
            )
        finally:
            server.close()

    def test_checked_actions_record_exact_applied_transitions(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_HistoryEngine())
            broker.bind_history("run-1")
            client = _P7BrokerClient(broker, recorder)
            plan = [
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 9}}},
                {"action": {"name": "ACTION1", "data": {}}, "expect": {"cell": {"x": 0, "y": 0, "value": 2}}},
            ]
            result = client.act_checked(plan)
            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(result["stop_reason"], "prediction-mismatch")
            self.assertEqual(len(broker.journal), 1)
            self.assertEqual(len(recorder.snapshot()), 1)
            self.assertEqual(recorder.snapshot()[0].kind, "arc.action")
            self.assertEqual(client.history(0, 2)[-1]["sequence"], 1)
            self.assertEqual(client.frame_at(1), [[1]])
            recorder.close()

    def test_model_history_queries_are_bounded_and_future_pages_are_empty(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_HistoryEngine())
            broker.bind_history("run-history-normalization")
            client = _P7BrokerClient(broker, recorder)
            client.act([{"name": "ACTION1", "data": {}}])
            self.assertLessEqual(len(client.history(0, 80)), 32)
            self.assertEqual(client.history(50, 20), [])
            recorder.close()

    def test_large_animation_is_reduced_to_settled_frame_for_model_response(self) -> None:
        from asterion.applications.prime.p7.operator import _P7BrokerClient

        class _LargeFrameBroker:
            def observe(self):
                return SimpleNamespace(
                    available_actions=("ACTION1",),
                    frame=tuple(
                        tuple(tuple(1 for _ in range(64)) for _ in range(64))
                        for _ in range(40)
                    ),
                    levels_completed=0,
                    state="NOT_FINISHED",
                    win_levels=1,
                )

            def status(self):
                return SimpleNamespace(
                    actions_remaining=500,
                    levels_completed=0,
                    primitive_actions=0,
                    terminal_reason="active",
                )

            game = SimpleNamespace(target_level=1, baseline_actions=(1,), action_cap=500)

            def learning_hint(self):
                return {"recommendation": "ordinary_exploration"}

            def tried_actions(self, level):
                return []

            def last_outcome_summary(self, level):
                return {"attempts": {}, "no_effect": {}}

        client = _P7BrokerClient.__new__(_P7BrokerClient)
        client._broker = _LargeFrameBroker()
        client._recorder = None
        client._identities = {}
        client._variant = "legacy"
        client._counts = {}
        client._route_adoption = SimpleNamespace()
        view = client.observe()
        self.assertTrue(view["frame_truncated"])
        self.assertEqual(len(view["frame"]), 1)
        self.assertEqual(view["frame"][-1][0][0], 1)

    def test_attached_background_stays_within_aggregate_response_budget(self) -> None:
        from asterion.applications.prime.p7.operator import (
            _COGNITION_OUTPUT_BYTES,
            _P7BrokerClient,
            _P7_RESPONSE_BUDGET_BYTES,
            _P7_RESPONSE_HEADROOM_BYTES,
            _json_bytes,
        )

        # Two animation frames are just under the standalone 48 KiB frame
        # limit.  Including the same observation in a 48 KiB background used
        # to push the worker response beyond the TypeScript bridge cap.
        frame = [[[0] * 11_500], [[1] * 11_500]]

        class _BudgetBroker:
            game = SimpleNamespace(target_level=1, baseline_actions=(1,), action_cap=500)

            def observe(self):
                return SimpleNamespace(
                    available_actions=("ACTION1",), frame=frame,
                    levels_completed=0, state="NOT_FINISHED", win_levels=1,
                )

            def status(self):
                return SimpleNamespace(
                    actions_remaining=500, levels_completed=0,
                    primitive_actions=0, terminal_reason="active",
                )

            def learning_hint(self):
                return {"recommendation": "ordinary_exploration"}

            def tried_actions(self, level):
                return []

            def last_outcome_summary(self, level):
                return {"attempts": {}, "no_effect": {}}

            def planning_background(self):
                return {
                    "schema": "asterion.prime.p7-planning-background/v1",
                    "execution_authority": "none",
                    "observation": {"frame": frame, "state": "NOT_FINISHED"},
                    "semantic_cognition": {
                        "semantic": {"claims": {"large": {"claim": "x" * 14_000}}}
                    },
                }

            def cognition_update(self, payload):
                return {
                    "status": "ok",
                    "report": {"claims": {"large": {"claim": "y" * 14_000}}},
                }

        client = _P7BrokerClient.__new__(_P7BrokerClient)
        client._broker = _BudgetBroker()
        client._recorder = None
        client._identities = {}
        client._variant = "legacy"
        client._counts = {}
        client._route_adoption = SimpleNamespace()
        client._cognition_mode = False
        client._cognition_update_sequence = 0

        observation = client.observe()
        cognition = client.cognition_update({"op": "propose"})
        response_limit = _P7_RESPONSE_BUDGET_BYTES - _P7_RESPONSE_HEADROOM_BYTES
        self.assertLessEqual(_json_bytes(observation), response_limit)
        self.assertLessEqual(_json_bytes(cognition), response_limit)
        self.assertEqual(observation["frame"], frame)
        self.assertTrue(observation["planning_background"]["observation"].get("frame_reused"))
        self.assertLessEqual(_json_bytes(cognition["report"]), _COGNITION_OUTPUT_BYTES)

    def test_worker_grid_uses_settled_last_frame_and_preserves_single_grid(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)

        animated = {"frame": [[[1]], [[2]], [[3]]]}
        self.assertEqual(namespace["_grid"](animated), [[3]])  # type: ignore[operator]

        single = {"frame": [[1, 2], [3, 4]]}
        self.assertEqual(namespace["_grid"](single), [[1, 2], [3, 4]])  # type: ignore[operator]

    def test_worker_render_distinguishes_all_arc_colors(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        observation = {"frame": [[list(range(16))]]}

        rendered = namespace["render"](observation, x1=16)  # type: ignore[operator]

        self.assertEqual(rendered, "00 0123456789ABCDEF")

    def test_worker_diff_separates_interior_and_one_cell_border_changes(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        before = {"frame": [[0, 0, 0], [0, 0, 0], [0, 0, 0]]}
        after = {"frame": [[1, 0, 0], [0, 2, 0], [0, 0, 0]]}

        result = namespace["diff"](before, after)  # type: ignore[operator]

        self.assertEqual(result["changed"], 2)
        self.assertEqual(result["border_changed_cells"], 1)
        self.assertEqual(result["interior_changed_cells"], 1)
        self.assertFalse(result["border_only"])

        border_only = namespace["diff"](before, {"frame": [[1, 0, 0], [0, 0, 0], [0, 0, 0]]})  # type: ignore[operator]
        self.assertTrue(border_only["border_only"])
        self.assertEqual(border_only["interior_changed_cells"], 0)

    def test_operator_prompt_explains_settled_frame_axis(self) -> None:
        from asterion.applications.prime.p7 import operator, official_operator
        from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
        for term in ('settled last frame', 'frame[layer][y][x]', 'p7_research.history(0,32)', 'p7_execute_plan', 'cells', 'frame_sha256', 'levels_completed', 'unexecuted_steps'):
            self.assertIn(term, P7_SOLVE_PROMPT)
        self.assertIs(official_operator.P7_SOLVE_PROMPT, P7_SOLVE_PROMPT)
        self.assertFalse(hasattr(operator, '_P7_FRAME_SEMANTICS'))

    def test_saved_level_prefix_reenters_broker_and_rejects_mismatch(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker, ArcTransition
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import (
            P7OperatorError,
            _apply_saved_prefix,
        )
        from tests.test_prime_p7_native_broker import _FullGameEngine

        game = P7GameSelection("ls20-9607627b", 0, 2)
        source = ArcBroker(engine=_FullGameEngine(), game=game)
        source.act(("ACTION1",))
        expected = source.journal
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _FullGameEngine()
            broker = ArcBroker(
                engine=engine,
                game=game,
            )
            broker.bind_history("run-1")
            _apply_saved_prefix(broker, recorder, expected)
            self.assertEqual(broker.journal, expected)
            history = broker.history(0, 32)
            self.assertEqual(len(history), len(expected) + 1)
            self.assertEqual(history[-1]["before_state_sha256"], expected[-1].before_sha256)
            self.assertEqual(history[-1]["after_state_sha256"], expected[-1].after_sha256)
            self.assertIn("after_frame_sha256", history[-1])
            self.assertEqual(broker.frame_at(len(expected)), [list(row) for row in broker.observe().frame[-1]])
            self.assertEqual(broker.status().levels_completed, 1)
            self.assertEqual(engine.calls, ["ACTION1"])
            recorder.close()
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _FullGameEngine()
            broker = ArcBroker(engine=engine, game=game)
            broker.bind_history("run-1")
            forged = ArcTransition(1, "ACTION1", "sha256:" + "0" * 64, expected[0].after_sha256, 1)
            with self.assertRaisesRegex(P7OperatorError, "saved prefix"):
                _apply_saved_prefix(broker, recorder, (forged,))
            self.assertEqual(engine.calls, [])
            recorder.close()
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _FullGameEngine()
            broker = ArcBroker(engine=engine, game=game)
            with self.assertRaisesRegex(P7OperatorError, "saved prefix"):
                _apply_saved_prefix(broker, recorder, expected)
            self.assertEqual(engine.calls, [])
            recorder.close()

    def test_saved_prefix_records_current_run_model_identity(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _apply_saved_prefix
        from asterion.applications.prime.p7.private_trace import (
            P7PrivateTraceReceipt, trace_identities_for,
        )
        from tests.test_prime_p7_native_broker import _FullGameEngine

        game = P7GameSelection("ls20-9607627b", 0, 2)
        source = ArcBroker(engine=_FullGameEngine(), game=game)
        source.act(("ACTION1",))
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_FullGameEngine(), game=game)
            broker.bind_history("run-model-switch")
            identities = trace_identities_for("gpt-6.1-sol")
            evidence = P7PrivateTraceReceipt(broker, recorder, identities)
            try:
                _apply_saved_prefix(broker, recorder, source.journal, identities=identities)
                self.assertEqual(recorder.snapshot()[0].identities, identities)
                self.assertTrue(evidence.runtime_ready())
            finally:
                recorder.close()

    def test_history_variant_defaults_verified_and_accepts_explicit_local_research(self) -> None:
        from asterion.applications.prime.p7.operator import (
            P7OperatorError, P7_HISTORY_VARIANT_ENV, _resolve_history_variant,
        )
        from asterion.applications.prime.p7.game import P7GameSelection

        game = P7GameSelection("ls20-9607627b", 0, 2)
        self.assertEqual(_resolve_history_variant({}, game), "verified")
        self.assertEqual(
            _resolve_history_variant({P7_HISTORY_VARIANT_ENV: "legacy", "ASTERION_PRIME_P7_RUN_MODE": "solve"}, game),
            "legacy",
        )
        for value in ("Legacy", "", "other"):
            with self.subTest(value=value), self.assertRaises(P7OperatorError):
                _resolve_history_variant({P7_HISTORY_VARIANT_ENV: value}, game)
        self.assertEqual(
            _resolve_history_variant({P7_HISTORY_VARIANT_ENV: "legacy", "ASTERION_PRIME_P7_RUN_MODE": "sweep"}, game),
            "legacy",
        )

    def test_strategy_defaults_to_replay_and_rejects_unknown_values(self) -> None:
        from asterion.applications.prime.p7.operator import (
            P7_STRATEGY_ENV, P7OperatorError, _resolve_strategy,
        )

        self.assertEqual(_resolve_strategy({}), "replay")
        self.assertEqual(_resolve_strategy({P7_STRATEGY_ENV: "replay"}), "replay")
        self.assertEqual(_resolve_strategy({P7_STRATEGY_ENV: "explore"}), "explore")
        for value in ("Replay", "", "sweep", "1"):
            with self.subTest(value=value), self.assertRaises(P7OperatorError):
                _resolve_strategy({P7_STRATEGY_ENV: value})

    def test_explore_prompt_is_explicit_and_replay_prompt_is_conservative(self) -> None:
        from asterion.applications.prime.p7.operator import _prompt_for_strategy
        replay = _prompt_for_strategy('replay')
        explore = _prompt_for_strategy('explore')
        self.assertEqual(replay, explore)
        self.assertIn('WorldMap', replay)
        self.assertNotIn('replay-verified', replay)
        with self.assertRaises(Exception):
            _prompt_for_strategy('unknown')

    def test_strategy_does_not_replace_legacy_history_prompt(self) -> None:
        from asterion.applications.prime.p7.operator import _prompt_for_variant
        from asterion.applications.prime.p7.prompt import P7_LEGACY_SOLVE_PROMPT

        self.assertEqual(_prompt_for_variant("legacy"), P7_LEGACY_SOLVE_PROMPT)

    def test_legacy_prompt_selection_preserves_old_batch_guidance(self) -> None:
        from asterion.applications.prime.p7.operator import _prompt_for_variant
        from asterion.applications.prime.p7.prompt import P7_LEGACY_SOLVE_PROMPT, P7_SOLVE_PROMPT

        self.assertEqual(_prompt_for_variant("verified"), P7_SOLVE_PROMPT)
        self.assertEqual(_prompt_for_variant("legacy"), P7_LEGACY_SOLVE_PROMPT)
        self.assertIn("Use a longer batch, never more than 20 actions", P7_LEGACY_SOLVE_PROMPT)
        self.assertNotIn("p7_client.history", P7_LEGACY_SOLVE_PROMPT)
        self.assertNotIn("act_checked", P7_LEGACY_SOLVE_PROMPT)
        self.assertNotEqual(P7_LEGACY_SOLVE_PROMPT, P7_SOLVE_PROMPT)
        with self.assertRaises(Exception):
            _prompt_for_variant("arbitrary")

    def test_verified_act_rejects_batch_before_dispatch_and_legacy_preserves_it(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import P7OperatorError, _P7BrokerClient
        from tests.test_prime_p7_native_broker import _HistoryEngine

        game = P7GameSelection("ls20-9607627b", 0, 2)
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _HistoryEngine()
            broker = ArcBroker(engine=engine, game=game)
            checked = _P7BrokerClient(broker, recorder)
            actions = [{"name": "ACTION1", "data": {}}] * 2
            with self.assertRaises(P7OperatorError):
                checked.act(actions)
            self.assertEqual(engine.calls, [])
            legacy = _P7BrokerClient(broker, recorder, variant="legacy")
            self.assertEqual(legacy.act(actions)["applied_count"], 2)
            self.assertEqual(engine.calls, ["ACTION1", "ACTION1"])
            recorder.close()

    def test_game_over_act_returns_terminal_view_without_closed_reads(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _Engine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            broker = ArcBroker(engine=_Engine(game_over_after=1))
            client = _P7BrokerClient(broker, recorder)
            batch = client.act([{"name": "ACTION1", "data": {}}])
            observation = cast(Mapping[str, object], batch["observation"])
            terminal = cast(Mapping[str, object], batch["terminal"])

            self.assertEqual(batch["applied_count"], 1)
            self.assertEqual(observation["state"], "GAME_OVER")
            self.assertEqual(terminal["primitive_actions"], 1)
            self.assertEqual(terminal["terminal_reason"], "reset-required")
            self.assertEqual(len(broker.journal), 1)
            recorder.close()

    def test_worker_act_reports_recoverable_game_over_without_followup_calls(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        calls: list[str] = []

        def fake_call(method: str, *args: object) -> object:
            calls.append(method)
            if method != "act":
                raise AssertionError("terminal state must come from act response")
            return {
                "level_advanced": False,
                "observation": {
                    "available_actions": ["ACTION1"],
                    "frame": [[[1]]],
                    "levels_completed": 0,
                    "state": "GAME_OVER",
                    "win_levels": 7,
                },
                "terminal": {
                    "actions_remaining": 499,
                    "levels_completed": 0,
                    "primitive_actions": 1,
                    "target_level": 1,
                    "terminal_reason": "reset-required",
                },
            }

        namespace["_call"] = fake_call
        view = namespace["act"]("ACTION1")  # type: ignore[operator]
        self.assertEqual(view["terminal"], "RESET_REQUIRED")
        self.assertEqual(view["actions_taken"], 1)
        self.assertEqual(namespace["summary"](view)["status"]["terminal_reason"], "reset-required")  # type: ignore[operator]
        self.assertEqual(calls, ["act"])

    def test_worker_reset_returns_active_view_and_cap_remains_final(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        requests: list[object] = []

        def fake_call(method: str, actions: object) -> object:
            self.assertEqual(method, "act")
            requests.append(actions)
            remaining = 0 if len(requests) == 2 else 498
            return {
                "level_advanced": False,
                "observation": {
                    "available_actions": ["ACTION1"], "frame": [[[1]]],
                    "levels_completed": 1, "state": "NOT_FINISHED", "win_levels": 7,
                },
                "terminal": {
                    "actions_remaining": remaining, "levels_completed": 1,
                    "primitive_actions": 500 - remaining, "target_level": 2,
                    "terminal_reason": "action-cap" if remaining == 0 else "active",
                },
            }

        namespace["_call"] = fake_call
        reset = namespace["act"]("RESET")  # type: ignore[operator]
        self.assertEqual(reset["terminal"], "ACTIVE")
        capped = namespace["act"]("ACTION1")  # type: ignore[operator]
        self.assertEqual(capped["terminal"], "ACTION_CAP")
        self.assertEqual(requests[0], [{"name": "RESET", "data": {}}])

    def test_worker_does_not_offer_reset_for_unrecoverable_game_over(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        namespace["_call"] = lambda method, *args: {
            "level_advanced": True,
            "observation": {
                "available_actions": ["ACTION1"], "frame": [[[1]]],
                "levels_completed": 1, "state": "GAME_OVER", "win_levels": 7,
            },
            "terminal": {
                "actions_remaining": 498, "levels_completed": 1,
                "primitive_actions": 2, "target_level": 2,
                "terminal_reason": "game-over",
            },
        }
        view = namespace["act"]("ACTION1")  # type: ignore[operator]
        self.assertEqual(view["terminal"], "GAME_OVER")

    def test_client_passes_click_coordinates_to_broker_and_journal(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.operator import P7OperatorError, _P7BrokerClient

        class Engine:
            game_id = "ls20-9607627b"
            seed = 0

            def __init__(self) -> None:
                self.clicks: list[tuple[str, dict[str, int]]] = []

            def observe(self) -> dict[str, object]:
                return {
                    "available_actions": ["ACTION6"], "frame": [[[1]]],
                    "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 7,
                }

            def step(self, action: str, data: dict[str, int]) -> dict[str, object]:
                self.clicks.append((action, data))
                return self.observe()

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = Engine()
            broker = ArcBroker(engine=engine)
            client = _P7BrokerClient(broker, recorder)
            client.act([{"name": "ACTION6", "data": {"x": 12, "y": 34}}])
            self.assertEqual(engine.clicks, [("ACTION6", {"x": 12, "y": 34})])
            self.assertEqual(broker.journal[0].data, (("x", 12), ("y", 34)))
            for data in ({"x": True, "y": 1}, {"x": 64, "y": 1}, {"x": 1}, {"x": 1, "y": 2, "z": 3}):
                with self.subTest(data=data), self.assertRaises(P7OperatorError):
                    client.act([{"name": "ACTION6", "data": data}])
            self.assertEqual(len(broker.journal), 1)
            recorder.close()

    def test_client_resets_failed_second_level_on_same_engine(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from tests.test_prime_p7_native_broker import _ResetEngine

        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            engine = _ResetEngine()
            broker = ArcBroker(
                engine=engine,
                game=P7GameSelection("ls20-9607627b", 0, 2),
            )
            client = _P7BrokerClient(broker, recorder)
            client.act([{"name": "ACTION1", "data": {}}])
            failed = client.act([{"name": "ACTION1", "data": {}}])
            self.assertEqual(failed["terminal"]["terminal_reason"], "reset-required")
            recovered = client.act([{"name": "RESET", "data": {}}])
            self.assertEqual(recovered["observation"]["levels_completed"], 1)
            self.assertEqual(recovered["observation"]["state"], "NOT_FINISHED")
            self.assertEqual(recovered["terminal"]["terminal_reason"], "active")
            self.assertEqual(engine.calls[-1], ("RESET", {}))
            self.assertEqual(len(broker.journal), 3)
            recorder.close()

    def test_arcade_adapter_forwards_click_data(self) -> None:
        from asterion.applications.prime.p7.live import ArcadeEngine

        class Environment:
            def __init__(self) -> None:
                self.calls: list[tuple[object, object]] = []

            def step(self, action: object, data: object) -> SimpleNamespace:
                self.calls.append((action, data))
                return SimpleNamespace(
                    available_actions=[6], frame=[[[1]]],
                    levels_completed=0, state="NOT_FINISHED", win_levels=7,
                )

        engine = object.__new__(ArcadeEngine)
        environment = Environment()
        engine._actions = {"ACTION6": "sdk-click", "RESET": "sdk-reset"}
        engine._environment = environment
        engine.step("ACTION6", {"x": 12, "y": 34})
        self.assertEqual(environment.calls, [("sdk-click", {"x": 12, "y": 34})])

    def test_competition_mode_rejected_before_arcade_constructor(self) -> None:
        import os
        import sys
        from types import ModuleType

        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.live import ArcadeEngine, P7LiveSolveError

        arc = ModuleType("arc_agi")
        arc.OperationMode = SimpleNamespace(OFFLINE="offline")  # type: ignore[attr-defined]
        constructed: list[bool] = []
        arc.Arcade = lambda **kwargs: constructed.append(True)  # type: ignore[attr-defined]
        engine = ModuleType("arcengine")
        engine.GameAction = SimpleNamespace(**{f"ACTION{i}": i for i in range(1, 8)}, RESET=0)  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            sys.modules, {"arc_agi": arc, "arcengine": engine}
        ), mock.patch.dict(os.environ, {"OPERATION_MODE": "competition"}):
            with self.assertRaises(P7LiveSolveError):
                ArcadeEngine(arc_root=Path(temporary), recordings_dir=Path(temporary) / "recordings", game=DEFAULT_GAME)
        self.assertEqual(constructed, [])

    def test_solve_level_requires_explicit_selection_and_ignores_dotenv_default(self) -> None:
        import os
        from asterion.applications.prime.p7.operator import _select_game_for_mode

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "environment_files" / "zx42" / "abc123"
            catalog.mkdir(parents=True)
            (catalog / "zx42.py").write_text("# source not imported\n")
            (catalog / "metadata.json").write_text(json.dumps({"game_id": "zx42-abc123", "baseline_actions": [10, 20, 30], "win_levels": 3}))
            (root / ".env").write_text("ASTERION_PRIME_P7_TARGET_LEVEL=1\n")
            with mock.patch.dict(os.environ, {"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_P7_GAME_ID": "zx42"}, clear=True):
                resolved = live_module.load_operator_environment(root)
            whole = _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "solve"}, resolved, root)
            selected = _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "solve", "ASTERION_PRIME_P7_TARGET_LEVEL": "2"}, resolved, root)
            self.assertEqual(whole.target_level, 3)
            self.assertEqual(selected.target_level, 2)
            witness = _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "witness", "ASTERION_PRIME_P7_TARGET_LEVEL": "1"}, resolved, root)
            self.assertEqual(witness.target_level, 1)
            self.assertEqual(witness.action_cap_override, 10)
            witness_two = _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "witness", "ASTERION_PRIME_P7_TARGET_LEVEL": "2"}, resolved, root)
            self.assertEqual(witness_two.action_cap_override, 30)
            sweep = _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "sweep", "ASTERION_PRIME_P7_TARGET_LEVEL": "2"}, resolved, root)
            self.assertEqual(sweep.target_level, 2)
            with self.assertRaises(Exception):
                _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "sweep"}, resolved, root)

    def test_dotenv_model_selection_overrides_stale_terminal_model(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ,
            {
                "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"),
                "ASTERION_PRIME_PROVIDER": "openai-codex",
                "ASTERION_PRIME_MODEL": "gpt-6-sol",
            },
            clear=True,
        ):
            root = Path(temporary)
            (root / ".env").write_text(
                "ASTERION_PRIME_PROVIDER=openai-codex\nASTERION_PRIME_MODEL=gpt-6.1-sol\n",
                encoding="utf-8",
            )
            resolved = live_module.load_operator_environment(root)
        self.assertEqual(resolved["ASTERION_PRIME_MODEL"], "gpt-6.1-sol")

    def test_sweep_budget_counts_saved_prefix_and_current_human_baseline(self) -> None:
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import P7OperatorError, _sweep_game, resolve_p7_runtime
        from asterion.applications.prime.p7.solutions import VerifiedPrefix

        game = P7GameSelection("ls20-9607627b", 0, 2)
        prefix = VerifiedPrefix(game.game_id, 0, 7, 1, (object(),) * 20, "prior", "sha256:test")
        bounded = _sweep_game(game, prefix)
        self.assertEqual(bounded.action_cap, 143)
        self.assertEqual(bounded.target_level, 2)
        self.assertEqual(resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")}, bounded).max_actions, 143)
        with self.assertRaises(P7OperatorError):
            _sweep_game(game, None)

    def test_preflight_reports_safe_level_routing_error_without_secret(self) -> None:
        from asterion.applications.prime.p7.operator import P7OperatorError, main

        for error, expected in (
            (P7OperatorError("LEVEL is only available with the P7 level-witness command"), True),
            (P7OperatorError("private-token sentinel-secret"), False),
        ):
            with self.subTest(expected=expected), mock.patch(
                "asterion.applications.prime.p7.operator._preflight", side_effect=error
            ), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([]), 2)
            public = json.loads(output.getvalue())
            self.assertEqual(public["status"], "preflight-rejected")
            self.assertEqual("LEVEL is only available" in public.get("reason", ""), expected)
            self.assertNotIn("sentinel-secret", output.getvalue())

    def test_worker_act_reports_intermediate_level_then_target(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        responses = [
            {
                "level_advanced": True,
                "observation": {
                    "available_actions": ["ACTION1"], "frame": [[[1]]],
                    "levels_completed": 1, "state": "NOT_FINISHED", "win_levels": 7,
                },
                "terminal": {
                    "actions_remaining": 498, "levels_completed": 1,
                    "primitive_actions": 2, "target_level": 2,
                    "terminal_reason": "active",
                },
            },
            {
                "level_advanced": True,
                "observation": {
                    "available_actions": ["ACTION1"], "frame": [[[2]]],
                    "levels_completed": 2, "state": "NOT_FINISHED", "win_levels": 7,
                },
                "terminal": {
                    "actions_remaining": 496, "levels_completed": 2,
                    "primitive_actions": 4, "target_level": 2,
                    "terminal_reason": "level-completed",
                },
            },
        ]
        namespace["_call"] = lambda method, *args: responses.pop(0)

        first = namespace["act"]("ACTION1")  # type: ignore[operator]
        self.assertEqual(first["terminal"], "LEVEL_ADVANCED")
        self.assertEqual(first["status"]["target_level"], 2)
        second = namespace["act"]("ACTION1")  # type: ignore[operator]
        self.assertEqual(second["terminal"], "LEVEL_SOLVED")
        self.assertEqual(responses, [])

    def test_worker_reports_game_solved_only_for_sdk_win(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        namespace["_call"] = lambda method, *args: {
            "level_advanced": True,
            "observation": {
                "available_actions": [], "frame": [[[1]]],
                "levels_completed": 7, "state": "WIN", "win_levels": 7,
            },
            "terminal": {
                "actions_remaining": 100, "levels_completed": 7,
                "primitive_actions": 900, "target_level": 7,
                "terminal_reason": "game-won",
            },
        }
        self.assertEqual(namespace["act"]("ACTION1")["terminal"], "GAME_SOLVED")  # type: ignore[operator]

    def test_full_game_public_classification_requires_game_won_and_uses_game_cap(self) -> None:
        from dataclasses import replace
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.live import P7LiveExecution, P7LiveSolveError
        from asterion.applications.prime.p7.operator import classify_live_result, resolve_p7_runtime

        game = P7GameSelection("ls20-9607627b", 0, 7)
        self.assertGreater(game.action_cap, 500)
        self.assertEqual(resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")}, game).max_actions, game.action_cap)
        result = P7LiveExecution(
            run_id="test-run", completed_level_count=7, primitive_action_count=700,
            replay_verified=True, sealed_trace=True, cleanup_complete=True,
            trace_root=Path("/tmp"), receipt={"receipt_sha256": "0" * 64},
            comparison_report=None, game=game, broker_replay_sha256="1" * 64,
            terminal_reason="game-won",
        )
        public = classify_live_result(result)
        self.assertEqual(public["status"], "PASS")
        self.assertEqual(public["completion_scope"], "full-game")
        self.assertEqual(public["win_levels"], 7)
        with self.assertRaisesRegex(P7LiveSolveError, "WIN"):
            classify_live_result(replace(result, terminal_reason="game-incomplete"))

    def test_unsuccessful_public_receipt_preserves_safe_game_over_evidence(self) -> None:
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.operator import P7LiveAttemptFailure, main

        error = P7LiveAttemptFailure(
            primitive_actions=50,
            levels_completed=0,
            target_level=1,
            terminal_reason="game-over",
            replay_verified=True,
            sealed_trace=False,
            cleanup_complete=True,
        )
        output = io.StringIO()
        with (
            mock.patch("asterion.applications.prime.p7.operator._preflight", return_value=SimpleNamespace(game=DEFAULT_GAME)),
            mock.patch("asterion.applications.prime.p7.operator.live.safe_run_id", return_value="p7-live-test"),
            mock.patch("asterion.applications.prime.p7.operator.run_live", new_callable=mock.AsyncMock, side_effect=error),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = main([])

        receipt = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(receipt["primitive_action_count"], 50)
        self.assertEqual(receipt["completed_level_count"], 0)
        self.assertEqual(receipt["terminal_reason"], "game-over")
        self.assertTrue(receipt["cleanup_complete"])
        self.assertTrue(receipt["replay_verified"])
        self.assertEqual(receipt["status"], "unsuccessful")
        self.assertNotIn("receipt_sha256", receipt)

    def test_runtime_failure_without_attempt_receipt_still_exits_nonzero(self) -> None:
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.live import P7LiveSolveError
        from asterion.applications.prime.p7.operator import main

        stderr = io.StringIO()
        with (
            mock.patch("asterion.applications.prime.p7.operator._preflight", return_value=SimpleNamespace(game=DEFAULT_GAME)),
            mock.patch("asterion.applications.prime.p7.operator.live.safe_run_id", return_value="p7-live-error"),
            mock.patch("asterion.applications.prime.p7.operator.run_live", new_callable=mock.AsyncMock, side_effect=P7LiveSolveError("broker unavailable")),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            status = main([])

        self.assertEqual(status, 1)
        self.assertIn("[asterion-prime-p7] error", stderr.getvalue())

    def test_run_live_seals_replayed_first_level_failure_without_reusable_prefix(self) -> None:
        for outcome in ("game-over", "interrupted", "untrusted-cancel"):
            with self.subTest(outcome=outcome):
                self._assert_replayed_first_level_failure(outcome)

    def _assert_replayed_first_level_failure(self, outcome: str) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.operator import (
            P7Invocation,
            P7LiveAttemptFailure,
            _P7BrokerClient,
            run_live,
        )
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from tests.test_prime_p7_native_broker import _Engine

        class Engine(_Engine):
            def __init__(self, **kwargs: object) -> None:
                super().__init__(game_over_after=1 if outcome == "game-over" else None)

            def close(self) -> None:
                pass

        class Worker:
            closed = False

        async def composed(*args: object, **kwargs: object) -> None:
            assert client is not None
            client.act([{"name": "ACTION1", "data": {}}])
            if outcome == "game-over":
                raise RuntimeError("private model detail")
            raise asyncio.CancelledError("supervisor interrupt")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = Worker()
            broker = None
            client = None

            def build_resources(**kwargs: object) -> SimpleNamespace:
                nonlocal broker, client
                broker = ArcBroker(engine=kwargs["engine"])
                evidence = P7PrivateTraceReceipt(
                    broker, PrimeTraceRecorder(kwargs["private_trace_root"])
                )
                client = _P7BrokerClient(broker, evidence.runtime_recorder, variant="legacy")

                async def close_resources() -> None:
                    evidence.close()
                    worker.closed = True

                return SimpleNamespace(
                    runtime_options={},
                    host_services={
                        "prime.arc-broker": broker,
                        "prime.private-trace": evidence,
                    },
                    close=close_resources,
                )
            assembly = SimpleNamespace(
                runtime_binding=SimpleNamespace(factory=lambda context: object()),
                path=root,
                plan=object(),
            )
            application = SimpleNamespace(assemblies=[assembly], implementations=())
            invocation = P7Invocation(
                operator_root=root,
                arc_root=root,
                game=DEFAULT_GAME,
                environment={"ASTERION_PRIME_P7_HISTORY_VARIANT": "legacy"},
                pi_base_command=(),
                extension_path=root,
            )
            with (
                mock.patch("asterion.applications.prime.p7.operator.live.SubprocessPythonWorker", return_value=worker),
                mock.patch("asterion.applications.prime.p7.operator.live.ArcadeEngine", side_effect=Engine),
                mock.patch(
                    "asterion.applications.prime.p7.operator.build_p7_operator_resources",
                    side_effect=build_resources,
                ),
                mock.patch("asterion.applications.prime.p7.operator._resolve_p7_application", return_value=application),
                mock.patch("asterion.applications.prime.p7.operator.run_composed_application", new_callable=mock.AsyncMock, side_effect=composed),
                mock.patch("asterion.applications.prime.p7.operator.live.worker_cell_count", return_value=0),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                cancellation = live_module.ProcessCancellation()
                if outcome == "interrupted":
                    cancellation.cancel()
                with self.assertRaises(P7LiveAttemptFailure) as caught:
                    asyncio.run(run_live(invocation, "p7-live-test", cancellation_signal=cancellation))

            failure = caught.exception
            if outcome == "untrusted-cancel":
                self.assertFalse(failure.sealed_trace)
                self.assertFalse(failure.replay_verified)
                return
            self.assertEqual(failure.primitive_actions, 1)
            self.assertEqual(failure.terminal_reason, outcome)
            self.assertTrue(failure.replay_verified)
            self.assertTrue(failure.cleanup_complete)
            self.assertTrue(failure.sealed_trace)
            run = root / ".asterion-private/prime-p7-live/p7-live-test"
            entries = live_module.read_trace_entries(run / "trace")
            self.assertEqual(
                [entry.kind for entry in entries][-2:],
                ["arc.run.failed", "trace.sealed"],
            )
            self.assertFalse(
                any(
                    entry.kind in {"arc.run.completed", "arc.run.partial"}
                    for entry in entries
                )
            )
            failure_entry = entries[-2]
            self.assertEqual(failure_entry.payload["primitive_actions"], 1)
            self.assertEqual(failure_entry.payload["levels_completed"], 0)
            self.assertEqual(failure_entry.payload["terminal_reason"], outcome)
            summary = json.loads((run / "summary.json").read_text())
            self.assertEqual(summary["broker"]["primitive_actions"], 1)
            self.assertEqual(summary["broker"]["terminal_reason"], outcome)
            self.assertEqual(summary["receipt"], {})
            self.assertIsNone(summary.get("completed_prefix"))
            self.assertTrue(summary["replay_verified"])
            self.assertTrue(summary["sealed_trace"])

    def test_failed_later_level_seals_only_verified_completed_prefix(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.live import read_trace_entries
        from asterion.applications.prime.p7.operator import _P7BrokerClient, _seal_verified_partial_run
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from tests.test_prime_p7_solutions import _Engine

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace_root = root / "trace"
            trace_root.mkdir()
            game = P7GameSelection("ls20-9607627b", 0, 7)
            broker = ArcBroker(engine=_Engine(), game=game)
            recorder = PrimeTraceRecorder(trace_root)
            evidence = P7PrivateTraceReceipt(broker, recorder)
            client = _P7BrokerClient(broker, recorder, variant="legacy")
            client.act([{"name": "ACTION1", "data": {}}] * 2)
            client.act([{"name": "ACTION1", "data": {}}])
            self.assertEqual((broker.journal[-1].levels_completed, len(broker.journal)), (1, 3))
            with mock.patch("asterion.applications.prime.p7.operator.live.ArcadeEngine", side_effect=lambda **_: _Engine()):
                prefix = _seal_verified_partial_run(broker, evidence, root, root)
            assert prefix is not None
            self.assertEqual((prefix["levels_completed"], prefix["primitive_actions"]), (1, 2))
            entries = read_trace_entries(trace_root)
            self.assertEqual([entry.kind for entry in entries][-2:], ["arc.run.partial", "trace.sealed"])
            self.assertEqual(len([entry for entry in entries if entry.kind == "arc.action"]), 3)

            incomplete_trace_root = root / "incomplete-trace"
            incomplete_trace_root.mkdir()
            other_broker = ArcBroker(engine=_Engine(), game=game)
            other_recorder = PrimeTraceRecorder(incomplete_trace_root)
            other_client = _P7BrokerClient(other_broker, other_recorder, variant="legacy")
            other_client.act([{"name": "ACTION1", "data": {}}] * 2)
            other_broker.act(("ACTION1",))
            with mock.patch("asterion.applications.prime.p7.operator.live.ArcadeEngine", side_effect=lambda **_: _Engine()):
                self.assertIsNone(_seal_verified_partial_run(
                    other_broker, P7PrivateTraceReceipt(other_broker, other_recorder), root, root
                ))
            self.assertFalse((incomplete_trace_root / "prime-trace.seal.json").exists())
            other_recorder.close()

    def test_run_live_retains_completed_level_when_model_fails_later(self) -> None:
        """Legacy model failure still retains only the replay-verified prefix."""
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import P7Invocation, P7LiveAttemptFailure, _P7BrokerClient, run_live
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from tests.test_prime_p7_solutions import _Engine

        class Engine(_Engine):
            def close(self) -> None:
                pass

        class Worker:
            closed = False

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = P7GameSelection("ls20-9607627b", 0, 7)
            worker = Worker()
            client = None

            def build_resources(**kwargs: object) -> SimpleNamespace:
                nonlocal client
                broker = ArcBroker(engine=kwargs["engine"], game=game)
                evidence = P7PrivateTraceReceipt(broker, PrimeTraceRecorder(kwargs["private_trace_root"]))
                client = _P7BrokerClient(broker, evidence.runtime_recorder, variant="legacy")

                async def close_resources() -> None:
                    evidence.close()
                    worker.closed = True

                return SimpleNamespace(
                    runtime_options={},
                    host_services={"prime.arc-broker": broker, "prime.private-trace": evidence},
                    close=close_resources,
                )

            async def composed(*args: object, **kwargs: object) -> None:
                assert client is not None
                client.act([{"name": "ACTION1", "data": {}}] * 2)
                client.act([{"name": "ACTION1", "data": {}}])
                raise RuntimeError("private model detail")

            assembly = SimpleNamespace(
                runtime_binding=SimpleNamespace(factory=lambda context: object()),
                path=root,
                plan=object(),
            )
            application = SimpleNamespace(assemblies=[assembly], implementations=())
            invocation = P7Invocation(root, {"ASTERION_PRIME_P7_HISTORY_VARIANT": "legacy"}, root, (), root, game)
            from asterion.applications.prime.p7.replay import replay_arc_run
            certification_witness = object()
            certified = []
            replayed = []

            def verify_save(arc_root, selected_game, transitions, receipt, observations, engine_factory):
                actual = replay_arc_run(transitions, receipt, engine_factory, game=selected_game, observations=observations)
                replayed.append(actual)
                return actual, certification_witness

            def publish_save(arc_root, source, witness, *, expected_model_id):
                finalized = json.loads((source / "summary.json").read_text())
                self.assertTrue(finalized["cleanup_complete"])
                self.assertTrue(finalized["sealed_trace"])
                self.assertTrue(worker.closed)
                self.assertIs(witness, certification_witness)
                self.assertEqual(finalized["completed_prefix"]["primitive_actions"], 2)
                certified.append(source)

            with (
                mock.patch.dict("sys.modules", {"asterion.applications.prime.p7.solution_certificates": SimpleNamespace(
                    verify_for_save=verify_save, publish_verified_save=publish_save,
                )}),
                mock.patch("asterion.applications.prime.p7.operator.live.SubprocessPythonWorker", return_value=worker),
                mock.patch("asterion.applications.prime.p7.operator.live.ArcadeEngine", side_effect=lambda **_: Engine()),
                mock.patch("asterion.applications.prime.p7.operator.build_p7_operator_resources", side_effect=build_resources),
                mock.patch("asterion.applications.prime.p7.operator._resolve_p7_application", return_value=application),
                mock.patch("asterion.applications.prime.p7.operator.run_composed_application", new_callable=mock.AsyncMock, side_effect=composed),
                mock.patch("asterion.applications.prime.p7.operator.live.worker_cell_count", return_value=0),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(P7LiveAttemptFailure) as caught:
                    asyncio.run(run_live(invocation, "p7-live-partial"))

            failure = caught.exception
            self.assertTrue(failure.replay_verified)
            self.assertTrue(failure.sealed_trace)
            self.assertTrue(failure.cleanup_complete)
            run = root / ".asterion-private/prime-p7-live/p7-live-partial"
            self.assertEqual(certified, [run.resolve()])
            self.assertEqual(len(replayed), 1)
            summary = json.loads((run / "summary.json").read_text())
            self.assertEqual(summary["completed_prefix"]["levels_completed"], 1)
            self.assertEqual(summary["completed_prefix"]["primitive_actions"], 2)
            self.assertEqual(summary["receipt"], {})
            arc_game = root / "environment_files/ls20/9607627b"
            arc_game.mkdir(parents=True)
            (arc_game / "ls20.py").write_text("# fixture\n")
            (arc_game / "metadata.json").write_text(json.dumps({
                "game_id": game.game_id,
                "baseline_actions": [22, 123, 73, 84, 96, 192, 186],
                "win_levels": 7,
            }))
            recording = run / "recordings/session/ls20.jsonl"
            recording.parent.mkdir(parents=True)
            recording.write_text("\n".join(json.dumps({"data": {
                "game_id": game.game_id,
                "win_levels": 7,
                "action_input": {"id": action, "data": {}},
            }}) for action in ("RESET", "ACTION1", "ACTION1", "ACTION1")) + "\n")
            from asterion.applications.prime.p7.solutions import load_best_prefix
            with mock.patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=lambda *_: Engine()):
                prefix = load_best_prefix(root, run.parent, game.game_id, 0)
            assert prefix is not None
            self.assertEqual((prefix.levels_completed, len(prefix.transitions)), (1, 2))

    def test_run_live_cancellation_seals_completed_prefix(self) -> None:
        """Legacy supervisor cancellation still seals completed-level evidence."""
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import (
            P7Invocation, P7LiveAttemptFailure, _P7BrokerClient, run_live,
        )
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from tests.test_prime_p7_solutions import _Engine

        class Worker:
            closed = False

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = P7GameSelection("ls20-9607627b", 0, 7)
            worker = Worker()
            client = None

            def build_resources(**kwargs: object) -> SimpleNamespace:
                nonlocal client
                broker = ArcBroker(engine=kwargs["engine"], game=game)
                evidence = P7PrivateTraceReceipt(
                    broker, PrimeTraceRecorder(kwargs["private_trace_root"])
                )
                client = _P7BrokerClient(broker, evidence.runtime_recorder, variant="legacy")

                async def close_resources() -> None:
                    evidence.close()
                    worker.closed = True

                return SimpleNamespace(
                    runtime_options={},
                    host_services={
                        "prime.arc-broker": broker,
                        "prime.private-trace": evidence,
                    },
                    close=close_resources,
                )

            async def composed(*args: object, **kwargs: object) -> None:
                assert client is not None
                client.act([{"name": "ACTION1", "data": {}}] * 2)
                client.act([{"name": "ACTION1", "data": {}}])
                raise asyncio.CancelledError("supervisor timeout")

            assembly = SimpleNamespace(
                runtime_binding=SimpleNamespace(factory=lambda context: object()),
                path=root,
                plan=object(),
            )
            application = SimpleNamespace(assemblies=[assembly], implementations=())
            invocation = P7Invocation(root, {"ASTERION_PRIME_P7_HISTORY_VARIANT": "legacy"}, root, (), root, game)
            with (
                mock.patch(
                    "asterion.applications.prime.p7.operator.live.SubprocessPythonWorker",
                    return_value=worker,
                ),
                mock.patch(
                    "asterion.applications.prime.p7.operator.live.ArcadeEngine",
                    side_effect=lambda **_: _Engine(),
                ),
                mock.patch(
                    "asterion.applications.prime.p7.operator.build_p7_operator_resources",
                    side_effect=build_resources,
                ),
                mock.patch(
                    "asterion.applications.prime.p7.operator._resolve_p7_application",
                    return_value=application,
                ),
                mock.patch(
                    "asterion.applications.prime.p7.operator.run_composed_application",
                    new_callable=mock.AsyncMock,
                    side_effect=composed,
                ),
                mock.patch(
                    "asterion.applications.prime.p7.operator.live.worker_cell_count",
                    return_value=0,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(P7LiveAttemptFailure) as caught:
                    asyncio.run(run_live(invocation, "p7-live-cancelled"))

            failure = caught.exception
            self.assertTrue(failure.sealed_trace)
            run = root / ".asterion-private/prime-p7-live/p7-live-cancelled"
            summary = json.loads((run / "summary.json").read_text())
            self.assertTrue(summary["sealed_trace"])
            self.assertEqual(summary["completed_prefix"]["levels_completed"], 1)
            self.assertEqual(
                summary["diagnostics"]["failure_classification"]["category"],
                "external_cancel",
            )

    def test_safe_run_id_keeps_utc_timestamp_and_separates_same_second_retries(
        self,
    ) -> None:
        completed = mock.Mock(stdout="20260924115415\n")
        with mock.patch.object(live_module.subprocess, "run", return_value=completed):
            first = live_module.safe_run_id()
            second = live_module.safe_run_id()

        self.assertRegex(first, r"^p7-live-20260924115415-[0-9a-f]{24}$")
        self.assertRegex(second, r"^p7-live-20260924115415-[0-9a-f]{24}$")
        self.assertNotEqual(first, second)

    def test_compare_cli_labels_operator_stopped_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asterion = _sealed_trace(root, outcome="level-completed", action_count=2)
            baseline = _sealed_trace(root, outcome="operator-stopped", action_count=3)
            output = root / "report.json"

            status = compare_main(
                [
                    "--asterion",
                    str(asterion),
                    "--baseline",
                    str(baseline),
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(status, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["baseline_label"], "operator-stopped")
            self.assertEqual(report["schema"], "asterion.prime.p7-live-comparison/v1")
            self.assertEqual(report["comparison"]["right"]["outcome"], "operator-stopped")
            self.assertNotIn("private", json.dumps(report, sort_keys=True))

    def test_compare_parser_requires_only_three_paths(self) -> None:
        parser = build_compare_parser()

        self.assertEqual(
            sorted(action.dest for action in parser._actions),
            ["asterion", "baseline", "help", "output"],
        )


if __name__ == "__main__":
    unittest.main()
