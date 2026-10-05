"""Fixed replay publication follows verified route quality and source recency."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.console_export import export_console
from asterion.applications.prime.p7.private_trace import trace_identities_for
from asterion.applications.prime.p7.score import replay_sha256
from asterion.applications.prime.p7.solutions import _truncate


class TestFixedReplayPublication(unittest.TestCase):
    game_id = 'vc33-test'
    config = {'games': [{'game_id': game_id, 'alias': 'vc33', 'win_levels': 7,
                         'baseline_actions': [7, 18, 44, 61, 131, 34, 152]}]}

    def make_run(self, root, run_id, levels, actions, mtime, *, score='100.000000'):
        run = root / run_id
        (run / 'recordings' / 'session').mkdir(parents=True)
        (run / 'recordings' / 'session' / 'game.jsonl').write_text('{}\n')
        summary = {'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': run_id,
                   'sealed_trace': True, 'replay_verified': True, 'cleanup_complete': True,
                   'receipt': {'partial_game_score': score}}
        (run / 'summary.json').write_text(json.dumps(summary))
        os.utime(run / 'summary.json', ns=(mtime, mtime))
        snapshot = {'schema': 'asterion.arc-agi3-p7-console/v1', 'levels': [
            {'level': levels, 'receipt': {'partial_game_score': score}}], 'warnings': [],
            'run': {'run_id': run_id, 'game_id': self.game_id, 'seed': 0,
                    'win_levels': 7, 'completed_level_count': levels,
                    'primitive_action_count': actions, 'sealed_trace': True,
                    'replay_verified': True}}
        with patch('asterion.applications.prime.p7.console_export.build_console_snapshot', return_value=snapshot):
            export_console(run, replay_config=self.config)
        return run, snapshot

    def make_partial(self, root, run_id, level_counts, attempt_actions, mtime):
        run = root / run_id
        (run / 'trace').mkdir(parents=True)
        recorder = PrimeTraceRecorder(run / 'trace')
        identities = trace_identities_for('gpt-6.1-sol')
        transitions = []
        sequence = 0
        for level_number, count in enumerate(level_counts, 1):
            for _ in range(count):
                sequence += 1
                transition = ArcTransition(sequence, 'ACTION1', 'sha256:' + 'a' * 64,
                                           'sha256:' + 'b' * 64, level_number)
                transitions.append(transition)
                recorder.append('arc.action', identities, {'sequence': sequence,
                    'action': transition.action, 'before_sha256': transition.before_sha256,
                    'after_sha256': transition.after_sha256,
                    'levels_completed': transition.levels_completed})
        prefix_transitions = _truncate(tuple(transitions), len(level_counts))
        marker = {'game_id': self.game_id, 'seed': 0, 'win_levels': 7,
                  'levels_completed': len(level_counts), 'primitive_actions': len(prefix_transitions),
                  'terminal_reason': 'level-completed',
                  'replay_sha256': replay_sha256(prefix_transitions, terminal_reason='level-completed')}
        recorder.append('arc.run.partial', identities, marker)
        recorder.seal()
        recorder.close()
        (run / 'recordings' / 'session').mkdir(parents=True)
        (run / 'recordings' / 'session' / 'game.jsonl').write_text('{}\n')
        (run / 'summary.json').write_text(json.dumps({
            'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': run_id,
            'sealed_trace': True, 'replay_verified': True, 'cleanup_complete': True,
            'completed_prefix': marker, 'receipt': {}}))
        os.utime(run / 'summary.json', ns=(mtime, mtime))
        snapshot = {'schema': 'asterion.arc-agi3-p7-console/v1', 'levels': [], 'warnings': [],
            'run': {'run_id': run_id, 'game_id': self.game_id, 'seed': 0,
                    'win_levels': 7, 'completed_level_count': len(level_counts),
                    'primitive_action_count': attempt_actions, 'sealed_trace': True,
                    'replay_verified': True}}
        with patch('asterion.applications.prime.p7.console_export.build_console_snapshot', return_value=snapshot):
            export_console(run, replay_config=self.config)
        return snapshot

    @staticmethod
    def embedded_run(path):
        match = re.search(r'<script id="console-data" type="application/json">(.*?)</script>',
                          path.read_text(encoding='utf-8'), re.S)
        return json.loads(match[1])['run']

    def test_same_progress_prefers_shorter_route_and_latest_uses_summary_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, longer = self.make_run(root, 'p7-live-20261006025626-' + 'a' * 24, 7, 201, 1_000_000_000)
            _, shorter = self.make_run(root, 'p7-live-20261005194027-' + 'b' * 24, 7, 176, 2_000_000_000)
            replay = root / 'replays' / 'vc33.html'
            latest = root / 'p7-console.html'
            self.assertEqual(self.embedded_run(replay)['run_id'], shorter['run']['run_id'])
            self.assertEqual(self.embedded_run(latest)['run_id'], shorter['run']['run_id'])

    def test_same_progress_preserves_higher_score_before_shorter_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            older_id = 'p7-live-20261006025626-' + 'e' * 24
            newer_id = 'p7-live-20261005194027-' + 'f' * 24
            self.make_run(root, older_id, 7, 201, 1_000_000_000, score='100.000000')
            _, newer = self.make_run(root, newer_id, 7, 176, 2_000_000_000, score='99.000000')
            replay = self.embedded_run(root / 'replays' / 'vc33.html')
            latest = self.embedded_run(root / 'p7-console.html')
            self.assertEqual(replay['run_id'], older_id)
            self.assertEqual(latest['run_id'], newer['run']['run_id'])

    def test_reexport_of_same_source_refreshes_both_fixed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run_id = 'p7-live-20261006025626-' + '3' * 24
            run, first = self.make_run(root, run_id, 7, 176, 1_000_000_000)
            refreshed = {**first, 'warnings': ['updated evidence projection']}
            with patch('asterion.applications.prime.p7.console_export.build_console_snapshot', return_value=refreshed):
                export_console(run, replay_config=self.config)
            game = json.loads(re.search(r'<script id="console-data" type="application/json">(.*?)</script>',
                (root / 'replays' / 'vc33.html').read_text(), re.S)[1])
            latest = json.loads(re.search(r'<script id="console-data" type="application/json">(.*?)</script>',
                (root / 'p7-console.html').read_text(), re.S)[1])
            self.assertEqual(game['warnings'], ['updated evidence projection'])
            self.assertEqual(latest['warnings'], ['updated evidence projection'])

    def test_partial_prefix_does_not_replace_full_route_but_can_be_latest_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            full_id = 'p7-live-20261006025626-' + 'c' * 24
            partial_id = 'p7-live-20261005194027-' + 'd' * 24
            self.make_run(root, full_id, 7, 176, 1_000_000_000)
            self.make_partial(root, partial_id, (1, 1, 1, 1, 1, 1), 100, 2_000_000_000)
            self.assertEqual(self.embedded_run(root / 'replays' / 'vc33.html')['run_id'], full_id)
            self.assertEqual(self.embedded_run(root / 'p7-console.html')['run_id'], partial_id)

    def test_partial_route_rank_uses_valid_prefix_actions_not_unfinished_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old_id = 'p7-live-20261006025626-' + '1' * 24
            shorter_id = 'p7-live-20261005194027-' + '2' * 24
            # Both six-level prefixes score at the cap, while the later attempt
            # contains an unverified tail beyond its six-action saved prefix.
            self.make_partial(root, old_id, (2, 2, 1, 1, 1, 1), 8, 1_000_000_000)
            self.make_partial(root, shorter_id, (1, 1, 1, 1, 1, 1), 100, 2_000_000_000)
            selected = self.embedded_run(root / 'replays' / 'vc33.html')
            self.assertEqual(selected['run_id'], shorter_id)
            self.assertEqual(selected['primitive_action_count'], 100)
