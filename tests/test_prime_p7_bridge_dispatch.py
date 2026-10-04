import json
import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
from asterion.applications.prime.p7.cognition_narrative import render_cognition_narrative_zh
from asterion.applications.prime.p7.operator import (
    _IpythonBridgeServer,
    _P7BrokerClient,
    _compact_cognition_session,
    _compact_planning_background,
    _bounded_semantic_report,
    _p7_action_plan_names,
    P7OperatorError,
)


class _Facade:
    def observe(self):
        return {"levels_completed": 0}

    def status(self):
        return {"primitive_actions": 0}

    def mechanics_prior(self):
        return {"available": False}

    def tried_actions(self, level=None):
        return [{"level": level}]

    def last_outcome_summary(self, level=None):
        return {"attempts": {}, "no_effect": {}}

    def world_model(self):
        return {"version": 1}

    def planning_background(self):
        return {"schema": "asterion.prime.p7-planning-background/v1", "execution_authority": "none"}

    def cognition(self):
        return {"input_kind": "keyboard", "type_profile": {"authority": "prior-only"}}

    def cognition_update(self, payload):
        return {"received": payload}

    def playbook(self, level=None):
        return {"level": level}

    def retrodiction_status(self):
        return {"status": "observed"}

    def record_hypothesis(self, layer, key, value):
        return {"layer": layer, "key": key, "value": value}

    def history(self, start, limit):
        return [{"sequence": start, "limit": limit}]

    def frame_at(self, sequence):
        return [[sequence]]

    def act_checked(self, plan):
        return {"applied_count": len(plan)}


