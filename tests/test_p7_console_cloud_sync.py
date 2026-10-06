"""Provider-free public HTTP capture boundaries."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.p7_console_cloud_sync import Capture, HTTPSource, UploadSchedule, SyncError, canonical


class TestConsoleCloudSync(unittest.TestCase):
    def fixture(self, count=65):
        revision, token, run = 'a' * 64, 'b' * 64, 'p7-live-test'
        summary = {'run_id': run, 'game_id': 'ab01-test', 'status': 'successful'}
        manifest = {'state': 'ready', 'run_id': run, 'revision': revision,
                    'run': summary, 'levels': [{'level': 1, 'frame_count': count,
                                               'action_count': 0}]}
        routes = {'/api/games': {'games': [{'game_id': 'ab01-test', 'win_levels': 1}]},
                  '/api/overview': {'games': [{'game_id': 'ab01-test', 'best_run_id': run}]},
                  '/api/state': {'snapshot': None},
                  '/api/preview/ab01-test': {'preview': True},
                  '/api/preview/ab01-test/1': {'preview': True},
                  f'/api/replay/{run}/manifest': manifest}
        prefix = f'/api/replay/{run}/levels/1/{revision}'
        routes[prefix] = {'run': summary, 'replay_revision': revision, 'levels': [
            {'level': 1, 'frame_count': count, 'frames': [], 'actions': [],
             'frame_page': {'start': 0, 'limit': 32, 'source_token': token}}]}
        for start in range(0, count, 32):
            routes[f'{prefix}/frames/{token}/{start}/32'] = {
                'run_id': run, 'level': 1, 'replay_revision': revision,
                'source_token': token, 'frame_count': count, 'start': start,
                'frames': [{'index': i, 'grid': [[i % 16]]}
                           for i in range(start, min(count, start + 32))]}
        return routes

    def test_all_pages_and_deterministic_objects_reused(self):
        routes = self.fixture()
        calls = []
        def fetch(route):
            calls.append(route)
            return routes[route]
        with tempfile.TemporaryDirectory() as directory:
            capture = Capture(Path(directory), fetch)
            first = capture.once()
            self.assertEqual(first['stats']['framePages'], 3)
            for entry in first['routes'].values():
                raw = gzip.decompress((Path(directory) / 'objects' / (entry['sha256'] + '.json.gz')).read_bytes())
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
                self.assertEqual(len(raw), entry['bytes'])
            calls.clear()
            second = capture.once()
            self.assertEqual(first['generation'], second['generation'])
            self.assertFalse(any('/frames/' in route for route in calls))
            self.assertFalse(any('/preview/' in route for route in calls))

    def test_stale_page_keeps_previous_index(self):
        routes = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            capture = Capture(Path(directory), routes.__getitem__)
            capture.once()
            before = (Path(directory) / 'index.json').read_bytes()
            capture.cache = None
            capture.completed.clear()
            page = next(key for key in routes if '/frames/' in key)
            routes[page]['source_token'] = 'c' * 64
            with self.assertRaises(SyncError):
                capture.once()
            self.assertEqual(before, (Path(directory) / 'index.json').read_bytes())

    def test_changing_manifest_does_not_publish(self):
        routes = self.fixture()
        seen = 0
        def fetch(route):
            nonlocal seen
            if route.endswith('/manifest'):
                seen += 1
                if seen > 1:
                    return {**routes[route], 'revision': 'c' * 64}
            return routes[route]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SyncError):
                Capture(Path(directory), fetch).once()
            self.assertFalse((Path(directory) / 'index.json').exists())

    def test_old_revision_urls_survive_new_capture(self):
        routes = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            capture = Capture(Path(directory), routes.__getitem__)
            first = capture.once()
            old_paths = {path for path in first['routes'] if '/levels/' in path}
            # The selected source can change without breaking an open old replay.
            routes['/api/overview'] = {'games': []}
            second = capture.once()
            self.assertTrue(old_paths <= second['routes'].keys())
            self.assertEqual(second['stats']['readyRuns'], 0)

    def test_source_rejects_external_hosts_and_embedded_credentials(self):
        for url in ('https://example.com', 'http://secret@localhost:57515',
                    'http://127.0.0.1:57515/private', 'http://127.0.0.1:57515?token=secret'):
            with self.subTest(url=url), self.assertRaises(SyncError):
                HTTPSource(url)

    def test_unavailable_current_attempt_does_not_replace_saved_replay(self):
        routes = self.fixture()
        routes['/api/overview']['games'][0]['active_run_id'] = 'p7-live-current'
        def fetch(route):
            if route == '/api/replay/p7-live-current/manifest':
                raise SyncError('source-unavailable')
            return routes[route]
        with tempfile.TemporaryDirectory() as directory:
            result = Capture(Path(directory), fetch).once()
            self.assertEqual(result['stats']['readyRuns'], 1)
            self.assertEqual(result['stats']['unavailableCurrentRuns'], ['p7-live-current'])
            self.assertNotIn('/api/replay/p7-live-current/manifest', result['routes'])

    def test_upload_coalesces_and_completion_obeys_minimum(self):
        schedule = UploadSchedule()
        self.assertTrue(schedule.due(0, 'saved1'))
        schedule.attempted(0, 'saved1')
        self.assertFalse(schedule.due(59, 'saved2'))
        self.assertTrue(schedule.due(60, 'saved2'))
        schedule.attempted(60, 'saved2')
        self.assertFalse(schedule.due(1859, 'saved2'))
        self.assertTrue(schedule.due(1860, 'saved2'))
        schedule.paused = True
        self.assertFalse(schedule.due(10000, 'saved3'))

    def test_generated_timestamp_only_does_not_change_generation(self):
        routes = self.fixture()
        routes['/api/overview']['generated_at'] = 'first'
        with tempfile.TemporaryDirectory() as directory:
            capture = Capture(Path(directory), routes.__getitem__)
            first = capture.once()
            routes['/api/overview']['generated_at'] = 'second'
            second = capture.once()
            self.assertEqual(first['generation'], second['generation'])

    def test_resume_history_is_not_captured_and_active_churn_is_not_saved_change(self):
        routes = self.fixture()
        game = routes['/api/overview']['games'][0]
        game['resume_run_id'] = 'p7-live-old-resume'
        overview_calls = 0
        def fetch(route):
            nonlocal overview_calls
            if route == '/api/overview':
                overview_calls += 1
                if overview_calls > 1:
                    return {'games': [{**game, 'active_run_id': 'p7-live-new-current'}]}
            self.assertNotIn('old-resume', route)
            return routes[route]
        with tempfile.TemporaryDirectory() as directory:
            result = Capture(Path(directory), fetch).once()
            self.assertEqual(result['stats']['readyRuns'], 1)

    def test_canonical_unicode(self):
        self.assertEqual(canonical({'b': 1, 'a': '图'}), '{"a":"图","b":1}'.encode())
