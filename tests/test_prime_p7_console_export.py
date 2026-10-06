"""Standalone HTML resource, escaping, and CLI delivery checks."""

import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.console_export import export_console, main, render_console


class TestConsoleExport(unittest.TestCase):
    def test_single_html_contains_bound_inert_pages_for_complete_long_animation(self):
        from tests.test_prime_p7_console import TestPrimeP7Console
        fixture = TestPrimeP7Console()
        fixture.setUp()
        self.addCleanup(fixture.temporary.cleanup)
        fixture.write_recording([fixture.observation(), fixture.observation('ACTION5', color=4, layers=95)])
        output = export_console(fixture.root)
        html = output.read_text()
        snapshot = json.loads(re.search(r'<script id="console-data" type="application/json">(.*?)</script>', html, re.S)[1])
        self.assertTrue(snapshot['offline_frames'])
        self.assertRegex(snapshot['replay_revision'], r'^[0-9a-f]{64}$')
        pages = [json.loads(value) for value in re.findall(r'<script type="application/json" id="console-frame-page-1-\d+">(.*?)</script>', html, re.S)]
        self.assertEqual([page['start'] for page in pages], [0, 32, 64])
        self.assertEqual(sum(len(page['frames']) for page in pages), 96)
        self.assertEqual(pages[-1]['frames'][-1]['index'], 95)
        self.assertEqual(pages[-1]['frames'][-1]['grid'][0][0], 4)
        for page in pages:
            self.assertEqual(page['replay_revision'], snapshot['replay_revision'])
            self.assertEqual(page['source_token'], snapshot['levels'][0]['frame_page']['source_token'])
            self.assertLessEqual(len(page['frames']), 32)
        self.assertIn("connect-src 'none'", html)

    def test_replay_catalog_embeds_baselines_without_network_authority(self):
        config = {"games": [{"game_id": "vc33-test", "alias": "vc33", "win_levels": 1,
                              "baseline_actions": [7]}]}
        html = render_console({}, replay_config=config)
        embedded = re.search(r'<script id="console-config" type="application/json">(.*?)</script>', html, re.S)
        self.assertEqual(json.loads(embedded[1]), config)
        self.assertIn("connect-src 'none'", html)
        with tempfile.TemporaryDirectory() as directory:
            run = self.make_run(Path(directory), '20261006123456')
            path = export_console(run, replay_config=config)
            self.assertIn('"baseline_actions":[7]', path.read_text())

    def test_console_catalog_rejects_invalid_baselines_and_replay_authority(self):
        game = {"game_id": "vc33-test", "alias": "vc33", "win_levels": 1}
        for baseline in ([True], [0], [-1], [7, 8], "7"):
            with self.subTest(baseline=baseline):
                for kind in ('live_config', 'replay_config'):
                    config = {"games": [{**game, "baseline_actions": baseline}]}
                    if kind == 'live_config':
                        config['token'] = 'token'
                    with self.assertRaises(ValueError):
                        render_console({}, **{kind: config})
        with self.assertRaises(ValueError):
            render_console({}, replay_config={"token": "token", "games": [game]})
        with self.assertRaises(ValueError):
            render_console({}, live_config={"token": "token", "games": [game]},
                           replay_config={"games": [game]})
        html = render_console({}, live_config={"token": "token", "games": [game],
                                               "replay_loading": "level-manifest/v1"})
        self.assertIn('"replay_loading":"level-manifest/v1"', html)
        for mode in (None, True, "level-manifest/v2"):
            with self.subTest(replay_loading=mode), self.assertRaises(ValueError):
                render_console({}, live_config={"token": "token", "games": [game], "replay_loading": mode})

    def test_worldmap_render_uses_cursor_belief_and_labels_saved_planning_fallback(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is unavailable')
        from asterion.applications.prime.p7 import console_export
        app = Path(console_export.__file__).parent / 'console_assets' / 'app.js'
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const app = fs.readFileSync(process.argv[1], 'utf8');
const revision = (id, sequence, description) => ({scope:'observation', frame_id:id,
  source_action_sequence:sequence, cognition_revision:sequence, event_sequence:sequence,
  stable_description:description, cognition_narrative_zh:'模型修订', origin:'actor',
  provenance:{run_id:'source-run',event_sequence:sequence+10}});
const earlier = revision('f2', 2, '早期规划'), later = revision('f3', 3, '后期规划');
const level = {cognition_timeline:[earlier,later],cognition:later};
const state = {frameIndex:0,eventSequence:null};
const elements = new Map();
const element = () => ({children:[],append(...values){this.children.push(...values)},replaceChildren(){this.children=[]}});
const scopes = {};
const context = {state,run:{},currentLevel:()=>level,frames:()=>[{id:'f0'},{id:'f2'},{id:'f3'}],
  researchEvents:()=>[],array:x=>Array.isArray(x)?x:[],object:x=>x||{},
  number:x=>Number.isFinite(x)?x:0,string:(x,fallback='')=>typeof x==='string'?x:fallback,
  $:id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)},
  write:(id,value)=>{scopes[id]=value},node:(tag,text)=>({tag,text}),};