class TestP7BridgeDispatch(unittest.TestCase):
    def setUp(self):
        self.bridge = object.__new__(_IpythonBridgeServer)
        self.bridge._client = _Facade()
        self.bridge._method_calls = {}
        self.bridge._method_failures = {}

    def test_no_argument_tools_do_not_receive_empty_object(self):
        for method in ("observe", "status", "mechanics_prior", "world_model", "planning_background", "cognition", "retrodiction_status"):
            with self.subTest(method=method):
                response = self.bridge._dispatch_method_call("request", method, {})
                self.assertEqual(response["status"], "ok")
            self.assertEqual(response["type"], "method_result")

    def test_action_plan_summary_keeps_only_public_action_names(self):
        plan = [
            {"action": {"name": "ACTION4", "data": {"x": 12}}},
            {"action": {"name": "ACTION1", "data": {}}},
        ]
        self.assertEqual(_p7_action_plan_names({"plan": plan}), "ACTION4、ACTION1")
        self.assertEqual(_p7_action_plan_names({"plan": []}), "空计划")

    def test_action_dispatch_logs_model_plan_and_result(self):
        stream = io.StringIO()
        plan = [{"action": {"name": "ACTION4", "data": {}}}]
        with redirect_stderr(stream):
            response = self.bridge._dispatch_method_call("request", "act_checked", {"plan": plan})
        self.assertEqual(response["status"], "ok")
        self.assertIn("[p7] P7动作计划：ACTION4。", stream.getvalue())
        self.assertIn("[p7] P7动作结果：已执行 1 步。", stream.getvalue())

        stream.seek(0)
        stream.truncate(0)
        with redirect_stderr(stream):
            response = self.bridge._dispatch_method_call("request", "act_checked", {"plan": []})
        self.assertEqual(response["status"], "ok")
        self.assertNotIn("P7动作计划", stream.getvalue())
        self.assertIn("[p7] P7动作结果：已执行 0 步。", stream.getvalue())

    def test_planning_background_compaction_honors_small_cap(self):
        value = {
            "schema": "asterion.prime.p7-planning-background/v1",
            "execution_authority": "none",
            "identity": {"game_id": "game", "seed": 0, "win_levels": 1, "level": 0},
            "revision": {"frame_sha256": "sha256:" + "a" * 64},
            "background_id": "sha256:" + "b" * 64,
            "worldmap": {"confirmed": {"entities": {"x": {"value": "x" * 100000}}}},
            "semantic_cognition": {"semantic": {"natural_language_context": "c" * 100000}},
            "observation": {"events": ["e" * 100000]},
        }
        compact = _compact_planning_background(value, max_bytes=1024)
        self.assertLessEqual(len(json.dumps(compact, separators=(",", ":")).encode()), 1024)
        self.assertEqual(compact["execution_authority"], "none")

    def test_model_tools_receive_typed_parameters(self):
        for method, params in (("playbook", 0), ("record_hypothesis", {"layer": "mechanics", "key": "x", "value": {}})):
            with self.subTest(method=method):
                response = self.bridge._dispatch_method_call("request", method, params)
                self.assertEqual(response["status"], "ok")

    def test_structured_tools_receive_typed_parameters(self):
        cases = {
            "tried_actions": 0,
            "last_outcome_summary": None,
            "history": {"start": 0, "limit": 1},
            "frame_at": {"sequence": 0},
            "act_checked": {"plan": []},
        }
        for method, params in cases.items():
            with self.subTest(method=method):
                response = self.bridge._dispatch_method_call("request", method, params)
                self.assertEqual(response["status"], "ok")
                self.assertIn("output", response)
                json.loads(response["output"])

    def test_malformed_or_unknown_method_fails_closed(self):
        for method, params in (("status", {"unexpected": 1}), ("unknown", {})):
            with self.subTest(method=method):
                response = self.bridge._dispatch_method_call("request", method, params)
                self.assertEqual(response["status"], "error")

    def test_cognition_update_receives_direct_payload(self):
        response = self.bridge._dispatch_method_call("request", "cognition_update", {"op": "snapshot"})
        self.assertEqual(response["status"], "ok")
        self.assertEqual(json.loads(response["output"])["received"], {"op": "snapshot"})
        malformed = self.bridge._dispatch_method_call("request", "cognition_update", {"payload": {"op": "snapshot"}})
        self.assertEqual(malformed["status"], "error")

    def test_cognition_operation_aliases_dispatch_to_canonical_session_methods(self):
        class Session:
            def __init__(self):
                self.calls = []
            def propose(self, value):
                self.calls.append(("propose", value))
                return 1
            def select_experiment(self, value):
                self.calls.append(("select_experiment", value))
                return {"state": "EXPERIMENT_SELECTED"}
            def analyze(self, value):
                self.calls.append(("analyze", value))
                return {"state": "ANALYZED"}
            def snapshot(self):
                return {"report": {}, "session": {}}

        broker = object.__new__(ArcBroker)
        broker._cognition_session = Session()
        broker._semantic_cognition_read_only = False
        for submitted, payload, canonical, field in (
            ("proposal", {"claims": []}, "propose", "proposal"),
            ("experiment", {"claim_ids": ["c"], "action": {"name": "ACTION1"}}, "select_experiment", "experiment"),
            ("select", {"claim_ids": ["c"]}, "select_experiment", "experiment"),
            ("record_analysis", {"results": []}, "analyze", "analysis"),
            ("analyze_experiment", {"results": []}, "analyze", "analysis"),
        ):
            with self.subTest(submitted=submitted):
                broker.cognition_update({"op": submitted, field: payload})
                self.assertEqual(broker._cognition_session.calls[-1][0], canonical)

    def test_rejected_cognition_payload_is_recoverable(self):
        class RejectingBroker:
            def cognition_update(self, payload):
                raise ArcBrokerError("unavailable")

        client = object.__new__(_P7BrokerClient)
        client._broker = RejectingBroker()
        result = client.cognition_update({"op": "propose"})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "invalid-cognition-operation")
        self.assertEqual(result["execution_authority"], "none")

    def test_first_probe_hint_reads_nested_session_action_count(self):
        class Broker:
            journal = ()

            def cognition_projection(self):
                return {"cognition_session": {
                    "state": "OBSERVE",
                    "session": {"state": "OBSERVE", "episode_actions": 0},
                }}

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        client._cognition_mode = True
        hint = client._first_probe_hint()
        self.assertEqual(hint["reason"], "cognition-first-probe-required")

    def test_ready_cognition_update_keeps_broker_open_for_followup_solve(self):
        class Session:
            def ready_for_solve(self):
                return {"state": "READY", "execution_authority": "none"}

        broker = object.__new__(ArcBroker)
        broker._cognition_session = Session()
        broker._semantic_cognition_read_only = False
        broker._terminal_reason = "active"
        result = broker.cognition_update({"op": "ready"})
        self.assertEqual(result["state"], "READY")
        self.assertEqual(broker._terminal_reason, "active")

    def test_cognition_update_logs_compact_correlated_request_and_outcome(self):
        payload = {
            "op": "select_experiment",
            "experiment": {"expected": {"frame_changed": True, "state": "NOT_FINISHED"}, "question": "为什么？"},
            "proposal": {"claim": "semantic detail " * 2000},
            "analysis": {"results": [{"explanation": "exact explanation"}]},
            "reason": "operator reason",
        }
        encoded_before = json.dumps(payload, sort_keys=True)

        class Broker:
            def cognition_update(self, submitted):
                return {"status": "rejected", "reason": "experiment expected predicate is unavailable", "retryable": True}

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        stream = io.StringIO()
        with redirect_stderr(stream):
            for _ in range(2):
                result = client.cognition_update(payload)
        lines = stream.getvalue().splitlines()
        requests = [json.loads(line.removeprefix("[p7-cognition] update-request ")) for line in lines if line.startswith("[p7-cognition] update-request ")]
        outcomes = [json.loads(line.removeprefix("[p7-cognition] update-call ")) for line in lines if line.startswith("[p7-cognition] update-call ")]
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual([item["request_sequence"] for item in requests], [1, 2])
        self.assertEqual([item["request_sequence"] for item in outcomes], [1, 2])
        self.assertEqual(requests[0]["payload_keys"], sorted(payload))
        self.assertEqual(requests[0]["analysis_count"], 1)
        self.assertNotIn("payload", requests[0])
        self.assertNotIn("semantic detail", stream.getvalue())
        self.assertLess(len(stream.getvalue().encode("utf-8")), 4096)
        self.assertEqual(outcomes[0]["reason"], result["reason"])
        self.assertEqual(json.dumps(payload, sort_keys=True), encoded_before)

    def test_cognition_update_logs_every_exit_without_changing_results(self):
        cases = (
            ({"op": "snapshot"}, {"state": "OBSERVE"}, None, "ok"),
            ({"op": "propose"}, None, ArcBrokerError("cognition-persistence-unavailable"), "rejected"),
            ({"op": "propose"}, None, ValueError("exact validation failure"), "error"),
            ({"op": 3}, None, None, "rejected"),
        )
        for payload, response, failure, status in cases:
            with self.subTest(payload=payload, status=status):
                class Broker:
                    def cognition_update(self, submitted):
                        if failure is not None:
                            raise failure
                        return response

                client = object.__new__(_P7BrokerClient)
                client._broker = Broker()
                stream = io.StringIO()
                with redirect_stderr(stream):
                    if status == "error":
                        with self.assertRaises(P7OperatorError):
                            client.cognition_update(payload)
                    else:
                        client.cognition_update(payload)
                lines = stream.getvalue().splitlines()
                self.assertEqual(len(lines), 2)
                self.assertTrue(lines[0].startswith("[p7-cognition] update-request "))
                outcome = json.loads(lines[-1].removeprefix("[p7-cognition] update-call "))
                self.assertEqual(outcome["request_sequence"], 1)
                self.assertEqual(outcome["status"], "ok" if status == "ok" else status)
                if failure is not None:
                    self.assertEqual(outcome["error_type"], type(failure).__name__)
                    self.assertEqual(outcome["detail"], str(failure))

    def test_cognition_update_prints_post_operation_cognition(self):
        class Broker:
            def cognition_update(self, submitted):
                return {
                    "status": "ok",
                    "next": "select_experiment",
                    "report": {
                        "schema": "schema",
                        "scope": {"game_id": "synthetic"},
                        "claims": {
                            "control": [{
                                "id": "move-right", "kind": "control", "subject": "ACTION2",
                                "claim": "ACTION2 使玩家向右移动。", "status": "certain", "confidence": 0.8,
                                "evidence_count": 1, "support_count": 1, "counterexample_count": 0,
                                "next_test": "Repeat ACTION2.",
                            }],
                        },
                        "evidence_counts": {"total": 1},
                        "execution_authority": "none",
                    },
                    "session": {
                        "session_id": "visible", "episode": 1, "episode_actions": 1,
                        "resets": 0, "state": "ANALYZED",
                        "validation": {
                            "needed": True, "possible": False,
                            "reason": "validation-budget-exhausted",
                            "actionable_claim_ids": ["goal"],
                        },
                    },
                }

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        stream = io.StringIO()
        with redirect_stderr(stream):
            client.cognition_update({"op": "analyze"})
        states = [
            json.loads(line.removeprefix("[p7-cognition] cognition-state "))
            for line in stream.getvalue().splitlines()
            if line.startswith("[p7-cognition] cognition-state ")
        ]
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["state"], "ANALYZED")
        self.assertEqual(states[0]["claims"], 1)
        self.assertIn("当前游戏认知", stream.getvalue())
        self.assertIn("ACTION2 使玩家向右移动", stream.getvalue())
        self.assertIn("P7分析：提交 0 条结果。", stream.getvalue())
        self.assertNotIn('"report"', stream.getvalue())
        displays = [
            line for line in stream.getvalue().splitlines()
            if line.startswith("[p7-cognition] cognition-display ")
        ]
        self.assertEqual(len(displays), 1)
        self.assertIn("phase=update:analyze", displays[0])
        self.assertIn("state=ANALYZED", displays[0])
        self.assertIn("claims=1", displays[0])

    def test_cognition_console_logs_use_narrative_instead_of_ledger_json(self):
        from asterion.applications.prime.p7.operator import _log_cognition_refresh

        projection = {
            "semantic": {
                "natural_language_context": "这是一个网格移动谜题。",
                "scope": {"level": 0},
                "claims": {
                    "control": [{
                        "id": "move-right",
                        "kind": "control",
                        "claim": "ACTION4 使横带右移四格。",
                        "status": "certain",
                        "next_test": "检查下一次右移。",
                    }],
                },
            },
            "cognition_session": {
                "session": {"state": "READY", "episode": 1, "episode_actions": 2},
            },
        }
        stream = io.StringIO()
        with redirect_stderr(stream):
            _log_cognition_refresh(projection, phase="startup")
        output = stream.getvalue()
        self.assertIn("当前游戏认知", output)
        self.assertIn("已确认", output)
        self.assertIn("ACTION4 使横带右移四格", output)
        self.assertIn("cognition-round start phase=startup episode=1 actions=2 state=READY", output)
        self.assertIn("cognition-round end phase=startup episode=1 actions=2 state=READY", output)
        self.assertEqual(output.count("cognition-round start"), output.count("cognition-round end"))
        self.assertNotIn('"natural_language_context"', output)
        self.assertNotIn('"claims"', output)
        self.assertLess(len(output.encode("utf-8")), 4096)

    def test_repeated_cognition_snapshot_is_logged_once(self):
        from asterion.applications.prime.p7.operator import _log_cognition_refresh

        projection = {
            "semantic": {
                "natural_language_context": "这是一个固定快照。",
                "claims": {},
            },
            "cognition_session": {
                "session": {
                    "session_id": "dedupe-test-session",
                    "state": "READY",
                    "episode": 1,
                    "episode_actions": 0,
                },
                "events": [{"sequence": 4, "type": "cognition.snapshot"}],
            },
        }
        stream = io.StringIO()
        with redirect_stderr(stream):
            _log_cognition_refresh(projection, phase="observe")
            _log_cognition_refresh(projection, phase="read")
            _log_cognition_refresh(projection, phase="startup")
        output = stream.getvalue()
        self.assertEqual(output.count("cognition-round start"), 1)
        self.assertEqual(output.count("reason=duplicate-snapshot"), 2)
        self.assertIn("phase=read", output)
        self.assertIn("phase=startup", output)

    def test_cognition_snapshot_sequence_controls_deduplication(self):
        from asterion.applications.prime.p7.operator import _log_cognition_refresh

        def projection(sequence, text):
            return {
                "semantic": {"natural_language_context": text, "claims": {}},
                "cognition_session": {
                    "session": {
                        "session_id": "sequence-test-session",
                        "state": "READY",
                        "episode": 1,
                        "episode_actions": 0,
                    },
                    "events": [{"sequence": sequence, "type": "cognition.snapshot"}],
                },
            }

        stream = io.StringIO()
        with redirect_stderr(stream):
            _log_cognition_refresh(projection(7, "第一版描述"), phase="observe")
            _log_cognition_refresh(projection(7, "第二版描述"), phase="read")
            _log_cognition_refresh(projection(8, "第三版描述"), phase="read")
        output = stream.getvalue()
        self.assertEqual(output.count("cognition-round start"), 2)
        self.assertEqual(output.count("reason=duplicate-snapshot"), 1)

    def test_action_refresh_logs_delta_without_repeating_stable_guide(self):
        from asterion.applications.prime.p7.operator import _log_cognition_refresh

        projection = {
            "semantic": {
                "scope": {"level": 0},
                "confirmed_knowledge": [],
                "claims": {},
                "coverage": {},
            },
            "cognition_session": {
                "session": {
                    "session_id": "compact-action-session",
                    "state": "ACTION_EXECUTED",
                    "episode": 1,
                    "episode_actions": 1,
                },
                "events": [{
                    "sequence": 21,
                    "type": "cognition.action.executed",
                    "action_name": "ACTION4",
                    "changed": True,
                }],
            },
        }
        stream = io.StringIO()
        with redirect_stderr(stream):
            _log_cognition_refresh(projection, phase="act_checked", compact=True)
        output = stream.getvalue()
        self.assertIn("动作后认知更新", output)
        self.assertIn("最近动作：ACTION4 已执行，画面发生变化。", output)
        self.assertNotIn("稳定游戏认知（规划背景）", output)

    def test_round_diagnostic_keeps_p7_signal_when_trace_rejects_callback(self):
        from asterion.agents.prime.execution import PrimeRoundDiagnostic
        from asterion.applications.prime.p7.runtime_binding import _p7_round_diagnostic

        class BrokenTrace:
            def record_model_round(self, diagnostic):
                raise RuntimeError("private trace unavailable")

        diagnostic = PrimeRoundDiagnostic(
            round_index=2,
            prompt_bytes=100,
            prompt_sha256="sha256:" + "a" * 64,
            output_bytes=20,
            output_sha256="sha256:" + "b" * 64,
            prompt_signals=("state-guidance",),
            output_signals=("plan", "action"),
        )
        stream = io.StringIO()
        with redirect_stderr(stream):
            _p7_round_diagnostic(BrokenTrace())(diagnostic)
        self.assertIn("[p7] P7推理轮次：第 3 轮；模型输出信号=plan、action。", stream.getvalue())

    def test_bounded_semantic_report_exposes_stable_worldmap_description(self):
        result = _bounded_semantic_report({
            "scope": {"level": 0},
            "claims": {
                "game_type": [{
                    "id": "current-grid-band-game", "kind": "game_type",
                    "claim": "English source", "status": "certain",
                }],
            },
            "confirmed_knowledge": [{
                "id": "current-grid-band-game", "kind": "game_type",
                "claim": "English source", "status": "certain",
            }],
        })
        description = result["stable_game_description_zh"]
        self.assertIn("稳定游戏认知（规划背景）", description)
        self.assertIn("游戏类型：", description)
        self.assertNotIn("历史原文", description)

    def test_bounded_semantic_report_keeps_confirmed_status_for_refreshes(self):
        bounded = _bounded_semantic_report({
            "scope": {"level": 0},
            "confirmed_knowledge": [{
                "id": "current-grid-band-game", "kind": "game_type",
                "claim": "这是网格街机谜题。", "status": "certain",
            }],
        })
        self.assertEqual(bounded["confirmed_knowledge"][0]["status"], "certain")
        narrative = render_cognition_narrative_zh(bounded, None)
        self.assertIn("游戏类型：", narrative)
        self.assertIn("网格街机谜题", narrative)

    def test_cognition_console_logs_can_use_logic_colors(self):
        from asterion.applications.prime.p7.operator import _log_cognition_refresh, _p7_narrative_role

        projection = {
            "semantic": {"natural_language_context": "这是一个网格移动谜题。"},
            "cognition_session": {
                "session": {"state": "READY", "episode": 1, "episode_actions": 0},
            },
        }
        stream = io.StringIO()
        with mock.patch.dict("os.environ", {"ASTERION_PRIME_P7_COLOR": "always"}), redirect_stderr(stream):
            _log_cognition_refresh(projection, phase="startup")
        output = stream.getvalue()
        self.assertIn("\x1b[", output)
        self.assertIn("cognition-round start", output)
        self.assertIn("cognition-round end", output)
        self.assertEqual(_p7_narrative_role("已确认：横带可移动。"), "confirmed")
        self.assertEqual(_p7_narrative_role("待验证：目标规则尚未确认。"), "pending")
        self.assertEqual(_p7_narrative_role("已否定：ACTION1向下移动。"), "rejected")
        self.assertEqual(_p7_narrative_role("候选验证问题（供P7选择）：检查下一次动作。"), "action")

    def test_compacted_session_preserves_validation_control(self):
        compacted = _compact_cognition_session({
            "state": "ANALYZED", "episode": 2, "episode_actions": 4, "resets": 1,
            "events": [{"sequence": 9, "type": "cognition.snapshot"}],
            "validation": {
                "needed": True, "possible": False, "reason": "no-actionable-hypotheses",
                "actionable_claim_ids": ["a", 3, "b"],
                "ignored": "private detail",
            },
        })
        self.assertEqual(compacted["validation"], {
            "needed": True, "possible": False,
            "reason": "no-actionable-hypotheses",
            "actionable_claim_ids": ["a", "b"],
        })
        self.assertEqual(compacted["event_sequence"], 9)

    def test_cognition_compaction_keeps_validation(self):
        class Broker:
            def cognition_projection(self):
                return {
                    "input_kind": "keyboard",
                    "type_profile": {"authority": "prior-only"},
                    "game_experience": {"history": "x" * 50000},
                    "semantic": {"claims": {}, "natural_language_context": "context"},
                    "cognition_session": {
                        "state": "ANALYZED", "episode": 1, "episode_actions": 1, "resets": 0,
                        "validation": {"needed": True, "possible": False, "reason": "budget"},
                    },
                }

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        result = client.cognition()
        self.assertEqual(result["cognition_session"]["validation"]["reason"], "budget")

    def test_semantic_report_is_byte_bounded_and_deduplicated(self):
        claim = {
            "id": "claim-1", "kind": "control", "subject": "ACTION1",
            "claim": "x" * 4000, "status": "undetermined", "confidence": 0.5,
            "evidence_count": 0, "support_count": 0,
            "counterexample_count": 0, "next_test": "y" * 4000,
        }
        report = {
            "schema": "schema", "scope": {"game_id": "g"},
            "claims": {"control": [claim] * 32, "undetermined": [claim] * 32},
            "natural_language_context": "z" * 8000,
            "evidence_counts": {"total": 0}, "execution_authority": "none",
        }
        bounded = _bounded_semantic_report(report)
        encoded = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
        self.assertLessEqual(len(encoded.encode("utf-8")), 16 * 1024)
        self.assertEqual(len(bounded["claims"]["control"]), 1)
        self.assertNotIn("undetermined", bounded["claims"])

    def test_cognition_preserves_projection_envelope(self):
        class Broker:
            def cognition_projection(self):
                return {
                    "input_kind": "keyboard",
                    "type_profile": {"authority": "prior-only"},
                    "game_experience": {"observations": 2},
                    "semantic": {"claims": {}, "natural_language_context": "context"},
                    "cognition_session": {"state": "PROPOSE"},
                }

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        result = client.cognition()
        self.assertEqual(result["input_kind"], "keyboard")
        self.assertEqual(result["cognition_session"]["state"], "PROPOSE")
        self.assertEqual(result["semantic"]["natural_language_context"], "context")

    def test_cognition_response_caps_large_pending_projection(self):
        class Broker:
            def cognition_projection(self):
                return {
                    "input_kind": "keyboard",
                    "type_profile": {"authority": "prior-only"},
                    "game_experience": {},
                    "semantic": {"claims": {}, "natural_language_context": "c" * 5000},
                    "cognition_session": {
                        "state": "EXPERIMENT_SELECTED",
                        "pending": {"expected": {"frame": [[1] * 10000]}},
                        "events": [{"explanation": "e" * 1000}] * 32,
                    },
                }

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        result = client.cognition()
        self.assertLessEqual(len(json.dumps(result, separators=(",", ":")).encode()), 16 * 1024)
        self.assertEqual(result["cognition_session"]["state"], "EXPERIMENT_SELECTED")

    def test_cognition_compaction_preserves_nested_session_control(self):
        class Broker:
            def cognition_projection(self):
                return {
                    "input_kind": "keyboard",
                    "type_profile": {"authority": "prior-only"},
                    "game_experience": {"history": "x" * 50000},
                    "semantic": {"claims": {}, "natural_language_context": "c" * 5000},
                    "cognition_session": {
                        "state": "EXPERIMENT_SELECTED",
                        "report": {"claims": {}, "natural_language_context": "r" * 50000},
                        "session": {
                            "session_id": "session-1",
                            "episode": 2,
                            "episode_actions": 3,
                            "resets": 1,
                            "state": "EXPERIMENT_SELECTED",
                            "pending": {
                                "claim_ids": ["claim-a", "claim-b", 3],
                                "question": "q" * 5000,
                                "information_gain": "i" * 5000,
                                "action_name": "ACTION1",
                                "expected": {"frame": [[1] * 10000]},
                            },
                            "validation": {
                                "needed": True,
                                "possible": True,
                                "reason": "actionable-hypotheses-remain",
                                "actionable_claim_ids": ["claim-a", "claim-b", 4],
                            },
                        },
                        "events": [{"explanation": "e" * 5000}] * 32,
                        "execution_authority": "none",
                    },
                }

        client = object.__new__(_P7BrokerClient)
        client._broker = Broker()
        result = client.cognition()
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        self.assertLessEqual(len(encoded.encode("utf-8")), 16 * 1024)
        session = result["cognition_session"]["session"]
        self.assertEqual(session["validation"]["actionable_claim_ids"], ["claim-a", "claim-b"])
        self.assertEqual(session["pending"]["claim_ids"], ["claim-a", "claim-b"])
        self.assertEqual(session["pending"]["action_name"], "ACTION1")


if __name__ == "__main__":
    unittest.main()
