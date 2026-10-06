"""Offline recovery of one replay-verified P7 trace append race."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


class _RecordingEngine:
    game_id = "ls20-9607627b"
    seed = 0

    def __init__(self, *, recordings_dir: Path, game: object) -> None:
        self.calls = 0
        self._path = recordings_dir / "session" / "ls20.jsonl"
        self._path.parent.mkdir(parents=True)
        self._write("RESET")
        self._write("RESET")

    def _observation(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1", "ACTION6"],
            "frame": [[[self.calls]]],
            "levels_completed": self.calls // 2,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def _write(self, action: str, data: dict[str, int] | None = None) -> None:
        row = {
            "data": {
                "action_input": {"data": data or {}, "id": action},
                "available_actions": ["ACTION1", "ACTION6"],
                "frame": [[[self.calls]]],
                "full_reset": False,
                "game_id": self.game_id,
                "guid": self._path.parent.name,
                "levels_completed": self.calls // 2,
                "state": "NOT_FINISHED",
                "win_levels": 7,
            }
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    def observe(self) -> dict[str, object]:
        return self._observation()

    def step(
        self, action: str, data: dict[str, int] | None = None
    ) -> dict[str, object]:
        if action != "RESET":
            self.calls += 1
        self._write(action, data)
        return self._observation()

    def close(self) -> None:
        pass


class TestRecoverPrimeP7TraceRace(unittest.TestCase):
    def test_materializes_new_sealed_prefix_without_changing_source(self) -> None:
        from asterion.applications.prime.p7.solutions import load_best_prefix
        from tools.list_prime_p7_games import inventory
        from tools.recover_prime_p7_trace_race import recover_trace_race

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            source = self._race_source(root)
            source_snapshot = {
                path.relative_to(source): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            }
            source_model = json.loads(
                (source / "trace" / "prime-trace.jsonl").read_text().splitlines()[0]
            )["identities"]["model_id"]
            with (
                # Clean Make exports unset operator settings as empty strings.
                # This fixture supplies the valid selection its source used.
                mock.patch.dict("os.environ", {
                    "ASTERION_PRIME_PROVIDER": "openai-codex",
                    "ASTERION_PRIME_MODEL": source_model,
                }),
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.safe_run_id",
                    return_value="p7-live-20260925080000-0123456789abcdef01234567",
                ),
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=lambda recordings_dir, game, **_: _RecordingEngine(
                        recordings_dir=recordings_dir, game=game
                    ),
                ),
                mock.patch(
                    "asterion.applications.prime.p7.solutions._fresh_engine",
                    side_effect=lambda _arc, game, recordings: _RecordingEngine(
                        recordings_dir=recordings, game=game
                    ),
                ),
            ):
                recovered = recover_trace_race(
                    operator_root=root,
                    arc_root=arc_root,
                    source_run_id=source.name,
                )
                prefix = load_best_prefix(
                    arc_root,
                    root / ".asterion-private" / "prime-p7-live",
                    "ls20-9607627b",
                    0,
                )

            self.assertNotEqual(recovered, source)
            self.assertEqual(
                source_snapshot,
                {
                    path.relative_to(source): path.read_bytes()
                    for path in source.rglob("*")
                    if path.is_file()
                },
            )
            self.assertIsNotNone(prefix)
            assert prefix is not None
            self.assertEqual(prefix.source_run_id, recovered.name)
            self.assertEqual((prefix.levels_completed, len(prefix.transitions)), (1, 2))
            summary = json.loads((recovered / "summary.json").read_text())
            self.assertTrue(summary["sealed_trace"])
            self.assertTrue(summary["replay_verified"])
            self.assertEqual(summary["diagnostics"]["recovered_from"], source.name)
            trace = (recovered / "trace" / "prime-trace.jsonl").read_text()
            self.assertIn('"kind":"arc.recovery.source"', trace)
            self.assertNotIn('"kind":"arc.usage.reported"', trace)
            row = next(
                value
                for value in inventory(
                    arc_root, root / ".asterion-private" / "prime-p7-live"
                )
                if value["game_id"] == "ls20-9607627b"
            )
            self.assertEqual(row["completed_levels"], 1)
            self.assertEqual(row["run_id"], recovered.name)

    def test_rejects_a_second_chain_break_before_creating_output(self) -> None:
        from tools.recover_prime_p7_trace_race import RecoveryError, recover_trace_race

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            source = self._race_source(root)
            trace = source / "trace" / "prime-trace.jsonl"
            rows = trace.read_text().splitlines()
            rows.insert(1, rows[0])
            trace.write_text("\n".join(rows) + "\n")

            with (
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=lambda recordings_dir, game, **_: _RecordingEngine(
                        recordings_dir=recordings_dir, game=game
                    ),
                ),
                self.assertRaisesRegex(RecoveryError, "recovery source is unavailable"),
            ):
                recover_trace_race(
                    operator_root=root,
                    arc_root=arc_root,
                    source_run_id=source.name,
                )

            runs = root / ".asterion-private" / "prime-p7-live"
            self.assertEqual(tuple(runs.iterdir()), (source,))

    def test_rejects_a_symlinked_private_evidence_ancestor(self) -> None:
        from tools.recover_prime_p7_trace_race import RecoveryError, recover_trace_race

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arc_root = self._arc_root(root)
            source = self._race_source(root)
            private = root / ".asterion-private"
            relocated = root / "relocated-private"
            private.rename(relocated)
            private.symlink_to(relocated, target_is_directory=True)

            with (
                mock.patch(
                    "tools.recover_prime_p7_trace_race.live.ArcadeEngine",
                    side_effect=lambda recordings_dir, game, **_: _RecordingEngine(
                        recordings_dir=recordings_dir, game=game
                    ),
                ),
                self.assertRaisesRegex(RecoveryError, "recovery source is unavailable"),
            ):
                recover_trace_race(
                    operator_root=root,
                    arc_root=arc_root,
                    source_run_id=source.name,
                )

    @staticmethod
    def _arc_root(root: Path) -> Path:
        game = root / "arc" / "environment_files" / "ls20" / "9607627b"
        game.mkdir(parents=True)
        (game / "ls20.py").write_text("# fixture\n")
        (game / "metadata.json").write_text(
            json.dumps(
                {
                    "baseline_actions": [22, 123, 73, 84, 96, 192, 186],
                    "game_id": "ls20-9607627b",
                    "win_levels": 7,
                }
            )
        )
        return root / "arc"

    @staticmethod
    def _race_source(root: Path) -> Path:
        from asterion.agents.prime.trace import _entry_digest
        from tests.test_prime_p7_solutions import TestP7SavedSolutions

        run = (
            root
            / ".asterion-private"
            / "prime-p7-live"
            / "p7-live-20260924230447-46fc1ea55b4041a6f56f8786"
        )
        TestP7SavedSolutions._write_run(run)
        summary_path = run / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary.update(
            {
                "completed_prefix": None,
                "failure": {"message": "trace is unavailable", "type": "PrimeTraceError"},
                "replay_verified": True,
                "sealed_trace": False,
            }
        )
        summary_path.write_text(json.dumps(summary, sort_keys=True))
        primary_recording = next((run / "recordings").glob("*/*.jsonl"))
        recording_rows = [
            json.loads(row) for row in primary_recording.read_text().splitlines()
        ]
        for row in recording_rows:
            row["data"]["action_input"]["reasoning"] = None
        primary_recording.write_text(
            "\n".join(json.dumps(row) for row in recording_rows) + "\n"
        )
        for name in ("replay-recordings", "prefix-replay-recordings"):
            target = run / name / "session"
            target.mkdir(parents=True)
            target.joinpath("ls20.jsonl").write_bytes(
                primary_recording.read_bytes()
            )

        trace_path = run / "trace" / "prime-trace.jsonl"
        original = [json.loads(row) for row in trace_path.read_text().splitlines()]
        first, second, completed, sealed = original
        orphan = {
            "identities": second["identities"],
            "kind": "arc.usage.reported",
            "payload": {"input_tokens": 7, "output_tokens": 3},
            "previous_sha256": first["sha256"],
            "sequence": 2,
        }
        orphan["sha256"] = _entry_digest(
            orphan["sequence"],
            orphan["kind"],
            orphan["identities"],
            orphan["payload"],
            orphan["previous_sha256"],
        )
        completed["sequence"] = 4
        completed["previous_sha256"] = second["sha256"]
        completed["sha256"] = _entry_digest(
            completed["sequence"],
            completed["kind"],
            completed["identities"],
            completed["payload"],
            completed["previous_sha256"],
        )
        sealed["sequence"] = 5
        sealed["previous_sha256"] = completed["sha256"]
        sealed["payload"] = {
            "entry_count": 4,
            "final_sha256": completed["sha256"],
        }
        sealed["sha256"] = _entry_digest(
            sealed["sequence"],
            sealed["kind"],
            sealed["identities"],
            sealed["payload"],
            sealed["previous_sha256"],
        )
        rows = [first, orphan, second, completed, sealed]
        trace_path.write_text(
            "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
            + "\n"
        )
        (run / "trace" / "prime-trace.seal.json").write_text(
            json.dumps(
                {
                    "entry_count": len(rows),
                    "final_sha256": sealed["sha256"],
                    "sealed_at": "2026-09-24T23:09:39+00:00",
                },
                sort_keys=True,
            )
        )
        return run


class TestTerminalRecoveryAnimationAdmission(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def _source(self, root: Path) -> Path:
        from tests.test_prime_p7_terminal_recovery import TestTerminalWinRecovery, _WinningEngine
        class AnimatedEngine(_WinningEngine):
            def _observation(self):
                value = super()._observation()
                value['frame'] = [[[91]], *value['frame']]
                return value
        with mock.patch('tests.test_prime_p7_terminal_recovery._WinningEngine', AnimatedEngine):
            source = TestTerminalWinRecovery()._source(root, seal=True)
        path = next((source / 'replay-recordings').glob('*/*.jsonl'))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[3]['data']['frame'][0][0][0] = 92
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return source

    def test_terminal_admission_authenticates_full_original_but_allows_only_intermediate_pixels_without_sdk(self):
        from tools.recover_prime_p7_trace_race import _terminal_candidate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            arc = TestRecoverPrimeP7TraceRace._arc_root(root)
            source = self._source(root)
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            with mock.patch('tools.recover_prime_p7_trace_race.live.ArcadeEngine', side_effect=AssertionError('admission must be static')) as sdk:
                candidate = _terminal_candidate(root, arc, source.name)
            sdk.assert_not_called()
            self.assertEqual(len(candidate.transitions), 14)
            self.assertEqual(len(candidate.observations), 15)
            self.assertEqual(candidate.observations[2].frame[0], ((91,),))
            self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_terminal_recovery_uses_two_fresh_passes_certifies_new_source_and_only_rejects_original_inventory(self):
        from asterion.applications.prime.p7 import solution_certificates as cert, solutions
        from tests.test_prime_p7_solution_certificates import TestP7SolutionCertificates
        from tests.test_prime_p7_terminal_recovery import _WinningEngine
        from tools.recover_prime_p7_trace_race import _register_terminal_rejection, _terminal_candidate, recover_terminal_win
        class NewAnimation(_WinningEngine):
            def _observation(self):
                value = super()._observation()
                value['frame'] = [[[93]], *value['frame']]
                return value
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(cert, '_sdk_identity', return_value={'fixture-sdk': 'a' * 64}):
            root = Path(directory).resolve()
            arc = TestRecoverPrimeP7TraceRace._arc_root(root)
            baseline = TestP7SolutionCertificates()
            baseline.root, baseline.arc, baseline.runs = root, arc, root / '.asterion-private' / 'prime-p7-live'
            baseline.game, baseline.model = 'ls20-9607627b', 'gpt-6.1-sol'
            baseline.catalog = ({'game_id': baseline.game, 'win_levels': 7, 'baseline_actions': (22, 123, 73, 84, 96, 192, 186)},)
            prior = baseline.save('p7-prior')
            baseline.certify(prior)
            pointer_path = cert._pointer(baseline.runs / 'solution-certificates', baseline.game, baseline.model)
            old_pointer = json.loads(pointer_path.read_text())
            old_certificate = baseline.runs / 'solution-certificates' / 'revisions' / (old_pointer['winner']['certificate'] + '.json')
            old_bytes = old_certificate.read_bytes()
            source = self._source(root)
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            with mock.patch('tools.recover_prime_p7_trace_race.live.ArcadeEngine', side_effect=lambda recordings_dir, game, **_: NewAnimation(recordings_dir=recordings_dir, game=game)) as sdk:
                recovered = recover_terminal_win(operator_root=root, arc_root=arc, source_run_id=source.name)
            self.assertEqual(sdk.call_count, 2, 'one new-source replay plus one independent save witness')
            summary = json.loads((recovered / 'summary.json').read_text())
            self.assertNotEqual(summary['broker']['replay_sha256'], json.loads((source / 'summary.json').read_text())['broker']['replay_sha256'])
            self.assertIsNotNone(solutions.source_experiment(recovered, summary))
            self.assertEqual(json.loads((recovered / 'solution-certification-status.json').read_text())['status'], 'ready')
            pointer = json.loads(pointer_path.read_text())
            self.assertEqual(pointer['winner']['source_run_id'], recovered.name)
            self.assertNotIn(source.name, pointer['eligible_sources'])
            self.assertEqual(set(pointer['rejected_sources']), {source.name})
            self.assertEqual(old_certificate.read_bytes(), old_bytes)
            self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            with mock.patch.object(solutions, '_fresh_engine', side_effect=AssertionError('static reader cannot execute SDK')):
                selected = cert.read_certified_roster(arc, recovered.parent, baseline.catalog, expected_model_id=baseline.model)
            self.assertEqual(selected[0].source_run_id, recovered.name)
            candidate = _terminal_candidate(root, arc, source.name)
            prefix, receipt, _ = solutions._read_one(arc, recovered, baseline.game, 0, None, baseline.model, strict_model=True)
            witness = cert._ReplayWitness(prefix.transitions, receipt, prefix.observations, cert.capture_verification_identity(arc, baseline.game))
            preserved_pointer = pointer_path.read_bytes()
            baseline.save('p7-unrelated-new-source')
            with self.assertRaisesRegex(ValueError, 'unrelated changes'):
                _register_terminal_rejection(arc, recovered, candidate, witness)
            self.assertEqual(pointer_path.read_bytes(), preserved_pointer)
            original_summary = source / 'summary.json'
            original_summary.write_bytes(original_summary.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                _register_terminal_rejection(arc, recovered, candidate, witness)
            self.assertEqual(pointer_path.read_bytes(), preserved_pointer)

    def test_terminal_admission_rejects_changed_settled_state_metadata_dimensions_or_original_digest(self):
        from tools.recover_prime_p7_trace_race import _terminal_candidate
        for mutation in ('settled', 'state', 'levels', 'available', 'dimensions', 'action', 'original-digest'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                arc = TestRecoverPrimeP7TraceRace._arc_root(root)
                source = self._source(root)
                group = 'recordings' if mutation == 'original-digest' else 'replay-recordings'
                path = next((source / group).glob('*/*.jsonl'))
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                row = rows[3]['data']
                if mutation == 'settled':
                    row['frame'][-1][0][0] += 1
                elif mutation == 'state':
                    row['state'] = 'WIN'
                elif mutation == 'levels':
                    row['levels_completed'] += 1
                elif mutation == 'available':
                    row['available_actions'] = ['ACTION1']
                elif mutation == 'dimensions':
                    for frame in row['frame']:
                        frame[0].append(92)
                elif mutation == 'action':
                    row['action_input']['id'] = 'ACTION6'
                else:
                    row['frame'][0][0][0] += 1
                path.write_text(''.join(json.dumps(value) + '\n' for value in rows))
                with mock.patch('tools.recover_prime_p7_trace_race.live.ArcadeEngine') as sdk, self.assertRaises(ValueError):
                    _terminal_candidate(root, arc, source.name)
                sdk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
