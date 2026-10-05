"""Standalone HTML resource, escaping, and CLI delivery checks."""

import base64
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.console_export import export_console, main


class TestConsoleExport(unittest.TestCase):
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
            self.assertNotIn('fetch(', html)
            self.assertIn("tailwindcss", html.lower())
            self.assertIn("connect-src 'none'", html)
            # Hashes must cover actual inline bytes, including whitespace.
            for pattern in (r'<style>(.*?)</style>', r'<script>(.*?)</script>'):
                body = re.search(pattern, html, re.S)[1]
                digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
                self.assertIn("sha256-" + digest, html)

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
