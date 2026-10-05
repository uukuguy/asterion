"""Explicit saved-run recovery reaches the actor only after verified replay."""

import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.model_selection import DEFAULT_MODEL
from asterion.applications.prime.p7.operator import (
    P7Invocation, P7LiveAttemptFailure, _P7BrokerClient, run_live,
)
from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from asterion.applications.prime.p7.score import digest
from tests import test_prime_p7_solutions as solutions_fixture
from tests.test_prime_p7_solver import draft


class _LiveEngine(solutions_fixture._Engine):
    def close(self):
        pass


class TestP7ExplicitResume(unittest.TestCase):
    def _run_resume(self, *, divergent=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            arc_root = solutions_fixture.TestP7SavedSolutions._arc_root(root)
            runs = root / ".asterion-private" / "prime-p7-live"
            source = runs / "p7-selected"
            solutions_fixture.TestP7SavedSolutions._write_run(source, target_level=2)
            summary_path = source / "summary.json"
            summary = json.loads(summary_path.read_text())
            summary["experiment"] = {
                "game_id": "ls20-9607627b", "seed": 0,
                "model": DEFAULT_MODEL, "prediction_variant": "verified",
            }
            summary_path.write_text(json.dumps(summary))
            scope = {"game_id": "ls20-9607627b", "seed": 0, "win_levels": 7,
                     "run_id": source.name, "attempt_id": source.name}
            snapshot = {"scope": scope, "parent_revision": None,
                        **{key: draft()[key] for key in (
                            "worldmap", "task", "model", "reports", "evidence_sequences", "correction")}}
            revision = digest(snapshot)
            workspace = source / "research" / digest(scope)[7:]
            (workspace / "revisions").mkdir(parents=True)
            (workspace / "current.json").write_text(json.dumps({"scope": scope, "revision": revision}))
            (workspace / "revisions" / (revision[7:] + ".json")).write_text(json.dumps(snapshot))

            class DivergentEngine(_LiveEngine):
                def observe(self):
                    observation = super().observe()
                    if self.calls == 2:
                        observation["frame"] = [[[99]]]
                    return observation

            async def composed(*args, **kwargs):
                host = kwargs["host_services"]["prime.ipython"]
                context = host.current_context()
                self.assertEqual(context["observation_ref"]["level"], 3)
                self.assertEqual(context["observation_ref"]["sequence"], 5)
                self.assertEqual(context["observation"]["levels_completed"], 2)
                self.assertTrue(context["needs_revision"])
                self.assertEqual(context["worldmap"]["description_zh"], "")
                self.assertEqual(context["reports"], [])
                self.assertIsNone(context["checkpoint"])
                self.assertEqual(context["budget"]["target_level"], 6)
                self.assertIn('"advisory_only":true', kwargs["input_text"])
                self.assertEqual(context["experience"]["latest"]["source_run_id"], source.name)
                self.assertTrue(context["experience"]["requires_current_evidence"])
                value = draft()
                result = host.solver.workspace({
                    "op": "revise", "base_revision": context["workspace_revision"],
                    "worldmap": value["worldmap"], "task": value["task"],
                    "evidence_sequences": [5], "correction": value["correction"],
                })
                self.assertEqual(result["status"], "revised")
                context = host.current_context()
                result = host.solver.execute_plan({
                    "plan_id": "new-plan", "start": context["observation_ref"],
                    "workspace_revision": context["workspace_revision"],
                    "goal": "新关探测", "purpose": "probe", "assumptions": [],
                    "steps": [{"action": {"name": "ACTION1", "data": {}},
                               "expect": {"cells": [{"x": 0, "y": 0, "value": 5}], "levels_completed": 2}}],
                })
                self.assertEqual(len(result["feedback"]), 1)
                raise RuntimeError("bounded fixture stops after one new action")

            def resources(**kwargs):
                broker = ArcBroker(engine=kwargs["engine"], game=kwargs["game"])
                broker.bind_history("p7-resumed")
                evidence = P7PrivateTraceReceipt(broker, PrimeTraceRecorder(kwargs["private_trace_root"]))
                client = _P7BrokerClient(broker, evidence.runtime_recorder, variant="verified")
                host = P7ResearchRuntime(
                    broker=broker, trace_client=client, run_root=kwargs["private_trace_root"].parent,
                    run_id="p7-resumed", deadline_seconds=30, event_sink=lambda *_: None,
                    experience=kwargs["experience"],
                )

                async def close():
                    await host.close()
                    evidence.close()

                return SimpleNamespace(
                    runtime_options={}, host_services={"prime.arc-broker": broker,
                    "prime.private-trace": evidence, "prime.ipython": host},
                    close=close, _bridge=SimpleNamespace(_host_closed=True),
                )

            game = P7GameSelection("ls20-9607627b", 0, 6)
            invocation = P7Invocation(root, {}, arc_root, (), root, game, resume_run_id=source.name)
            assembly = SimpleNamespace(runtime_binding=SimpleNamespace(factory=lambda _: object()), path=root, plan=object())
            with (
                mock.patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=lambda *_: _LiveEngine()),
                mock.patch("asterion.applications.prime.p7.operator.live.SubprocessPythonWorker", return_value=SimpleNamespace(closed=True)),
                mock.patch("asterion.applications.prime.p7.operator.live.ArcadeEngine", side_effect=lambda **kwargs:
                           DivergentEngine() if divergent and kwargs["recordings_dir"].name == "recordings" else _LiveEngine()),
                mock.patch("asterion.applications.prime.p7.operator.build_p7_operator_resources", side_effect=resources),
                mock.patch("asterion.applications.prime.p7.operator._resolve_p7_application", return_value=SimpleNamespace(assemblies=[assembly], implementations=())),
                mock.patch("asterion.applications.prime.p7.operator.run_composed_application", new_callable=mock.AsyncMock, side_effect=composed) as model,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(P7LiveAttemptFailure):
                    asyncio.run(run_live(invocation, "p7-resumed"))
                self.assertEqual(model.await_count, 0 if divergent else 1)
            return json.loads((runs / "p7-resumed" / "summary.json").read_text())

    def test_recovery_precedes_model_and_keeps_new_worldmap_admission(self):
        summary = self._run_resume()
        diagnostics = summary["diagnostics"]
        self.assertEqual(diagnostics["execution_mode"], "resumed")
        self.assertFalse(diagnostics["fresh"])
        self.assertEqual(diagnostics["start_level"], 3)
        self.assertEqual(diagnostics["restoration_actions"], 5)
        self.assertEqual(diagnostics["new_solver_actions"], 1)
        self.assertEqual(diagnostics["budget"]["action_cap"], 5 + 73 + 84 + 96 + 192)
        self.assertTrue(summary["cleanup_complete"])
        self.assertTrue(summary["replay_verified"])

    def test_divergent_restore_rejects_model_and_records_actual_recovery(self):
        summary = self._run_resume(divergent=True)
        self.assertEqual(summary["diagnostics"]["restoration_actions"], 2)
        self.assertEqual(summary["diagnostics"]["new_solver_actions"], 0)
        self.assertTrue(summary["cleanup_complete"])


if __name__ == "__main__":
    unittest.main()
