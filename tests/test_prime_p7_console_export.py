"""Standalone HTML resource, escaping, and CLI delivery checks."""

import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.console_export import export_console, main, render_console


class TestConsoleExport(unittest.TestCase):
    def make_run(self, root, timestamp, suffix='a'):
        run = root / f'p7-live-{timestamp}-{suffix * 24}'
        run.mkdir()
        (run / 'summary.json').write_text(json.dumps({
            'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': run.name,
        }))
        recording = run / 'recordings' / 'session' / 'game.jsonl'
        recording.parent.mkdir(parents=True)
        recording.write_text('{}\n')
        return run

    def test_single_html_and_script_safe_data(self):
        sentinel = '</script><img src=x onerror="alert(1)">__CONSOLE_JS__'
        snapshot = {"schema": "asterion.arc-agi3-p7-console/v1", "run": {},
                    "levels": [], "warnings": [sentinel]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("asterion.applications.prime.p7.console_export.build_console_snapshot", return_value=snapshot):
                path = export_console(root)
            self.assertEqual(path, root / "p7-console.html")
            html = path.read_text()
            self.assertNotIn(sentinel, html)
            embedded = re.search(r'<script id="console-data" type="application/json">(.*?)</script>', html, re.S)
            self.assertIsNotNone(embedded)
            self.assertEqual(json.loads(embedded[1]), snapshot)
            self.assertNotRegex(html, r'<(?:script|link|img)[^>]+(?:src|href)="(?:https?:|assets/)')
            self.assertIn('console-config', html)
            self.assertIn("tailwindcss", html.lower())
            self.assertIn("connect-src 'none'", html)
            # Hashes must cover actual inline bytes, including whitespace.
            for pattern in (r'<style>(.*?)</style>', r'<script>(.*?)</script>'):
                body = re.search(pattern, html, re.S)[1]
                digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
                self.assertIn("sha256-" + digest, html)

    def test_live_config_uses_safe_json_and_same_origin_csp(self):
        config = {"token": "token</script>sentinel", "games": [
            {"game_id": "sp80-test", "alias": "SP80", "win_levels": 3}]}
        html = render_console({"schema": "asterion.arc-agi3-p7-console/v1", "run": {},
                               "levels": [], "warnings": []}, live_config=config)
        self.assertIn("connect-src 'self'", html)
        self.assertNotIn("token</script>sentinel", html)
        embedded = re.search(r'<script id="console-config" type="application/json">(.*?)</script>', html, re.S)
        self.assertEqual(json.loads(embedded[1]), config)
        digest = base64.b64encode(hashlib.sha256(embedded[1].encode()).digest()).decode()
        self.assertIn("sha256-" + digest, html)
        with self.assertRaises(ValueError):
            render_console({}, live_config={"token": "token", "root": "/private/path"})

    def test_cli_failure_is_public_safe(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("asterion.applications.prime.p7.console_export.export_console", side_effect=OSError('/private/credential-sentinel')):
            self.assertEqual(main(['/missing'], stdout=out, stderr=err), 2)
        self.assertNotIn('credential-sentinel', err.getvalue())
        self.assertIn('导出失败', err.getvalue())

    def test_cli_route(self):
        from asterion.applications.first_party_cli import main as cli
        with patch('asterion.applications.prime.p7.console_export.main', return_value=0) as invoke:
            self.assertEqual(cli(['arc-console', '/selected/run', '--output', '/tmp/example.html']), 0)
        self.assertEqual(invoke.call_args.args[0], ['/selected/run', '--output', '/tmp/example.html'])

    def test_latest_run_ignores_junk_incomplete_nested_and_symlink_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = self.make_run(root, '20261004090000')
            latest = self.make_run(root, '20261005090000')
            (root / 'notes.jsonl').write_text('{}')
            incomplete = root / ('p7-live-20261006100000-' + 'a' * 24)
            incomplete.mkdir()
            (incomplete / 'summary.json').write_text('{}')
            junk = self.make_run(root, '20261007100000')
            junk.rename(root / 'other-run')
            (root / ('p7-live-20261008100000-' + 'a' * 24)).symlink_to(older, target_is_directory=True)
            nested = root / 'nested'
            nested.mkdir()
            self.make_run(nested, '20261009100000')
            for index, part in enumerate(('summary.json', 'recordings', 'recordings/session', 'recordings/session/game.jsonl')):
                run = self.make_run(root, f'20261010{index:02d}0000')
                path = run / part
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                path.symlink_to(older / part, target_is_directory=(older / part).is_dir())
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(main(['--runs-root', str(root)], stdout=out, stderr=err), 0)
            self.assertTrue((latest / 'p7-console.html').is_file())
            self.assertFalse((older / 'p7-console.html').exists())
            self.assertEqual(err.getvalue(), '')

    def test_latest_corrupt_run_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = self.make_run(root, '20261004090000')
            latest = self.make_run(root, '20261005090000')
            (latest / 'summary.json').write_text('{"schema":"wrong","run_id":"private-sentinel"}')
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(main(['--runs-root', str(root)], stdout=out, stderr=err), 2)
            self.assertFalse((older / 'p7-console.html').exists())
            self.assertFalse((latest / 'p7-console.html').exists())
            self.assertNotIn('private-sentinel', err.getvalue())
            self.assertNotIn(str(root), err.getvalue())

    def test_missing_runs_have_friendly_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for selected in (root / 'private-missing-sentinel', root):
                with self.subTest(root_exists=selected.exists()):
                    out, err = io.StringIO(), io.StringIO()
                    self.assertEqual(main(['--runs-root', str(selected)], stdout=out, stderr=err), 2)
                    self.assertIn('没有找到', err.getvalue())
                    self.assertIn('录制', err.getvalue())
                    self.assertNotIn(str(selected), err.getvalue())

    def test_explicit_run_overrides_latest_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = self.make_run(root, '20261004090000')
            latest = self.make_run(root, '20261005090000')
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(main([str(selected), '--runs-root', str(root)], stdout=out, stderr=err), 0)
            self.assertTrue((selected / 'p7-console.html').is_file())
            self.assertFalse((latest / 'p7-console.html').exists())

    def test_browser_opens_exported_output_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = self.make_run(root, '20261005090000')
            output = root / 'chosen.html'
            out, err = io.StringIO(), io.StringIO()
            with patch('asterion.applications.prime.p7.console_export.webbrowser.open', return_value=True) as browser:
                self.assertEqual(main([str(selected)], stdout=out, stderr=err), 0)
                browser.assert_not_called()
                self.assertEqual(main([str(selected), '--output', str(output), '--open-browser'], stdout=out, stderr=err), 0)
            browser.assert_called_once_with(output.resolve().as_uri())
            self.assertTrue(output.is_file())
            self.assertEqual(err.getvalue(), '')

    def test_browser_failure_keeps_success_and_explains_manual_open(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = self.make_run(Path(directory), '20261005090000')
            for failure in (False, OSError('browser-private-sentinel')):
                with self.subTest(failure=type(failure).__name__):
                    out, err = io.StringIO(), io.StringIO()
                    kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                    with patch('asterion.applications.prime.p7.console_export.webbrowser.open', **kwargs):
                        self.assertEqual(main([str(selected), '--open-browser'], stdout=out, stderr=err), 0)
                    self.assertTrue((selected / 'p7-console.html').is_file())
                    self.assertIn('手动', err.getvalue())
                    self.assertIn('p7-console.html', err.getvalue())
                    self.assertNotIn('browser-private-sentinel', err.getvalue())

    def test_output_cannot_replace_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'summary.json'
            source.write_text('{}')
            with self.assertRaises(ValueError):
                export_console(root, source)
            self.assertEqual(source.read_text(), '{}')

    def test_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'original.html'
            target.write_text('untouched')
            link = root / 'p7-console.html'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                export_console(root, link)
            self.assertEqual(target.read_text(), 'untouched')
