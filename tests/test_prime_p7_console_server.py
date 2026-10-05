from __future__ import annotations

import http.client
import json
import threading
import unittest

from asterion.applications.prime.p7.console_server import create_console_server
from tests.test_prime_p7_console_session import ConsoleSessionFixture
from tests.test_prime_p7_console_manual_session import FakeManualController


class TestPrimeP7ConsoleServer(ConsoleSessionFixture):
    def setUp(self):
        super().setUp()
        self.manual = FakeManualController()
        self.session_ = self.session(manual_controller=self.manual)
        self.config = None
        def render(snapshot, *, live_config):
            self.config = live_config
            return '<!doctype html><title>console</title>'
        self.server = create_console_server(self.session_, renderer=render)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.host = f'127.0.0.1:{self.server.server_port}'
        self.origin = 'http://' + self.host

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def request(self, method, path, value=None, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        self.addCleanup(connection.close)
        body = json.dumps(value) if value is not None else None
        connection.request(method, path, body, {'Host': self.host, **headers})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def write(self, path, value, **changes):
        headers = {'Origin': self.origin, 'X-P7-Console-Token': self.server.token,
                   'Content-Type': 'application/json'}
        headers.update(changes)
        return self.request('POST', path, value, **headers)

    def test_page_catalog_state_are_provider_free_and_token_is_page_only(self):
        status, headers, _ = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertEqual(self.config['token'], self.server.token)
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        for path, key in (('/api/games', 'games'), ('/api/runs', 'runs'), ('/api/state', 'state')):
            status, _, body = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn(key, json.loads(body))
            self.assertNotIn(self.server.token.encode(), body)
        self.assertFalse(self.calls)

    def test_initial_preview_get_uses_catalog_members_and_redacts_failure_without_starting(self):
        calls = []
        def preview(root, game):
            calls.append(game['game_id'])
            return {'run': {'game_id': game['game_id'], 'status': 'preview', 'run_id': None},
                    'levels': [{'frames': [{'grid': [[9]]}], 'actions': []}]}
        self.session_._preview_reader = preview
        before = self.session_.view()
        status, _, raw = self.request('GET', '/api/preview/test-1')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['run']['status'], 'preview')
        self.assertEqual(self.request('GET', '/api/preview/test-1')[0], 200)
        self.assertEqual(calls, ['test-1'])
        self.assertEqual(self.session_.view(), before)
        self.assertFalse(self.calls)
        for path in ('/api/preview/unknown-test', '/api/preview/../test-1'):
            self.assertGreaterEqual(self.request('GET', path)[0], 400)
        self.assertEqual(calls, ['test-1'])
        self.session_._previews.clear()
        def fail(*_):
            raise ValueError('/private/sk-preview-secret')
        self.session_._preview_reader = fail
        status, _, raw = self.request('GET', '/api/preview/test-1')
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(raw), {'error': 'preview-unavailable'})
        self.assertNotIn(b'sk-preview-secret', raw)

    def test_write_requires_exact_host_origin_token_and_keys(self):
        valid = {'game_id': 'test-1', 'command_id': 'start'}
        for changes in ({'Origin': 'http://evil.test'}, {'Origin': ''},
                        {'X-P7-Console-Token': ''}, {'X-P7-Console-Token': 'é'},
                        {'Host': 'localhost:' + str(self.server.server_port)},
                        {'Content-Type': 'text/plain'}):
            with self.subTest(changes=changes):
                self.assertGreaterEqual(self.write('/api/start', valid, **changes)[0], 400)
        self.assertEqual(self.write('/api/start', {**valid, 'provider': 'secret'})[0], 400)
        self.assertFalse(self.calls)
        status, _, raw = self.write('/api/start', valid)
        self.assertEqual(status, 202)
        started = json.loads(raw)
        self.assertTrue(self.launched.wait(1))
        self.assertEqual(self.write('/api/stop', {'session_id': 'wrong', 'command_id': 'stop'})[0], 409)
        self.assertEqual(self.write('/api/stop', {'session_id': started['session_id'], 'command_id': 'stop'})[0], 202)

    def test_pause_resume_are_closed_authenticated_session_commands(self):
        import time
        from asterion.applications.prime.p7.solver_control import SolverControl
        status, _, raw = self.write('/api/start', {'game_id': 'test-1', 'command_id': 'start-control'})
        self.assertEqual(status, 202)
        started = json.loads(raw)
        self.wait_state(self.session_, 'running')
        root = self.session_._run_path(started['run_id'])
        root.mkdir(parents=True)
        control = SolverControl(root, started['run_id'], time.monotonic() + 30)
        for path, command in (('/api/pause', 'pause'), ('/api/resume', 'resume')):
            value = {'session_id': started['session_id'], 'command_id': command}
            self.assertEqual(self.write(path, value, Origin='http://evil.test')[0], 403)
            self.assertEqual(self.write(path, {**value, 'code': 'SENTINEL'})[0], 400)
            self.assertEqual(self.request('GET', path)[0], 404)
            self.assertEqual(self.write(path, {**value, 'session_id': 'wrong-session'})[0], 409)
            status, _, response = self.write(path, value)
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(response)['state'], 'pause_requested' if command == 'pause' else 'resume_requested')
            control.poll(0, 'sha256:' + 'a' * 64)
            self.wait_state(self.session_, 'paused' if command == 'pause' else 'running')
        self.assertEqual(self.manual.calls, [('close', None, None)])

    def test_private_paths_and_arbitrary_files_are_never_served(self):
        for path in ('/.env', '/api/replay/../.env', '/api/replay/%2e%2e', '/api/state?path=secret'):
            with self.subTest(path=path):
                status, headers, body = self.request('GET', path)
                self.assertEqual(status, 404)
                self.assertNotIn(str(self.root).encode(), body)
                self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_manual_open_action_close_require_write_protections_without_model(self):
        opened = {'game_id': 'test-1', 'command_id': 'open'}
        self.assertEqual(self.write('/api/manual/open', opened, Origin='http://evil.test')[0], 403)
        self.assertEqual(self.request('GET', '/api/manual/open')[0], 404)
        status, headers, body = self.write('/api/manual/open', opened)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['state'], 'ready')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        action = {'session_id': 'manual-1', 'command_id': 'action', 'observation_version': 1,
                  'action': 'ACTION1', 'data': {}}
        self.assertEqual(self.write('/api/manual/action', action)[0], 200)
        status, _, body = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertEqual(value['manual']['action_count'], 1)
        self.assertEqual(value['state'], 'idle')
        self.assertIsNone(value['run_id'])
        self.assertEqual(self.write('/api/manual/close', {'session_id': 'manual-1', 'command_id': 'close'})[0], 200)
        self.assertFalse(self.calls)
        self.write('/api/start', {'game_id': 'test-1', 'command_id': 'start'})
        status, _, body = self.write('/api/manual/open', {'game_id': 'test-1', 'command_id': 'open2'})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {'error': 'session-busy'})

    def test_manual_shapes_and_private_failures_are_rejected(self):
        action = {'session_id': 'manual-1', 'command_id': 'action', 'observation_version': 1,
                  'action': 'ACTION1', 'data': {}}
        for change in ({'observation_version': True}, {'observation_version': '1'},
                       {'observation_version': -1}, {'data': []}, {'provider': 'secret'}):
            with self.subTest(change=change):
                self.assertEqual(self.write('/api/manual/action', {**action, **change})[0], 400)
        self.assertEqual(self.write('/api/manual/open', {'game_id': 'test', 'command_id': 'open'})[0], 409)
        self.assertEqual(self.manual.calls, [])
        def fail(*args):
            raise RuntimeError('/private/secret-sentinel')
        self.manual.open = fail
        status, _, body = self.write('/api/manual/open', {'game_id': 'test-1', 'command_id': 'open'})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {'error': 'manual-unavailable'})
        self.assertEqual(self.session_.view()['revision'], 0)

    def test_manual_restart_requires_exact_current_identity_and_write_protections(self):
        self.write('/api/manual/open', {'game_id': 'test-1', 'command_id': 'open', 'level': 2})
        request = {'session_id': 'manual-1', 'command_id': 'restart', 'observation_version': 1}
        self.assertEqual(self.write('/api/manual/restart', request, Origin='http://evil.test')[0], 403)
        self.assertEqual(self.request('GET', '/api/manual/restart')[0], 404)
        status, _, body = self.write('/api/manual/restart', request)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['session_id'], 'manual-2')
        self.assertEqual(self.manual.calls[-1], ('restart', 'manual-1', 'restart', 1))
        for changes in ({'observation_version': True}, {'observation_version': -1},
                        {'observation_version': '1'}, {'game_id': 'test-1'}, {'level': 1},
                        {'action': 'RESET'}, {'data': {}}):
            with self.subTest(changes=changes):
                self.assertEqual(self.write('/api/manual/restart', {**request, **changes})[0], 400)
        state = self.session_.view()
        self.assertEqual(state['selection'], {'game_id': 'test-1', 'level': 2})
        self.assertEqual(state['state'], 'idle')
        self.assertIsNone(state['run_id'])
        self.assertFalse(self.calls)

    def test_manual_direct_level_uses_exact_shape_and_preserves_p7_state(self):
        request = {'game_id': 'test-1', 'command_id': 'level-two', 'level': 2}
        for level in (True, '2', None, 2.0):
            with self.subTest(level=level):
                self.assertEqual(self.write('/api/manual/open', {**request, 'level': level})[0], 400)
        for level in (0, 3):
            with self.subTest(level=level):
                status, _, body = self.write('/api/manual/open', {**request, 'level': level})
                self.assertEqual(status, 409)
                self.assertEqual(json.loads(body), {'error': 'level-unavailable'})
        self.assertEqual(self.write('/api/manual/open', {**request, 'extra': 1})[0], 400)
        self.assertFalse(self.manual.calls)
        status, _, body = self.write('/api/manual/open', request)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['level'], 2)
        status, _, body = self.request('GET', '/api/state')
        state = json.loads(body)
        self.assertEqual(state['selection'], {'game_id': 'test-1', 'level': 2})
        self.assertEqual(state['state'], 'idle')
        self.assertIsNone(state['run_id'])
        self.assertFalse(self.calls)

    def test_real_renderer_serves_only_same_origin_connections_and_hashed_assets(self):
        from asterion.applications.prime.p7.console_export import render_console
        self.server.renderer = render_console
        status, headers, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        self.assertIn("script-src 'sha256-", headers['Content-Security-Policy'])
        self.assertIn(self.server.token.encode(), body)
        self.assertNotIn(str(self.root).encode(), body)
        self.assertFalse(self.calls)


    def test_overview_is_read_only_fixed_scope_and_redacted(self):
        from unittest.mock import patch
        metadata = ({'game_id': 'test-1', 'alias': 'test', 'win_levels': 2,
                     'baseline_actions': (20, 20)},)
        with patch('asterion.applications.prime.p7.console_session._read_catalog', return_value=metadata):
            status, _, raw = self.request('GET', '/api/overview')
        self.assertEqual(status, 200)
        value = json.loads(raw)
        self.assertEqual(value['scope']['model_id'], 'gpt-6.1-sol')
        self.assertEqual(value['scope']['seed'], 0)
        self.assertEqual(value['totals']['total_games'], 1)
        self.assertEqual(value['totals']['score'], '0.000000')
        self.assertNotIn(self.server.token.encode(), raw)
        self.assertNotIn(str(self.root).encode(), raw)
        self.assertFalse(self.calls)

    def test_overview_missing_metadata_is_unavailable_without_changing_other_api(self):
        status, _, raw = self.request('GET', '/api/overview')
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(raw), {'error': 'overview-unavailable'})
        self.assertEqual(self.request('GET', '/api/games')[0], 200)
        self.assertEqual(self.request('GET', '/api/state')[0], 200)
        self.assertFalse(self.calls)

    def test_start_accepts_exact_optional_target_but_rejects_bad_types(self):
        valid = {'game_id': 'test-1', 'command_id': 'full-game', 'target_level': 2}
        for target in (True, '2', None, 2.0):
            with self.subTest(target=target):
                self.assertEqual(self.write('/api/start', {**valid, 'target_level': target})[0], 400)
        self.assertEqual(self.write('/api/start', {**valid, 'resume_run_id': '../bad'})[0], 409)
        self.assertFalse(self.calls)
        status, _, raw = self.write('/api/start', valid)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(raw)['target_level'], 2)
        self.assertTrue(self.launched.wait(1))
        self.assertIn('LEVEL=2', self.calls[0][0])


if __name__ == '__main__':
    unittest.main()
