"""Installed-wheel official gameplay smoke test with a deterministic game."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = "asterion/applications/prime/resources/ipython-extension.mjs"
GAMEPLAY_ASSEMBLY = "asterion/applications/prime/assemblies/prime-arc-agi-3-gameplay.json"


def _run(
    command: tuple[str, ...], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _official_fake_pi_source() -> str:
    """Drive installed public tools; computation and Solver remain production."""
    script = r'''
const tools = new Map();
const loader = await import(process.argv[1]);
await loader.default({registerTool(tool) { tools.set(tool.name, tool); }});
const names = [...tools.keys()].sort();
if (JSON.stringify(names) !== JSON.stringify(['ipython', 'p7_execute_plan', 'p7_workspace']))
  throw Error('default three-tool registration differs');
let counter = 0;
async function call(name, args) {
  const id = `installed-research-${++counter}`;
  console.log(JSON.stringify({type: 'tool_execution_start', toolCallId: id, toolName: name, args}));
  const result = await tools.get(name).execute(id, args);
  console.log(JSON.stringify({type: 'tool_execution_end', toolCallId: id, isError: !!result.isError, result}));
  if (result.isError) throw Error(`${name} failed: ${result.content[0]?.text}`);
  return JSON.parse(result.content[0].text);
}
const current = await call('p7_workspace', {op: 'read'});
const model = await call('ipython', {code:
  "import p7_research\n" +
  "assert p7_research.context()['observation_ref']['sequence'] == 0\n" +
  "def transition(count): return count + 1\n" +
  "prime_workspace.export('source', 'def transition(count): return count + 1')\n" +
  "prime_workspace.export('state', {'count': 0})\n"});
if (model.execution_status !== 'ok' || model.kernel_exports.length !== 2)
  throw Error('real kernel failed to export model');
const source = model.kernel_exports.find(ref => ref.name === 'source').export_id;
const state = model.kernel_exports.find(ref => ref.name === 'state').export_id;
const draft = {
  worldmap: {description_zh: '动作使计数增加，胜利条件待实测。', state_summary: '初始计数为零',
    rules: ['ACTION1 候选规律为计数加一'], unknowns: ['胜利条件尚未验证'], competing_hypotheses: []},
  task: {goal: '检验计数模型并到达目标', obstacles: [], question: '连续动作是否符合模型？',
    next_operation: 'execute', public_basis: '真实起点和候选程序'},
  model: {source_export_ids: [source], state_export_id: state, coverage: '单动作计数模型', assumptions: []},
  reports: [], evidence_sequences: [0], correction: {changed: [], retained: []}
};
// JSON literals here contain no Python-specific scalars; eval-free Python code
// loads actor data through json.loads and verifies the retained namespace.
const draftText = JSON.stringify(draft);
const exported = await call('ipython', {code:
  "import json\nassert transition(41) == 42\n" +
  "prime_workspace.export('draft', json.loads(" + JSON.stringify(draftText) + "))\n"});
const draftId = exported.kernel_exports[0].export_id;
const published = await call('p7_workspace', {
  op: 'publish', base_revision: current.workspace_revision, draft_export_id: draftId
});
if (published.status !== 'published' || published.workspace_revision === current.workspace_revision)
  throw Error('real workspace rejected publication');
const result = await call('p7_execute_plan', {
  plan_id: 'installed-plan', start: published.observation_ref,
  workspace_revision: published.workspace_revision, goal: '检验候选模型', purpose: 'advance', assumptions: [],
  steps: Array.from({length: 13}, (_, index) => ({action: {name: 'ACTION1', data: {}},
    expect: {cells: [{x: 0, y: 0, value: index + 1}]}}))
});
if (result.applied_count !== 13 || result.observation.levels_completed !== 1)
  throw Error('real actor plan did not complete');
'''
    return textwrap.dedent(r'''
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys

        SCRIPT = __SCRIPT__

        def emit(value):
            print(json.dumps(value, separators=(",", ":")), flush=True)

        def main():
            arguments = sys.argv[1:]
            loader = arguments[arguments.index("--extension") + 1]
            node = arguments[0]
            for raw in sys.stdin:
                request = json.loads(raw)
                if request.get("type") == "abort":
                    return 0
                if request.get("type") != "prompt":
                    continue
                emit({"id": request["id"], "success": True, "type": "response"})
                emit({"type": "agent_start"})
                emit({"type": "turn_start"})
                completed = subprocess.run(
                    (node, "--input-type=module", "--eval", SCRIPT, loader),
                    close_fds=True, env=dict(os.environ),
                    pass_fds=(int(os.environ["ASTERION_PRIME_IPYTHON_FD"]),
                              int(os.environ["ASTERION_PI_EXTENSION_SOURCE_FD"])),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    timeout=30,
                )
                events = [json.loads(line) for line in completed.stdout.splitlines()]
                for event in events:
                    emit(event)
                if completed.returncode:
                    sys.stderr.write(completed.stderr)
                    raise RuntimeError("installed research extension failed")
                Path("installed-tool-calls.json").write_text(json.dumps([
                    event["toolName"] for event in events
                    if event["type"] == "tool_execution_start"
                ]))
                for kind in ("turn_end", "agent_end", "agent_settled"):
                    emit({"type": kind})
                return 0
            return 1

        if __name__ == "__main__":
            raise SystemExit(main())
        ''').replace("__SCRIPT__", repr(script))


_RUNNER = textwrap.dedent(
    """
    import asyncio
    import json
    from importlib import resources
    from pathlib import Path
    import sys

    from asterion.applications.prime.p7.game import ArcGameContract
    from asterion.applications.prime.p7.official_operator import (
        OfficialInvocation,
        _resolve_gameplay_application,
        _run_game,
    )

    class Engine:
        game_id = "ab12-12345678"
        guid = "fixture-guid"
        seed = 0
        win_levels = 1

        def __init__(self, marker):
            self.actions = 0
            self.marker = marker

        def observe(self):
            return {
                "available_actions": ["ACTION1"],
                "frame": [[[self.actions]]],
                "levels_completed": int(self.actions >= 13),
                "state": "WIN" if self.actions >= 13 else "NOT_FINISHED",
                "win_levels": self.win_levels,
            }

        def step(self, action, data=None):
            assert action == "ACTION1"
            self.actions += 1
            return self.observe()

        def close(self):
            self.marker.write_text("closed", encoding="utf-8")

    async def main():
        root = Path.cwd()
        profile = root / "pi-profile"
        profile.mkdir(exist_ok=True)
        (profile / "auth.json").write_text(json.dumps({"deepseek": {"token": "fixture-only"}}))
        (profile / "models-store.json").write_text(json.dumps({"deepseek": {"models": [{"id": "deepseek-flash"}]}}))
        marker = root / "closed"
        evidence = root / "evidence"
        evidence.mkdir()
        extension = Path(str(resources.files("asterion.applications.prime").joinpath(
            "resources/ipython-extension.mjs"
        ))).resolve()
        invocation = OfficialInvocation(
            root,
            {
                "ASTERION_PRIME_PROVIDER": "deepseek",
                "ASTERION_PRIME_MODEL": "deepseek-flash",
                "ASTERION_PRIME_PI_AGENT_DIR": str(profile),
                "DEEPSEEK_API_KEY": "fixture-only",
            },
            (sys.executable, str(root / "fake_pi_rpc.py"), str(Path(sys.argv[1]).resolve())),
            extension,
            "arc-fixture-only",
        )
        engine = Engine(marker)
        await _run_game(
            invocation,
            _resolve_gameplay_application(),
            evidence,
            engine,
            ArcGameContract("ab12-12345678", win_levels=1),
            "official-fixture",
        )
        trace = evidence / "official-fixture" / "trace" / "prime-trace.jsonl"
        entries = [json.loads(line) for line in trace.read_text().splitlines()]
        terminal = next(row for row in entries if row["kind"] == "arc.run.completed")
        run_root = evidence / "official-fixture"
        current_paths = tuple((run_root / "research").glob("*/current.json"))
        assert len(current_paths) == 1
        model = json.loads(current_paths[0].read_text())
        revision = json.loads((current_paths[0].parent / "revisions" / (model["revision"][7:] + ".json")).read_text())
        assert revision["parent_revision"] is not None
        assert len(revision["model"]["source_export_ids"]) == 1
        assert revision["model"]["state_export_id"].startswith("sha256:")
        exports = list((run_root / "research-kernel" / "exports").glob("*.json"))
        print(json.dumps({
            "actions": engine.actions,
            "closed": marker.read_text(),
            "trace_entries": len(entries),
            "terminal": terminal["payload"]["terminal_reason"],
            "sealed": entries[-1]["kind"] == "trace.sealed",
            "tool_calls": json.loads((root / "installed-tool-calls.json").read_text()),
            "export_count": len(exports),
            "workspace_revision": model["revision"],
        }, sort_keys=True))

    asyncio.run(main())
    """
)


class TestPrimeP7OfficialInstalled(unittest.TestCase):
    def test_installed_official_gameplay_runs_and_seals_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-p7-official-installed-", dir="/tmp"
        ) as temporary:
            root = Path(temporary).resolve()
            dist = root / "dist"
            dist.mkdir()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            environment["UV_OFFLINE"] = "1"

            built = _run(
                ("uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel = next(dist.glob("asterion-*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                self.assertTrue(
                    {EXTENSION, GAMEPLAY_ASSEMBLY} <= set(archive.namelist())
                )

            virtual = root / "venv"
            created = _run(
                ("uv", "venv", "--seed", str(virtual)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            python = virtual / "bin" / "python"
            installed = _run(
                ("uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            node = shutil.which("node")
            self.assertIsNotNone(node)
            resource_dirs = tuple(
                (virtual / "lib").glob(
                    "python*/site-packages/asterion/runtimes/resources"
                )
            )
            self.assertEqual(len(resource_dirs), 1)
            loader_dir = resource_dirs[0]
            earendil_host = Path(
                "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent"
            )
            self.assertTrue(earendil_host.is_dir())
            link = loader_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
            link.parent.mkdir(parents=True)
            link.symlink_to(earendil_host)

            (root / "fake_pi_rpc.py").write_text(
                _official_fake_pi_source(), encoding="utf-8"
            )
            script = root / "run.py"
            script.write_text(_RUNNER, encoding="utf-8")
            result = _run(
                (str(python), "-I", str(script), str(Path(node).resolve())),
                cwd=root,
                environment={
                    **environment,
                    "ASTERION_TEST_FORBID_PRIME_SOURCE": "1",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence["actions"], 13)
            self.assertEqual(evidence["closed"], "closed")
            self.assertEqual(evidence["terminal"], "game-won")
            self.assertTrue(evidence["sealed"])
            self.assertGreaterEqual(evidence["trace_entries"], 2)
            self.assertEqual(evidence["tool_calls"], [
                "p7_workspace", "ipython", "ipython", "p7_workspace", "p7_execute_plan",
            ])
            self.assertEqual(evidence["export_count"], 3)
            self.assertRegex(evidence["workspace_revision"], r"^sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