context.node=(tag,text)=>({...element(),tag,text});
vm.createContext(context);
vm.runInContext(app.slice(app.indexOf('  function observationCognition()'),app.indexOf('  function setEvent(')),context);
const text = entry => [entry.text||'',...(entry.children||[]).map(text)].join(' ');
context.renderWorld();
assert.match(scopes['cognition-scope'],/形成于第 3 步/);
assert.match(scopes['cognition-scope'],/仅作规划背景，不表示此帧当时已知/);
assert.match(scopes['cognition-scope'],/来源运行 source-run · 原事件 13/);
assert.match(text(elements.get('world-guide')),/后期规划/);
state.frameIndex=1;
context.renderWorld();
assert.match(scopes['cognition-scope'],/动作序号 2/);
assert.match(text(elements.get('world-guide')),/早期规划/);
assert.doesNotMatch(text(elements.get('world-guide')),/后期规划/);
assert.match(scopes['cognition-scope'],/不认证规则或授权动作/);
state.eventSequence=1;
context.renderWorld();
assert.match(scopes['cognition-scope'],/仅作规划背景，不表示此帧当时已知/);
'''
        completed = subprocess.run([node, '-e', script, str(app)], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_export_retains_exact_seed_for_saved_partial_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run = self.make_run(root, '20261006005914')
            for seed, expected in ((0, 0), (1, 1), (True, None), (-1, None)):
                with self.subTest(seed=seed):
                    (run / 'summary.json').write_text(json.dumps({
                        'schema': 'asterion.prime.p7-live-private-summary/v1',
                        'run_id': run.name, 'experiment': {'game_id': 'dc22-test', 'seed': seed}}))
                    path = export_console(run)
                    embedded = json.loads(re.search(
                        r'<script id="console-data" type="application/json">(.*?)</script>',
                        path.read_text(), re.S)[1])
                    self.assertEqual(embedded['run']['seed'], expected)

    def test_fixed_replays_keep_verified_progress_and_latest_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            def publish(timestamp, game, levels, verified=True, trace_verified=True):
                run = self.make_run(root, timestamp)
                (run / 'summary.json').write_text(json.dumps({
                    'run_id': run.name, 'sealed_trace': verified,
                    'replay_verified': verified, 'cleanup_complete': verified}))
                snapshot = {'schema': 'asterion.arc-agi3-p7-console/v1', 'levels': [],
                            'run': {'run_id': run.name, 'game_id': game,
                                    'completed_level_count': levels, 'sealed_trace': trace_verified,
                                    'replay_verified': True}, 'warnings': []}
                with patch('asterion.applications.prime.p7.console_export.build_console_snapshot', return_value=snapshot):
                    output = export_console(run)
                self.assertTrue(output.is_file())
                return snapshot
            four = publish('20261005010000', 'sp80-test', 4)
            publish('20261005020000', 'sp80-test', 5, verified=False)
            fixed = root / 'replays' / 'sp80.html'
            def embedded(path):
                return json.loads(re.search(
                    r'<script id="console-data" type="application/json">(.*?)</script>', path.read_text(), re.S)[1])
            self.assertEqual(embedded(fixed), four)
            publish('20261005025000', 'sp80-test', 5, trace_verified=False)
            self.assertEqual(embedded(fixed), four)
            other = publish('20261005030000', 'as66-test', 1)
            self.assertEqual(embedded(root / 'p7-console.html'), other)
            latest_by_summary_mtime = publish('20261005000000', 'sp80-test', 2)
            self.assertEqual(embedded(fixed), four)
            self.assertEqual(embedded(root / 'p7-console.html'), latest_by_summary_mtime)
            five = publish('20261005040000', 'sp80-test', 5)
            self.assertEqual(embedded(fixed), five)
            self.assertEqual(embedded(root / 'p7-console.html'), five)

    def test_replay_command_opens_fixed_file_without_game_or_model_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'replays').mkdir()
            fixed = root / 'replays' / 'sp80.html'
            fixed.write_text('saved')
            with patch('asterion.applications.prime.p7.console_export.webbrowser.open', return_value=True) as browser:
                self.assertEqual(main(['replay', '--runs-root', str(root), '--game', 'sp80'],
                                      stdout=io.StringIO(), stderr=io.StringIO()), 0)
                browser.assert_called_once_with(fixed.as_uri())
                browser.reset_mock()
                self.assertEqual(main(['replay', '--runs-root', str(root), '--game', '../sp80'],
                                      stdout=io.StringIO(), stderr=io.StringIO()), 2)
                browser.assert_not_called()

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
