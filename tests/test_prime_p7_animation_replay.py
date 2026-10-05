"""Random intermediate animation never authorizes a changed settled state."""

from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_recover_prime_p7_trace_race import _RecordingEngine
from tests import test_recover_prime_p7_trace_race as fixtures


class _Animated(_RecordingEngine):
    noise = 2

    def _observation(self):
        value = super()._observation()
        value["frame"] = [[[type(self).noise]], *value["frame"]]
        return value

    def _write(self, action, data=None):
        with self._path.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "data": {
                            **self._observation(),
                            "game_id": self.game_id,
                            "action_input": {"id": action, "data": data or {}},
                        }
                    }
                )
                + "\n"
            )


class TestAnimationReplay(unittest.TestCase):
    def _source(self, root):
        from asterion.applications.prime.p7 import live
        from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.private_trace import (
            P7PrivateTraceReceipt,
            trace_identities_for,
        )
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from tools.recover_prime_p7_trace_race import _receipt_mapping

        rid = "p7-live-20261006064304-7096300396424db6b3c63325"
        run = live.private_root(root, rid)
        (run / "trace").mkdir()
        game = P7GameSelection("ls20-9607627b", 0, 2)
        broker = ArcBroker(
            engine=_Animated(recordings_dir=run / "recordings", game=game), game=game
        )
        recorder = PrimeTraceRecorder(run / "trace")
        identities = trace_identities_for("gpt-6.1-sol")
        evidence = P7PrivateTraceReceipt(broker, recorder, identities)
        recorder.append(
            "arc.run.context",
            identities,
            {
                "run_id": rid,
                "game_id": game.game_id,
                "seed": 0,
                "win_levels": 7,
                "model_id": "gpt-6.1-sol",
                "target_level": 2,
                "source_run_id": None,
                "restoration_actions": 0,
            },
        )
        client = _P7BrokerClient(broker, recorder, identities, variant="legacy")
        for _ in range(4):
            client.act([{"name": "ACTION1", "data": {}}])
        receipt = evidence.get_receipt(
            run_id=rid, receipt_sha256=evidence.expected_receipt_sha256(run_id=rid)
        )
        live.write_summary(
            root,
            run,
            run_id=rid,
            receipt=_receipt_mapping(receipt),
            broker_receipt=broker.seal(),
            game=game,
            replay_verified=False,
            sealed_trace=False,
            cleanup_complete=True,
            comparison_report=None,
            reason="replay unavailable",
            failure=ArcBrokerError("unavailable"),
            experiment={
                "game_id": game.game_id,
                "seed": 0,
                "model": "gpt-6.1-sol",
                "target_level": 2,
                "prediction_variant": "verified",
            },
            diagnostics={
                "native_event_summary": [{"sequence": 1, "type": "agent_settled"}]
            },
        )
        return run

    def test_recovery_preserves_original_and_future_restore_uses_real_new_hashes(self):
        from asterion.applications.prime.p7.solutions import (
            load_exact_prefix,
            source_experiment,
        )
        from asterion.applications.prime.p7.operator import _apply_saved_prefix
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from tools.recover_prime_p7_trace_race import recover_animation_replay
        from asterion.applications.prime.p7.official_replay import execute_saved_prefix

        with (
            tempfile.TemporaryDirectory() as directory,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            root = Path(directory)
            arc = fixtures.TestRecoverPrimeP7TraceRace._arc_root(root)
            _Animated.noise = 2
            source = self._source(root)
            original = {
                str(p.relative_to(source)): p.read_bytes()
                for p in source.rglob("*")
                if p.is_file()
            }
            _Animated.noise = 3

            def factory(recordings_dir, game, **_):
                return _Animated(recordings_dir=recordings_dir, game=game)

            with (
                patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=factory,
                ),
                patch(
                    "asterion.applications.prime.p7.solutions._fresh_engine",
                    side_effect=lambda a, g, r: factory(r, g),
                ),
            ):
                recovered = recover_animation_replay(
                    operator_root=root, arc_root=arc, source_run_id=source.name
                )
                _Animated.noise = 4
                prefix = load_exact_prefix(
                    arc, recovered.parent, recovered.name, "ls20-9607627b", 0
                )
                self.assertIsNotNone(prefix)
                summary = json.loads((recovered / "summary.json").read_text())
                self.assertEqual(
                    source_experiment(recovered, summary)["prediction_variant"],
                    "verified",
                )
                self.assertNotEqual(
                    summary["broker"]["replay_sha256"],
                    json.loads(original["summary.json"])["broker"]["replay_sha256"],
                )
                self.assertEqual(
                    summary["diagnostics"]["source_receipt"],
                    json.loads(original["summary.json"])["receipt"],
                )
                game = P7GameSelection("ls20-9607627b", 0, 3)
                broker = ArcBroker(engine=factory(root / "next", game), game=game)
                broker.bind_history("next")
                (root / "trace-next").mkdir()
                recorder = PrimeTraceRecorder(root / "trace-next")
                _apply_saved_prefix(
                    broker,
                    recorder,
                    prefix.transitions,
                    observations=prefix.observations,
                )
                self.assertEqual(broker.status().levels_completed, 2)
                self.assertNotEqual(broker.journal, prefix.transitions)
                self.assertEqual(
                    tuple((x.action, x.data) for x in broker.journal),
                    tuple((x.action, x.data) for x in prefix.transitions),
                )
                recorder.close()
                engine = factory(root / "official", game)
                engine.win_levels = 7
                # This is an in-memory SDK substitute, never a network submission.
                execute_saved_prefix(engine, prefix)
                self.assertEqual(
                    original,
                    {
                        str(p.relative_to(source)): p.read_bytes()
                        for p in source.rglob("*")
                        if p.is_file()
                    },
                )
                (source / "summary.json").write_text(
                    original["summary.json"].decode() + " "
                )
                self.assertIsNone(source_experiment(recovered, summary))

    def test_invalid_native_source_is_rejected_without_output(self):
        from asterion.applications.prime.p7.animation_replay import native_evidence

        for mutation in ("receipt", "normal_settlement", "recording", "seal"):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                root = Path(directory)
                source = self._source(root)
                summary = json.loads((source / "summary.json").read_text())
                if mutation == "receipt":
                    summary["receipt"] = {}
                elif mutation == "normal_settlement":
                    summary["diagnostics"]["native_event_summary"] = []
                elif mutation == "recording":
                    path = next((source / "recordings").glob("*/*.jsonl"))
                    rows = path.read_text().splitlines()
                    row = json.loads(rows[-1])
                    row["data"]["frame"][-1][0][0] = 9
                    rows[-1] = json.dumps(row)
                    path.write_text("\n".join(rows) + "\n")
                elif mutation == "seal":
                    (source / "trace/prime-trace.seal.json").write_text("{}")
                (source / "summary.json").write_text(json.dumps(summary))
                with self.assertRaises((ValueError, KeyError)):
                    native_evidence(source)
