from __future__ import annotations

import http.client
import json
import threading
import unittest

from asterion.applications.prime.p7.console_server import create_console_server
from tests.test_prime_p7_console_session import ConsoleSessionFixture


class TestPrimeP7ConsoleServer(ConsoleSessionFixture):
    def setUp(self):
        super().setUp()
        self.session_ = self.session()
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

    def test_private_paths_and_arbitrary_files_are_never_served(self):
        for path in ('/.env', '/api/replay/../.env', '/api/replay/%2e%2e', '/api/state?path=secret'):
            with self.subTest(path=path):
                status, headers, body = self.request('GET', path)
                self.assertEqual(status, 404)
                self.assertNotIn(str(self.root).encode(), body)
                self.assertNotIn('Access-Control-Allow-Origin', headers)

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


if __name__ == '__main__':
    unittest.main()
