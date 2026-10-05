"""Saved routes compose at a checked level boundary without model execution."""
from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from asterion.applications.prime.p7.broker import ArcTransition
from tests.test_prime_p7_terminal_recovery import _WinningEngine


class _CompositionEngine(_WinningEngine):
    last_action = "RESET"

    def step(self, action, data=None):
        self.last_action = action
        return super().step(action, data)

    def _observation(self):
        value = super()._observation()
        if self.calls == 4:
            # Different level-completion animation, identical settled frame.
            value["frame"] = [[[6 if self.last_action == "ACTION6" else 1]], [[4]]]
        return value


class TestRouteComposition(unittest.TestCase):
    def setUp(self):
        from asterion.applications.prime.p7 import solutions
        self.assertTrue(callable(solutions.load_exact_prefix))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def _source(self, root, run_id, target):
        from asterion.agents.prime.trace import PrimeTraceRecorder
        from asterion.applications.prime.p7 import live
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.game import P7GameSelection
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt, trace_identities_for
        from asterion.applications.prime.p7.score import digest
        from tools.recover_prime_p7_trace_race import _receipt_mapping
        run = live.private_root(root, run_id)
        (run / "trace").mkdir()
        game = P7GameSelection("ls20-9607627b", 0, target)
        broker = ArcBroker(engine=_CompositionEngine(recordings_dir=run / "recordings", game=game), game=game)
        recorder = PrimeTraceRecorder(run / "trace")
        identities = trace_identities_for("gpt-6.1-sol")
        client = _P7BrokerClient(broker, recorder, identities, variant="legacy")
        for index in range(target * 2):
            client.act([{"name": "ACTION6", "data": {"x": 1, "y": 1}}] if target == 2 and index == 3
                       else [{"name": "ACTION1", "data": {}}])
        receipt = broker.seal()
        broker.replay(lambda: _CompositionEngine(recordings_dir=run / "replay-recordings", game=game))
        evidence = P7PrivateTraceReceipt(broker, recorder, identities)
        native = evidence.get_receipt(run_id=run_id, receipt_sha256=evidence.expected_receipt_sha256(run_id=run_id))
        live.write_summary(root, run, run_id=run_id, receipt=_receipt_mapping(native), broker_receipt=receipt,
                           game=game, replay_verified=True, sealed_trace=True, cleanup_complete=True,
                           comparison_report=None, reason=None, failure=None, diagnostics={},
                           experiment={"game_id": game.game_id, "seed": 0, "model": identities["model_id"],
                                       "target_level": target, "prediction_variant": "verified"})
        scope = {"game_id": game.game_id, "seed": 0, "win_levels": 7, "run_id": run_id, "attempt_id": run_id}
        snapshot = {"scope": scope, "worldmap": {"description_zh": "原始研究", "state_summary": "研究状态",
                                                "rules": [], "unknowns": [], "competing_hypotheses": []}}
        revision = digest(snapshot)
        workspace = run / "research" / digest(scope)[7:]
        (workspace / "revisions").mkdir(parents=True)
        (workspace / "current.json").write_text(json.dumps({"scope": scope, "revision": revision}))
        (workspace / "revisions" / (revision[7:] + ".json")).write_text(json.dumps(snapshot))
        return run

    def test_materializes_full_sdk_replay_with_two_pinned_sources(self):
        from tools.recover_prime_p7_trace_race import compose_saved_route
        from asterion.applications.prime.p7.route_composition import composition_sources
        from asterion.applications.prime.p7.solutions import load_exact_prefix, source_experiment, load_resume_worldmap
        from asterion.applications.prime.p7.official_operator import _load_current_roster_prefixes
        from asterion.applications.prime.p7.console_overview import ConsoleOverview
        from tests.test_recover_prime_p7_trace_race import TestRecoverPrimeP7TraceRace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = TestRecoverPrimeP7TraceRace._arc_root(root)
            first = self._source(root, "p7-live-20261006120000-000000000000000000000001", 2)
            last = self._source(root, "p7-live-20261006110000-000000000000000000000002", 7)
            before = {p: p.read_bytes() for run in (first, last) for p in run.rglob("*") if p.is_file()}
            with (mock.patch("tools.recover_prime_p7_trace_race.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: _CompositionEngine(recordings_dir=recordings_dir, game=game)),
                  mock.patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=lambda _arc, game, recordings: _CompositionEngine(recordings_dir=recordings, game=game))):
                run = compose_saved_route(operator_root=root, arc_root=arc, source_run_id=first.name,
                                          suffix_run_id=last.name, through_level=2)
                summary = json.loads((run / "summary.json").read_text())
                self.assertEqual(len(composition_sources(run, summary)), 2)
                prefix = load_exact_prefix(arc, run.parent, run.name, "ls20-9607627b", 0, expected_model_id="gpt-6.1-sol")
                self.assertEqual(prefix.levels_completed, 7)
                self.assertEqual(summary["diagnostics"]["model_call_count"], 0)
                seam = summary["diagnostics"]["composition_seam"]
                self.assertNotEqual(seam["prefix_after_sha256"], seam["suffix_before_sha256"])
                self.assertEqual(source_experiment(run, summary)["target_level"], 2)
                self.assertEqual(load_resume_worldmap(run, prefix)["source_run_id"], last.name)
                catalog = ({"game_id": "ls20-9607627b", "win_levels": 7, "baseline_actions": [22, 123, 73, 84, 96, 192, 186]},)
                row = ConsoleOverview(run.parent, catalog)._read_run(run, {catalog[0]["game_id"]: catalog[0]})
                self.assertEqual(row["status"], "completed")
                self.assertEqual(row["route_sources"][1]["source_start_sequence"], 5)
                # Existing equal-score native source can win the tie; the new
                # composed candidate must pass all admission checks regardless.
                self.assertEqual(len(_load_current_roster_prefixes(arc, run.parent, catalog)), 1)
                self.assertFalse((run / "research").exists())
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                for mutation in ("segment", "seam", "model", "mode", "source"):
                    with self.subTest(mutation=mutation):
                        altered = json.loads(json.dumps(summary))
                        if mutation == "segment":
                            altered["diagnostics"]["route_sources"][1]["destination_start_sequence"] += 1
                        elif mutation == "seam":
                            altered["diagnostics"]["composition_seam"]["settled_sha256"] = "sha256:" + "0" * 64
                        elif mutation == "model":
                            altered["experiment"]["model"] = "other-model"
                        elif mutation == "mode":
                            altered["experiment"]["prediction_variant"] = "verified"
                        else:
                            path = first / "summary.json"
                            path.write_bytes(before[path] + b" ")
                        self.assertIsNone(composition_sources(run, altered))
                        self.assertIsNone(source_experiment(run, altered))
                        if mutation == "source":
                            (first / "summary.json").write_bytes(before[first / "summary.json"])

    def test_reindexes_only_sequences_and_first_suffix_before(self):
        from asterion.applications.prime.p7.route_composition import compose_transitions
        prefix = (ArcTransition(1, "ACTION1", "initial", "new-boundary", 1),)
        suffix = (ArcTransition(4, "ACTION2", "old-boundary", "after", 1),
                  ArcTransition(5, "ACTION1", "after", "win", 2))
        self.assertEqual(compose_transitions(prefix, suffix), (
            *prefix, replace(suffix[0], sequence=2, before_sha256="new-boundary"),
            replace(suffix[1], sequence=3)))

    def test_suffix_sdk_divergence_never_publishes_success(self):
        from tools.recover_prime_p7_trace_race import compose_saved_route, RecoveryError
        from tests.test_recover_prime_p7_trace_race import TestRecoverPrimeP7TraceRace
        class Divergent(_CompositionEngine):
            def _observation(self):
                value = super()._observation()
                if self.calls == 5:
                    value["frame"] = [[[99]]]
                return value
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc = TestRecoverPrimeP7TraceRace._arc_root(root)
            first = self._source(root, "p7-live-20261006120000-000000000000000000000001", 2)
            last = self._source(root, "p7-live-20261006110000-000000000000000000000002", 7)
            with (mock.patch("tools.recover_prime_p7_trace_race.live.ArcadeEngine", side_effect=lambda recordings_dir, game, **_: Divergent(recordings_dir=recordings_dir, game=game)),
                  mock.patch("asterion.applications.prime.p7.solutions._fresh_engine", side_effect=lambda _arc, game, recordings: _CompositionEngine(recordings_dir=recordings, game=game))):
                with self.assertRaisesRegex(RecoveryError, "materialization failed"):
                    compose_saved_route(operator_root=root, arc_root=arc, source_run_id=first.name,
                                        suffix_run_id=last.name, through_level=2)
            for run in first.parent.iterdir():
                if run not in (first, last):
                    self.assertFalse((run / "summary.json").exists())
                    self.assertFalse((run / "trace/prime-trace.seal.json").exists())

    def test_rejects_gaps_after_the_seam(self):
        from asterion.applications.prime.p7.route_composition import compose_transitions
        prefix = (ArcTransition(1, "ACTION1", "initial", "boundary", 1),)
        suffix = (ArcTransition(4, "ACTION2", "boundary", "after", 1),
                  ArcTransition(5, "ACTION1", "different", "win", 2))
        with self.assertRaises(ValueError):
            compose_transitions(prefix, suffix)
