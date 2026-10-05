"""Console launch stays provider-free until the browser explicitly starts P7."""

import io
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from asterion.applications.prime.p7.console_export import main


class TestLiveConsoleCli(unittest.TestCase):
    def test_serve_routes_operator_configuration_without_export_or_model(self):
        serve = Mock(side_effect=lambda **kw: kw['on_ready']('http://127.0.0.1:12345/'))
        out, err = io.StringIO(), io.StringIO()
        fake = SimpleNamespace(serve_console=serve)
        with patch.dict(sys.modules, {'asterion.applications.prime.p7.console_server': fake}), patch(
            'asterion.applications.prime.p7.console_export.export_console'
        ) as export:
            self.assertEqual(main(['serve', '--operator-root', '/operator', '--arc-root', '/games',
                                   '--guest-machine', 'guest', '--no-browser'], stdout=out, stderr=err), 0)
        export.assert_not_called()
        self.assertEqual(serve.call_args.kwargs['operator_root'], Path('/operator'))
        self.assertEqual(serve.call_args.kwargs['arc_root'], Path('/games'))
        self.assertEqual(serve.call_args.kwargs['guest_machine'], 'guest')
        self.assertFalse(serve.call_args.kwargs['open_browser'])
        self.assertEqual(serve.call_args.kwargs['port'], 57515)
        self.assertIn('http://127.0.0.1:12345/', out.getvalue())
        self.assertEqual(err.getvalue(), '')

    def test_serve_failure_does_not_expose_private_detail(self):
        fake = SimpleNamespace(serve_console=Mock(side_effect=OSError('/private/secret-sentinel')))
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {'asterion.applications.prime.p7.console_server': fake}):
            self.assertEqual(main(['serve', '--no-browser'], stdout=out, stderr=err), 2)
        self.assertNotIn('secret-sentinel', out.getvalue() + err.getvalue())
        self.assertIn('服务', err.getvalue())

    def test_make_shortcut_launches_service_and_export_target_stays_offline(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            binary = scratch / 'uv'
            output = scratch / 'args.json'
            binary.write_text('#!' + sys.executable + '\nimport json, os, sys\n'
                              'open(os.environ["P7_TEST_ARGUMENTS"], "w").write(json.dumps(sys.argv[1:]))\n')
            binary.chmod(0o700)
            env = {**os.environ, 'PATH': str(scratch) + os.pathsep + os.environ['PATH'],
                   'P7_TEST_ARGUMENTS': str(output)}
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            for target, expected in (('p7-console', 'serve'), ('asterion-prime-p7-console', '--runs-root')):
                with self.subTest(target=target):
                    result = subprocess.run(['make', '-s', target, 'ASTERION_PRIME_NODE=',
                                             'ASTERION_PRIME_OPERATOR_ROOT=/operator space',
                                             f'P7_CONSOLE_PORT={port}',
                                             'PRIME_ORB_MACHINE=guest'], cwd=root, env=env,
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    args = json.loads(output.read_text())
                    if target == 'p7-console':
                        arc_root = root.parent / 'external-prime' / 'arc-agi-3'
                        self.assertEqual(args[:5], ['run', '--with', str(arc_root / 'wheels' / 'arc_agi-0.9.9-py3-none-any.whl'),
                                                  '--with', str(arc_root / 'wheels' / 'arcengine-0.9.3-py3-none-any.whl')])
                        self.assertEqual(args[5:8], ['asterion', 'arc-console', expected])
                        self.assertIn('/operator space', args)
                        self.assertIn('guest', args)
                    else:
                        self.assertEqual(args[:4], ['run', 'asterion', 'arc-console', expected])
                        self.assertNotIn('--with', args)
                        self.assertNotIn('serve', args)


if __name__ == '__main__':
    unittest.main()
