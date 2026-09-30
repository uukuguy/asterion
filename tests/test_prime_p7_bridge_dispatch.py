import json
import unittest

from asterion.applications.prime.p7.operator import _IpythonBridgeServer


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


if __name__ == "__main__":
    unittest.main()
