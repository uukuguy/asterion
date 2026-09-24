"""Official P7 operator boundaries without model or ARC network calls."""

from __future__ import annotations

import unittest
import asyncio
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from asterion.applications.prime.p7.game import ArcGameContract
from asterion.applications.prime.p7.operator import p7_runtime_options, resolve_p7_runtime


class TestOfficialOperator(unittest.TestCase):
    def test_submit_without_credentials_rejects_before_card_or_recovery(self) -> None:
        from asterion.applications.prime.p7.official import OfficialError
        from asterion.applications.prime.p7.official_operator import main

        output = StringIO()
        with (
            mock.patch.dict("os.environ", {"ASTERION_PRIME_P7_OFFICIAL_MODE": "submit"}, clear=True),
            mock.patch("asterion.applications.prime.p7.official_operator._preflight", side_effect=OfficialError("secret")),
            mock.patch("asterion.applications.prime.p7.official_operator.prepare_session") as prepare,
            redirect_stdout(output),
        ):
            status = main([])
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue().strip(), '{"status":"preflight-rejected"}')
        prepare.assert_not_called()
        self.assertNotIn("secret", output.getvalue())

    def test_invocation_repr_redacts_both_credentials(self) -> None:
        from asterion.applications.prime.p7.official_operator import OfficialInvocation

        invocation = OfficialInvocation(
            Path("/tmp"), {"DEEPSEEK_API_KEY": "model-secret"},
            ("/usr/bin/pi",), Path("/tmp/extension"), "arc-secret",
        )
        self.assertNotIn("model-secret", repr(invocation))
        self.assertNotIn("arc-secret", repr(invocation))

    def test_read_only_preflight_never_opens_card_or_model(self) -> None:
        from asterion.applications.prime.p7.official_operator import main

        class Session:
            preflight = SimpleNamespace(game_count=1, total_action_cap=1000,
                                        total_model_callback_cap=128,
                                        total_deadline_seconds=3600, games=(
                SimpleNamespace(game_id="ab12-12345678", action_cap=1000,
                                model_callback_cap=128, deadline_seconds=3600),
            ))

            def __enter__(self) -> "Session":
                return self

            def __exit__(self, *args: object) -> None:
                pass

            def open(self) -> None:
                raise AssertionError("card opened during preflight")

        output = StringIO()
        with (
            TemporaryDirectory() as directory,
            mock.patch.dict("os.environ", {"ASTERION_PRIME_P7_OFFICIAL_MODE": "preflight"}, clear=True),
            mock.patch("asterion.applications.prime.p7.official_operator._preflight", return_value=SimpleNamespace(operator_root=Path(directory), api_key="private")),
            mock.patch("asterion.applications.prime.p7.official_operator.prepare_session", return_value=Session()),
            redirect_stdout(output),
        ):
            status = main([])
        self.assertEqual(status, 0)
        self.assertIn('"status":"ready"', output.getvalue())
        self.assertIn('"total_model_callback_cap":128', output.getvalue())
        self.assertIn('"total_deadline_seconds":3600', output.getvalue())
        self.assertNotIn("private", output.getvalue())

    def test_recovery_record_is_written_after_abort_close(self) -> None:
        from asterion.applications.prime.p7.official_operator import main

        class Session:
            aborted = False

            def __enter__(self) -> "Session":
                return self

            def __exit__(self, *args: object) -> None:
                self.aborted = True

        session = Session()
        observed = []

        def record(value: Session, root: Path) -> None:
            observed.append(value.aborted)

        output = StringIO()
        with (
            TemporaryDirectory() as directory,
            mock.patch.dict("os.environ", {"ASTERION_PRIME_P7_OFFICIAL_MODE": "submit"}, clear=True),
            mock.patch("asterion.applications.prime.p7.official_operator._preflight", return_value=SimpleNamespace(operator_root=Path(directory), api_key="private")),
            mock.patch("asterion.applications.prime.p7.official_operator.prepare_session", return_value=session),
            mock.patch("asterion.applications.prime.p7.official_operator._submit", new_callable=mock.AsyncMock, side_effect=RuntimeError("private failure")),
            mock.patch("asterion.applications.prime.p7.official_operator.write_recovery_record", side_effect=record),
            redirect_stdout(output),
        ):
            status = main([])
        self.assertEqual(status, 1)
        self.assertEqual(observed, [True])
        self.assertIn('"status":"recovery-required"', output.getvalue())
        self.assertNotIn("private failure", output.getvalue())

    def test_reset_guidance_uses_the_actual_broker_call_shape(self) -> None:
        from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT

        self.assertIn('p7_client.act([{"name":"RESET","data":{}}])', P7_SOLVE_PROMPT)
        self.assertNotIn('act("RESET")', P7_SOLVE_PROMPT)

    def test_official_game_uses_bounded_gameplay_runtime(self) -> None:
        game = ArcGameContract("ab12-12345678", win_levels=12, action_cap=1000)
        selection = resolve_p7_runtime({"DEEPSEEK_API_KEY": "private"}, game)

        self.assertEqual(selection.max_actions, 1000)
        self.assertEqual(selection.deadline_ms, 3_600_000)
        self.assertEqual(p7_runtime_options(selection, game)["max_actions"], "1000")

    def test_official_resources_route_scoreless_evidence_without_arc_key(self) -> None:
        from asterion.applications.prime.p7.gameplay_trace import PrimeGameplayTrace
        from asterion.applications.prime.p7.official_operator import _resolve_gameplay_application
        from asterion.applications.prime.p7.operator import build_p7_operator_resources
        from asterion.runtime.factory import RuntimeFactoryContext
        from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient

        class Engine:
            game_id = "ab12-12345678"
            guid = "guid-private"
            seed = 0

            def observe(self) -> dict[str, object]:
                return {"available_actions": ["ACTION1"], "frame": [[[1]]],
                        "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 2}

            def step(self, action: str) -> dict[str, object]:
                return self.observe()

        class Worker:
            async def start(self, *args: object, **kwargs: object) -> None:
                pass

            async def execute_cell(self, *args: object, **kwargs: object) -> None:
                pass

            async def close(self) -> None:
                pass

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / "extension.mjs"
            extension.write_text("export default function extension() {}\n")
            trace_root = root / "trace"
            trace_root.mkdir()
            resources = build_p7_operator_resources(
                environment={"DEEPSEEK_API_KEY": "model-secret", "ARC_API_KEY": "arc-secret"},
                pi_base_command=("/usr/bin/pi", "--mode", "rpc"),
                extension_path=extension,
                working_directory=root,
                worker=Worker(),
                engine=Engine(),
                private_trace_root=trace_root,
                game=ArcGameContract("ab12-12345678", 2),
            )
            self.assertEqual(set(resources.host_services), {
                "prime.arc-broker", "prime.ipython", "prime.launch", "prime.arc-run-evidence",
            })
            self.assertIs(type(resources.host_services["prime.arc-run-evidence"]), PrimeGameplayTrace)
            launch = resources.host_services["prime.launch"]
            self.assertNotIn("ARC_API_KEY", launch.approved_environment)
            self.assertNotIn("arc-secret", repr(resources))
            application = _resolve_gameplay_application()
            assembly = application.assemblies[0]
            self.assertEqual(dict(resources.runtime_options), {
                "deadline_ms": "3600000", "max_actions": "1000", "max_callbacks": "128",
                "model": "deepseek-v4-flash", "provider": "deepseek",
            })
            runtime = assembly.runtime_binding.factory(RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-gameplay",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=assembly.path,
                options=resources.runtime_options,
                host_services=resources.host_services,
            ))
            self.assertIs(type(runtime), AsterionPrimeRuntimeClient)
            asyncio.run(resources.close())

    def test_game_engine_closes_if_host_resources_fail_to_initialize(self) -> None:
        from asterion.applications.prime.p7.official_operator import (
            OfficialInvocation,
            _run_game,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            invocation = OfficialInvocation(
                operator_root=root,
                environment={"DEEPSEEK_API_KEY": "private"},
                pi_base_command=("pi",),
                extension_path=root / "extension.mjs",
                api_key="arc-private",
            )
            engine = mock.Mock()
            with mock.patch(
                "asterion.applications.prime.p7.official_operator.build_p7_operator_resources",
                side_effect=RuntimeError("private host failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "private host failure"):
                    asyncio.run(_run_game(
                        invocation,
                        mock.Mock(),
                        root,
                        engine,
                        ArcGameContract("ab12-12345678", 2),
                        "p7-official-cleanup",
                    ))
            engine.close.assert_called_once_with()

    def test_host_cleanup_releases_trace_and_extension_after_worker_failure(self) -> None:
        from asterion.applications.prime.p7.operator import P7OperatorResources

        bridge = SimpleNamespace(close=mock.Mock())
        ipython = SimpleNamespace(
            close=mock.AsyncMock(side_effect=RuntimeError("private worker failure"))
        )
        trace = SimpleNamespace(close=mock.Mock())
        lease = SimpleNamespace(close=mock.Mock())
        launch = SimpleNamespace(extension_lease=lease)
        resources = P7OperatorResources(
            host_services={
                "prime.ipython": ipython,
                "prime.private-trace": trace,
                "prime.launch": launch,
            },
            runtime_options={},
            _bridge=bridge,
        )

        with self.assertRaisesRegex(RuntimeError, "private worker failure"):
            asyncio.run(resources.close())
        bridge.close.assert_called_once_with()
        ipython.close.assert_awaited_once_with()
        trace.close.assert_called_once_with()
        lease.close.assert_called_once_with()

    def test_one_card_attempts_every_game_despite_one_game_failure(self) -> None:
        from asterion.applications.prime.p7.official_operator import run_official_games

        class Session:
            preflight = SimpleNamespace(games=(
                SimpleNamespace(game_id="ab12-12345678", action_cap=1000),
                SimpleNamespace(game_id="cd34-87654321", action_cap=1200),
            ))

            def __init__(self) -> None:
                self.calls = []

            def open(self) -> str:
                self.calls.append("open")
                return "card"

            def make(self, game_id: str) -> SimpleNamespace:
                self.calls.append(("make", game_id))
                return SimpleNamespace(game_id=game_id, win_levels=2)

            def close(self) -> object:
                self.calls.append("close")
                return object()

        session = Session()

        async def run_game(engine: SimpleNamespace, game: ArcGameContract, run_id: str) -> None:
            session.calls.append(("run", game.game_id, game.action_cap, run_id))
            if game.game_id == "ab12-12345678":
                raise RuntimeError("private model output")

        attempts = asyncio.run(run_official_games(session, run_game))
        self.assertEqual(tuple(a.status for a in attempts), ("run-failed", "run-completed"))
        self.assertEqual(session.calls[0], "open")
        self.assertEqual(session.calls[-1], "close")
        self.assertEqual(len([call for call in session.calls if isinstance(call, tuple) and call[0] == "make"]), 2)
        self.assertNotIn("private model output", repr(attempts))


if __name__ == "__main__":
    unittest.main()
