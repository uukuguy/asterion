import json
import io
import unittest
from contextlib import redirect_stderr

from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
from asterion.applications.prime.p7.operator import (
    _IpythonBridgeServer,
    _P7BrokerClient,
    _bounded_semantic_report,
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
        for method in ("observe", "status", "mechanics_prior", "world_model", "cognition", "retrodiction_status"):
            with self.subTest(method=method):
                response = self.bridge._dispatch_method_call("request", method, {})
                self.assertEqual(response["status"], "ok")
            self.assertEqual(response["type"], "method_result")

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

    def test_cognition_update_logs_complete_correlated_request_and_outcome(self):
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
        self.assertEqual(requests[0]["payload"], payload)
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
                                "claim": "ACTION2 moves the player right.", "status": "certain", "confidence": 0.8,
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
        claim = states[0]["cognition"]["report"]["claims"]["control"][0]
        self.assertEqual(claim["id"], "move-right")
        self.assertEqual(claim["status"], "certain")
        self.assertEqual(states[0]["cognition"]["session"]["state"], "ANALYZED")

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


if __name__ == "__main__":
    unittest.main()
