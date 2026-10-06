"""Live saves publish certification only after finalized evidence exists."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


class TestLiveSaveCertificate(unittest.TestCase):
    def test_publication_preserves_summary_and_reports_pending_without_losing_evidence(self) -> None:
        from asterion.applications.prime.p7 import operator, solution_certificates

        publish = getattr(operator, "_publish_save_certificate", None)
        self.assertTrue(callable(publish), "finalized save certificate publication is required")
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            summary = b'{"cleanup_complete": true, "sealed_trace": true}\n'
            (run / "summary.json").write_bytes(summary)
            witness = object()
            calls = []

            def certify(arc_root, source, actual, *, expected_model_id):
                self.assertEqual((source / "summary.json").read_bytes(), summary)
                self.assertIs(actual, witness)
                self.assertEqual(expected_model_id, "gpt-6.1-sol")
                calls.append(source)

            module = SimpleNamespace(
                publish_verified_save=certify,
                SourceProvenanceCapacityError=solution_certificates.SourceProvenanceCapacityError,
            )
            with mock.patch.dict("sys.modules", {
                "asterion.applications.prime.p7.solution_certificates": module,
            }):
                publish(run, run, witness, expected_model_id="gpt-6.1-sol", eligible=True)
                self.assertEqual(json.loads((run / "solution-certification-status.json").read_text())["status"], "ready")
                module.publish_verified_save = mock.Mock(side_effect=ValueError("private-sentinel"))
                publish(run, run, witness, expected_model_id="gpt-6.1-sol", eligible=True)
                status = (run / "solution-certification-status.json").read_text()
                self.assertEqual(json.loads(status)["status"], "pending")
                self.assertNotIn("private-sentinel", status)
                publish(run, run, witness, expected_model_id="gpt-6.1-sol", eligible=False)
                self.assertEqual(module.publish_verified_save.call_count, 1)
            self.assertEqual(calls, [run])
            self.assertEqual((run / "summary.json").read_bytes(), summary)

    def test_partial_save_keeps_exact_successful_replay_witness(self) -> None:
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7 import operator
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
        from asterion.applications.prime.p7.replay import replay_arc_run
        from tests.test_prime_p7_solutions import _Engine

        self.assertIn("verification_witnesses", __import__("inspect").signature(operator._seal_verified_partial_run).parameters)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "trace").mkdir()
            game = P7GameSelection("ls20-9607627b", 0, 7)
            broker = ArcBroker(engine=_Engine(), game=game)
            recorder = PrimeTraceRecorder(run / "trace")
            evidence = P7PrivateTraceReceipt(broker, recorder)
            client = operator._P7BrokerClient(broker, recorder, variant="legacy")
            client.act([{"name": "ACTION1", "data": {}}] * 3)
            witness = object()
            verified = []

            def verify(arc_root, selected_game, transitions, receipt, observations, engine_factory):
                self.assertEqual(len(transitions), 2)
                self.assertEqual(len(observations), 3)
                result = replay_arc_run(transitions, receipt, engine_factory, game=selected_game, observations=observations)
                verified.append(result)
                return result, witness

            module = SimpleNamespace(verify_for_save=verify)
            retained = []
            with mock.patch.dict("sys.modules", {
                "asterion.applications.prime.p7.solution_certificates": module,
            }), mock.patch.object(operator.live, "ArcadeEngine", side_effect=lambda **_: _Engine()) as engines:
                prefix = operator._seal_verified_partial_run(broker, evidence, run, run, verification_witnesses=retained)
            self.assertEqual(prefix["primitive_actions"], 2)
            self.assertEqual(retained, [witness])
            self.assertEqual(len(verified), 1)
            self.assertEqual(engines.call_count, 1)

    def test_recovery_publishes_its_own_verified_save_after_final_summary(self) -> None:
        from asterion.applications.prime.p7.replay import replay_arc_run
        from asterion.applications.prime.p7 import solution_certificates
        from tests.test_prime_p7_terminal_recovery import TestTerminalWinRecovery, _WinningEngine
        from tests.test_recover_prime_p7_trace_race import TestRecoverPrimeP7TraceRace
        from tools.recover_prime_p7_trace_race import recover_terminal_win

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = TestRecoverPrimeP7TraceRace._arc_root(root)
            source = TestTerminalWinRecovery()._source(root)
            before = (source / "summary.json").read_bytes()
            witness = object()
            certified = []
            replayed = []

            def verify(arc_root, game, transitions, receipt, observations, engine_factory):
                result = replay_arc_run(transitions, receipt, engine_factory, game=game, observations=observations)
                replayed.append(result)
                return result, witness

            def publish(arc_root, run, actual, *, expected_model_id):
                summary = json.loads((run / "summary.json").read_text())
                self.assertEqual(summary["diagnostics"]["recovery_kind"], "terminal-game-win")
                self.assertTrue(summary["cleanup_complete"])
                self.assertIs(actual, witness)
                self.assertEqual(expected_model_id, "gpt-6.1-sol")
                certified.append(run)

            # Keep static source authentication real. This fixture checks
            # publication ordering; real typed-witness inventory admission has
            # separate coverage in the terminal animation recovery tests.
            with mock.patch.object(solution_certificates, "verify_for_save", side_effect=verify), \
                    mock.patch.object(solution_certificates, "publish_verified_save", side_effect=publish), \
                    mock.patch("tools.recover_prime_p7_trace_race._register_terminal_rejection") as rejection, \
                    mock.patch("tools.recover_prime_p7_trace_race.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: _WinningEngine(recordings_dir=recordings_dir, game=game)):
                recovered = recover_terminal_win(operator_root=root, arc_root=arc, source_run_id=source.name)
                rejection.assert_called_once()
                self.assertIs(rejection.call_args.args[-1], witness)
            self.assertEqual(certified, [recovered])
            self.assertEqual(len(replayed), 1)
            self.assertEqual((source / "summary.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
