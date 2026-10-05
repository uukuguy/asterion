"""Game WIN evidence survives a separately failed native model settlement."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests import test_recover_prime_p7_trace_race as race_fixtures
from tests.test_recover_prime_p7_trace_race import _RecordingEngine


class _WinningEngine(_RecordingEngine):
    def _observation(self) -> dict[str, object]:
        value = super()._observation()
        value["state"] = "WIN" if self.calls == 14 else "NOT_FINISHED"
        return value

    def _write(self, action: str, data: dict[str, int] | None = None) -> None:
        # Mirror the SDK recording alongside the actual observation.
        row = {"data": {**self._observation(), "game_id": self.game_id,
                        "action_input": {"id": action, "data": data or {}}}}
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")


class TestTerminalWinRecovery(unittest.TestCase):
    def setUp(self) -> None:
        # Import before patching live.ArcadeEngine: solutions binds that class
        # at import time, and must not retain a test engine for later suites.
        from asterion.applications.prime.p7 import solutions
        self.assertTrue(callable(solutions.load_exact_prefix))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def _source(self, root: Path, *, seal: bool = False) -> Path:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from asterion.applications.prime.p7 import live

        run_id = "p7-live-20261006022156-6ee2768ba89e485eba69614e"
        run = live.private_root(root, run_id)
        (run / "trace").mkdir()
        game = P7GameSelection("ls20-9607627b", 0, 7)
        broker = ArcBroker(engine=_WinningEngine(recordings_dir=run / "recordings", game=game), game=game)
        recorder = PrimeTraceRecorder(run / "trace")
        from asterion.applications.prime.p7.private_trace import trace_identities_for
        identities = trace_identities_for("gpt-6.1-sol")
        client = _P7BrokerClient(broker, recorder, identities, variant="legacy")
        for _ in range(14):
            client.act([{"name": "ACTION1", "data": {}}])
        receipt = broker.seal()
        broker.replay(lambda: _WinningEngine(recordings_dir=run / "replay-recordings", game=game))
        if seal:
            from asterion.applications.prime.p7.operator import _seal_verified_game_win
            self.assertTrue(_seal_verified_game_win(broker, P7PrivateTraceReceipt(broker, recorder, identities), receipt))
        recorder.close()
        live.write_summary(root, run, run_id=run_id, receipt={}, broker_receipt=receipt,
                           game=game, replay_verified=True, sealed_trace=seal, cleanup_complete=True,
                           comparison_report=None, reason="P7 live solve unsuccessful",
                           failure=RuntimeError("model settlement failed"),
                           diagnostics={"failure_classification": {"category": "model_rpc_error"}})
        from asterion.applications.prime.p7.score import digest
        summary_path = run / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["experiment"] = {"game_id": game.game_id, "seed": 0,
                                 "model": identities["model_id"], "prediction_variant": "verified"}
        summary_path.write_text(json.dumps(summary))
        scope = {"game_id": game.game_id, "seed": 0, "win_levels": 7,
                 "run_id": run.name, "attempt_id": run.name}
        snapshot = {"scope": scope, "worldmap": {"description_zh": "原始研究", "state_summary": "WIN",
                   "rules": [], "unknowns": [], "competing_hypotheses": []}}
        revision = digest(snapshot)
        workspace = run / "research" / digest(scope)[7:]
        (workspace / "revisions").mkdir(parents=True)
        (workspace / "current.json").write_text(json.dumps({"scope": scope, "revision": revision}))
        (workspace / "revisions" / (revision[7:] + ".json")).write_text(json.dumps(snapshot))
        return run

    def test_replays_new_win_without_mutating_original_failure(self) -> None:
        from tools.recover_prime_p7_trace_race import recover_terminal_win
        from asterion.applications.prime.p7.solutions import load_exact_prefix

        for sealed in (False, True):
            with self.subTest(sealed=sealed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                arc = race_fixtures.TestRecoverPrimeP7TraceRace._arc_root(root)
                source = self._source(root, seal=sealed)
                before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
                with (
                    mock.patch("tools.recover_prime_p7_trace_race.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: _WinningEngine(recordings_dir=recordings_dir, game=game)),
                    mock.patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=lambda _arc, game, recordings: _WinningEngine(recordings_dir=recordings, game=game)),
                ):
                    recovered = recover_terminal_win(operator_root=root, arc_root=arc, source_run_id=source.name)
                    prefix = load_exact_prefix(arc, recovered.parent, recovered.name, "ls20-9607627b", 0)
                    from asterion.applications.prime.p7.official_operator import _load_current_roster_prefixes
                    from asterion.applications.prime.p7.console_overview import ConsoleOverview
                    catalog = ({"game_id": "ls20-9607627b", "win_levels": 7,
                                "baseline_actions": [22, 123, 73, 84, 96, 192, 186]},)
                    admitted = _load_current_roster_prefixes(arc, recovered.parent, catalog)
                    self.assertEqual([item.source_run_id for item in admitted], [recovered.name])
                    row = ConsoleOverview(recovered.parent, catalog)._read_run(recovered, {catalog[0]["game_id"]: catalog[0]})
                    self.assertEqual(row["status"], "completed")
                    self.assertEqual(row["source_runtime_status"], "failed")
                self.assertIsNotNone(prefix)
                self.assertEqual(prefix.levels_completed, 7)
                summary = json.loads((recovered / "summary.json").read_text())
                self.assertEqual(summary["diagnostics"]["recovery_kind"], "terminal-game-win")
                self.assertEqual(summary["diagnostics"]["execution_mode"], "offline-replay")
                self.assertEqual(summary["broker"]["terminal_reason"], "game-won")
                self.assertEqual(summary["receipt"]["completed_level_count"], 7)
                from asterion.applications.prime.p7.solutions import source_experiment, load_resume_worldmap
                self.assertEqual(source_experiment(recovered, summary)["prediction_variant"], "verified")
                self.assertEqual(summary["experiment"]["prediction_variant"], "offline-replay")
                self.assertEqual(load_resume_worldmap(recovered, prefix)["source_run_id"], source.name)
                self.assertFalse((recovered / "research").exists())
                self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()})
                if sealed:
                    seal_path = source / "trace/prime-trace.seal.json"
                    seal_bytes = seal_path.read_bytes()
                    seal_path.write_bytes(seal_bytes + b" ")
                    self.assertIsNone(source_experiment(recovered, summary))
                    self.assertIsNone(load_resume_worldmap(recovered, prefix))
                    seal_path.write_bytes(seal_bytes)
                source_summary = source / "summary.json"
                source_summary.write_text(source_summary.read_text() + " ")
                self.assertIsNone(source_experiment(recovered, summary))
                self.assertIsNone(load_resume_worldmap(recovered, prefix))

    def test_lineage_and_official_selection_reject_changed_provenance(self) -> None:
        from tools.recover_prime_p7_trace_race import recover_terminal_win
        from asterion.applications.prime.p7.solutions import source_experiment, load_resume_worldmap, VerifiedPrefix
        from asterion.applications.prime.p7.official_operator import _load_current_roster_prefixes

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = race_fixtures.TestRecoverPrimeP7TraceRace._arc_root(root)
            source = self._source(root)
            with mock.patch("tools.recover_prime_p7_trace_race.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: _WinningEngine(recordings_dir=recordings_dir, game=game)):
                recovered = recover_terminal_win(operator_root=root, arc_root=arc, source_run_id=source.name)
            summary_path = recovered / "summary.json"
            original_summary = summary_path.read_text()
            catalog = ({"game_id": "ls20-9607627b", "win_levels": 7,
                        "baseline_actions": [22, 123, 73, 84, 96, 192, 186]},)
            scope = VerifiedPrefix("ls20-9607627b", 0, 7, 0, (), recovered.name, "")
            recording = next((source / "recordings").glob("*/*.jsonl"))
            original_recording = recording.read_bytes()
            for mutation in ("game", "seed", "model", "variant", "recording", "seal", "source", "broker"):
                with self.subTest(mutation=mutation):
                    summary = json.loads(original_summary)
                    if mutation in {"game", "seed", "model", "variant"}:
                        key, value = {"game": ("game_id", "wrong-game"), "seed": ("seed", 1),
                                      "model": ("model", "wrong-model"),
                                      "variant": ("prediction_variant", "verified")}[mutation]
                        summary["experiment"][key] = value
                    elif mutation == "recording":
                        recording.write_bytes(original_recording + b"\n")
                    elif mutation == "seal":
                        (source / "trace/prime-trace.seal.json").write_text("{}")
                    elif mutation == "source":
                        summary["diagnostics"]["recovered_from"] = recovered.name
                    elif mutation == "broker":
                        summary["broker"]["seed"] = 1
                    summary_path.write_text(json.dumps(summary))
                    self.assertIsNone(source_experiment(recovered, summary))
                    self.assertIsNone(load_resume_worldmap(recovered, scope))
                    with mock.patch("asterion.applications.prime.p7.solutions._fresh_engine") as replay:
                        self.assertEqual(_load_current_roster_prefixes(arc, recovered.parent, catalog), ())
                        replay.assert_not_called()
                    recording.write_bytes(original_recording)
                    (source / "trace/prime-trace.seal.json").unlink(missing_ok=True)
                    summary_path.write_text(original_summary)

    def test_rejects_inconsistent_evidence_before_creating_output(self) -> None:
        from tools.recover_prime_p7_trace_race import RecoveryError, recover_terminal_win
        for mutation in ("chain", "cleanup", "false_win", "recording", "replay", "model"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                arc = race_fixtures.TestRecoverPrimeP7TraceRace._arc_root(root)
                source = self._source(root)
                summary_path = source / "summary.json"
                summary = json.loads(summary_path.read_text())
                if mutation == "chain":
                    trace = source / "trace/prime-trace.jsonl"
                    rows = trace.read_text().splitlines()
                    trace.write_text("\n".join(rows[1:]) + "\n")
                elif mutation == "cleanup":
                    summary["cleanup_complete"] = False
                elif mutation == "false_win":
                    summary["broker"]["terminal_reason"] = "level-completed"
                elif mutation == "model":
                    summary["experiment"]["model"] = "wrong-model"
                elif mutation == "recording":
                    path = next((source / "recordings").glob("*/*.jsonl"))
                    path.write_text(path.read_text().replace('"WIN"', '"NOT_FINISHED"'))
                summary_path.write_text(json.dumps(summary))
                factory = _RecordingEngine if mutation == "replay" else _WinningEngine
                with mock.patch("tools.recover_prime_p7_trace_race.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: factory(recordings_dir=recordings_dir, game=game)):
                    with self.assertRaisesRegex(RecoveryError, "source is unavailable"):
                        recover_terminal_win(operator_root=root, arc_root=arc, source_run_id=source.name)
                self.assertEqual(list(source.parent.iterdir()), [source])

    def test_live_failure_seals_game_evidence_without_native_receipt(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import P7Invocation, P7LiveAttemptFailure, _P7BrokerClient, run_live
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from asterion.applications.prime.p7.live import read_trace_entries
        from asterion.runner import ApplicationRunError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = P7GameSelection("ls20-9607627b", 0, 7)
            client = None
            def build(**kwargs: object) -> SimpleNamespace:
                nonlocal client
                broker = ArcBroker(engine=kwargs["engine"], game=game)
                evidence = P7PrivateTraceReceipt(broker, PrimeTraceRecorder(kwargs["private_trace_root"]))
                client = _P7BrokerClient(broker, evidence.runtime_recorder, variant="legacy")
                async def close() -> None:
                    evidence.close()
                return SimpleNamespace(runtime_options={}, host_services={"prime.arc-broker": broker, "prime.private-trace": evidence}, close=close)
            async def composed(*args: object, **kwargs: object) -> None:
                for _ in range(14):
                    client.act([{"name": "ACTION1", "data": {}}])
                raise ApplicationRunError("application capability execution failed")
            rpc = SimpleNamespace(last_failure="Pi RPC output limit exceeded (line)")
            runtime = SimpleNamespace(_session=SimpleNamespace(_rpc_session=rpc))
            assembly = SimpleNamespace(runtime_binding=SimpleNamespace(factory=lambda _: runtime), path=root, plan=object())
            with (
                mock.patch("asterion.applications.prime.p7.operator.live.SubprocessPythonWorker", return_value=SimpleNamespace(closed=True)),
                mock.patch("asterion.applications.prime.p7.operator.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: _WinningEngine(recordings_dir=recordings_dir, game=game)),
                mock.patch("asterion.applications.prime.p7.operator.build_p7_operator_resources", side_effect=build),
                mock.patch("asterion.applications.prime.p7.operator._resolve_p7_application", return_value=SimpleNamespace(assemblies=[assembly], implementations=())),
                mock.patch("asterion.applications.prime.p7.operator.run_composed_application", side_effect=composed),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(P7LiveAttemptFailure) as caught:
                    asyncio.run(run_live(P7Invocation(root, {"ASTERION_PRIME_P7_HISTORY_VARIANT": "legacy"}, root, (), root, game), "p7-live-win-failure"))
            self.assertTrue(caught.exception.sealed_trace)
            self.assertTrue(caught.exception.replay_verified)
            run = root / ".asterion-private/prime-p7-live/p7-live-win-failure"
            summary = json.loads((run / "summary.json").read_text())
            self.assertEqual(summary["receipt"], {})
            self.assertIsNone(summary["completed_prefix"])
            self.assertEqual(summary["failure"]["type"], "ApplicationRunError")
            self.assertEqual(summary["diagnostics"]["failure_classification"]["category"], "model_rpc_error")
            kinds = [e.kind for e in read_trace_entries(run / "trace")]
            self.assertIn("arc.run.game-won", kinds)
            self.assertNotIn("arc.run.completed", kinds)
