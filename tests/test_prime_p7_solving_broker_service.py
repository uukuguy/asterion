from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch


class TestP7SolvingClient(unittest.TestCase):
    def test_generated_client_contains_only_fixed_transport_and_three_functions(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_client import (
            p7_solving_client_module_bytes,
        )

        source = p7_solving_client_module_bytes(
            "/broker/model.sock", "sentinel-token"
        ).decode()
        self.assertIn("/broker/model.sock", source)
        self.assertIn("sentinel-token", source)
        self.assertIn("def observe()", source)
        self.assertIn("def status()", source)
        self.assertIn("def act(actions)", source)
        for forbidden in (
            "arc_agi",
            "arcengine",
            "environments_dir",
            "api_key",
            "credential",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source.lower())

    def test_service_representation_and_public_results_are_redacted(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker_service import (
            P7SolvingBrokerService,
        )

        service = object.__new__(P7SolvingBrokerService)

        def control(method: str) -> dict[str, object]:
            common = {
                "action_count": 2,
                "levels_completed": 1,
                "score": "3.571429",
                "score_sha256": "sha256:" + "b" * 64,
                "terminal_reason": "level-completed",
            }
            if method == "seal":
                return {**common, "transcript_sha256": "sha256:" + "a" * 64}
            return {**common, "replay_sha256": "sha256:" + "a" * 64}

        service._control = control
        self.assertEqual(repr(service), "P7SolvingBrokerService(redacted)")
        self.assertNotIn("sentinel", repr(service))
        self.assertEqual(service.seal()["score"], "3.571429")
        self.assertEqual(service.replay()["terminal_reason"], "level-completed")

    def test_sdk_engine_uses_locked_step_api_for_primitive_actions(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        calls: list[tuple[object, object]] = []

        class State:
            value = "NOT_FINISHED"

        class Raw:
            available_actions = [1, 2, 6]
            frame = []
            levels_completed = 0
            state = State()
            win_levels = 7

        class Environment:
            def reset(self) -> Raw:
                return Raw()

            def step(self, action: object, data: object) -> Raw:
                calls.append((action, data))
                return Raw()

        class Arcade:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def make(self, *_args: object, **_kwargs: object) -> Environment:
                return Environment()

        arc_agi = types.SimpleNamespace(
            Arcade=Arcade, OperationMode=types.SimpleNamespace(OFFLINE="offline")
        )
        arcengine = types.SimpleNamespace(GameAction={"ACTION1": 1, "ACTION6": 6})
        with (
            TemporaryDirectory() as directory,
            patch.dict(sys.modules, {"arc_agi": arc_agi, "arcengine": arcengine}),
        ):
            from asterion.applications.prime_agent.operator.p7_solving_broker_process import (
                _ArcadeEngine,
            )

            root = Path(directory) / "environment_files/ls20/9607627b"
            root.mkdir(parents=True)
            engine = _ArcadeEngine(root, Path(directory))
            engine.act({"name": "ACTION1", "data": {}})
            engine.act({"name": "ACTION6", "data": {"x": 2, "y": 3}})
        self.assertEqual(calls, [(1, {}), (6, {"x": 2, "y": 3})])

    def test_process_rechecks_exact_resource_identity_before_engine_start(self) -> None:
        from pathlib import Path
        from types import SimpleNamespace

        from asterion.applications.prime_agent.operator.p7_solving_broker_process import (
            P7SolvingBrokerProcessError,
            verify_p7_solving_process_resource,
        )
        from asterion.applications.prime_agent.operator.p7_solving_workload import (
            P7_SOLVING_GAME_ID,
            P7_SOLVING_RESOURCE_SHA256,
        )

        root = Path("/resource/ls20/9607627b")
        valid = SimpleNamespace(
            root=root,
            game_id=P7_SOLVING_GAME_ID,
            resource_sha256=P7_SOLVING_RESOURCE_SHA256,
        )
        with patch(
            "asterion.applications.prime_agent.operator.p7_resource_lock.verify_p7_development_resources",
            return_value=valid,
        ):
            self.assertEqual(verify_p7_solving_process_resource(root), valid)
        changed = SimpleNamespace(
            root=root, game_id=P7_SOLVING_GAME_ID, resource_sha256="sha256:" + "0" * 64
        )
        with patch(
            "asterion.applications.prime_agent.operator.p7_resource_lock.verify_p7_development_resources",
            return_value=changed,
        ):
            with self.assertRaises(P7SolvingBrokerProcessError):
                verify_p7_solving_process_resource(root)

    def test_public_result_value_types_fail_closed(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker_service import (
            P7SolvingBrokerService,
            P7SolvingBrokerServiceError,
        )

        service = object.__new__(P7SolvingBrokerService)
        service._control = lambda _method: {
            "action_count": 2,
            "levels_completed": 1,
            "score": "/private/sentinel",
            "score_sha256": "sha256:" + "b" * 64,
            "terminal_reason": "level-completed",
            "transcript_sha256": "sha256:" + "a" * 64,
        }
        with self.assertRaises(P7SolvingBrokerServiceError):
            service.seal()

    def test_private_presentation_allows_safe_action_cap_evidence(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_broker_service import (
            P7SolvingBrokerService,
            P7SolvingBrokerServiceError,
        )

        service = object.__new__(P7SolvingBrokerService)
        service._control = lambda _method: {
            "action_count": 1,
            "applied_actions": [{"data": {}, "name": "ACTION1"}],
            "completion_grid": [[[1]]],
            "initial_grid": [[[0]]],
            "levels_completed": 0,
            "score": "0.000000",
            "terminal_reason": "action-cap",
        }
        self.assertEqual(service.presentation()["terminal_reason"], "action-cap")

        service._control = lambda _method: {
            "action_count": 1,
            "applied_actions": [{"data": {}, "name": "ACTION1"}],
            "completion_grid": [[["/private/sentinel"]]],
            "initial_grid": [[[0]]],
            "levels_completed": 0,
            "score": "0.000000",
            "terminal_reason": "action-cap",
        }
        with self.assertRaises(P7SolvingBrokerServiceError):
            service.presentation()


if __name__ == "__main__":
    unittest.main()
