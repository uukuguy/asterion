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
    identities = {"model_id": "deepseek-v4-flash", "reasoning_id": "asterion.prime"}
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
            self.assertEqual(terminal["terminal_reason"], "game-over")
            self.assertEqual(len(broker.journal), 1)
            recorder.close()

    def test_worker_act_uses_terminal_batch_without_followup_calls(self) -> None:
        namespace: dict[str, object] = {}
        exec(live_module.client_module_source("/tmp/test-p7.sock"), namespace)
        calls: list[str] = []

        def fake_call(method: str, *args: object) -> object:
            calls.append(method)
            if method != "act":
                raise AssertionError("terminal state must come from act response")
            return {
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
                    "terminal_reason": "game-over",
                },
            }

        namespace["_call"] = fake_call
        view = namespace["act"]("ACTION1")  # type: ignore[operator]
        self.assertEqual(view["terminal"], "GAME_OVER")
        self.assertEqual(view["actions_taken"], 1)
        self.assertEqual(namespace["summary"](view)["status"]["terminal_reason"], "game-over")  # type: ignore[operator]
        self.assertEqual(calls, ["act"])

    def test_unsuccessful_public_receipt_preserves_safe_game_over_evidence(self) -> None:
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.operator import P7LiveAttemptFailure, main

        error = P7LiveAttemptFailure(
            primitive_actions=50,
            levels_completed=0,
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

    def test_run_live_seals_and_replays_game_over_failure_before_cleanup(self) -> None:
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import DEFAULT_GAME
        from asterion.applications.prime.p7.operator import P7Invocation, P7LiveAttemptFailure, run_live
        from tests.test_prime_p7_native_broker import _Engine

        class Engine(_Engine):
            def __init__(self, **kwargs: object) -> None:
                super().__init__(game_over_after=1)

            def close(self) -> None:
                pass

        class Worker:
            closed = False

        async def composed(*args: object, **kwargs: object) -> None:
            broker.act(("ACTION1",))
            raise RuntimeError("private model detail")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = Worker()
            broker = ArcBroker(engine=Engine())

            async def close_resources() -> None:
                worker.closed = True

            resources = SimpleNamespace(
                runtime_options={},
                host_services={"prime.arc-broker": broker},
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
                mock.patch("asterion.applications.prime.p7.operator.build_p7_operator_resources", return_value=resources),
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
            self.assertFalse(failure.sealed_trace)
            summary = json.loads((root / ".asterion-private/prime-p7-live/p7-live-test/summary.json").read_text())
            self.assertEqual(summary["broker"]["primitive_actions"], 1)
            self.assertEqual(summary["broker"]["terminal_reason"], "game-over")
            self.assertTrue(summary["replay_verified"])

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
