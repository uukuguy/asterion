from __future__ import annotations

import json
import contextlib
import io
import asyncio
from collections.abc import Mapping
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7 import live as live_module
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
    def test_pi_command_allows_registered_p7_application_tools(self) -> None:
        command = live_module.pi_base_command(
            node=Path("/usr/bin/node"), pi_entry=Path("/tmp/rpc-entry.js")
        )
        tools = command[command.index("--tools") + 1].split(",")
        self.assertEqual(tools, list(live_module.P7_APPLICATION_TOOL_NAMES))
        self.assertIn("p7_observe", tools)
        self.assertIn("p7_act_checked", tools)

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
        from asterion.applications.prime.p7 import operator
        from asterion.applications.prime.p7 import official_operator
        from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT

        self.assertIn("settled", P7_SOLVE_PROMPT.lower())
        self.assertIn("last", P7_SOLVE_PROMPT.lower())
        self.assertIn("a-f represent color values 10-15", P7_SOLVE_PROMPT.lower())
        self.assertIn("p7_client.history(0, 32)", P7_SOLVE_PROMPT)
        self.assertIn("p7_client.frame_at(sequence)", P7_SOLVE_PROMPT)
        self.assertIn("p7_client.act_checked(plan)", P7_SOLVE_PROMPT)
        self.assertIn("remaining plan was not executed", " ".join(P7_SOLVE_PROMPT.split()))
        normalized = " ".join(P7_SOLVE_PROMPT.split())
        self.assertIn("levels_completed is 0", normalized)
        self.assertIn("primitive_actions", normalized)
        self.assertIn("retry with a smaller limit", normalized)
        self.assertIn("last returned sequence plus 1", normalized)
        self.assertIn('"action":{"name":"ACTION1","data":{}}', normalized)
        self.assertIn('"expect":{"cell":{"x":2,"y":3,"value":7}}', normalized)
        for key in ('frame_sha256', 'levels_completed', 'state'):
            self.assertIn(key, normalized)
        self.assertIs(official_operator.P7_SOLVE_PROMPT, P7_SOLVE_PROMPT)
        self.assertFalse(hasattr(operator, "_P7_FRAME_SEMANTICS"))

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
            sweep = _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "sweep", "ASTERION_PRIME_P7_TARGET_LEVEL": "2"}, resolved, root)
            self.assertEqual(sweep.target_level, 2)
            with self.assertRaises(Exception):
                _select_game_for_mode({"ASTERION_PRIME_P7_RUN_MODE": "sweep"}, resolved, root)

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
        self.assertEqual(status, 1)
        self.assertEqual(receipt["primitive_action_count"], 50)
        self.assertEqual(receipt["completed_level_count"], 0)
        self.assertEqual(receipt["terminal_reason"], "game-over")
        self.assertTrue(receipt["cleanup_complete"])
        self.assertTrue(receipt["replay_verified"])
        self.assertEqual(receipt["status"], "unsuccessful")
        self.assertNotIn("receipt_sha256", receipt)

    def test_run_live_seals_replayed_first_level_failure_without_reusable_prefix(self) -> None:
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
                super().__init__(game_over_after=1)

            def close(self) -> None:
                pass

        class Worker:
            closed = False

        async def composed(*args: object, **kwargs: object) -> None:
            assert client is not None
            client.act([{"name": "ACTION1", "data": {}}])
            raise RuntimeError("private model detail")

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
                client = _P7BrokerClient(broker, evidence.runtime_recorder)

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
                environment={},
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
                with self.assertRaises(P7LiveAttemptFailure) as caught:
                    asyncio.run(run_live(invocation, "p7-live-test"))

            failure = caught.exception
            self.assertEqual(failure.primitive_actions, 1)
            self.assertEqual(failure.terminal_reason, "game-over")
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
            self.assertEqual(failure_entry.payload["terminal_reason"], "game-over")
            summary = json.loads((run / "summary.json").read_text())
            self.assertEqual(summary["broker"]["primitive_actions"], 1)
            self.assertEqual(summary["broker"]["terminal_reason"], "game-over")
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
            invocation = P7Invocation(root, {}, root, (), root, game)
            with (
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
