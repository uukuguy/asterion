"""Installed-wheel proof for the explicit historical legacy P7 route."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FAKE_PI = ROOT / "tests/fixtures/asterion_prime/fake_pi_rpc.py"
EXTENSION = "asterion/applications/prime/resources/ipython-extension.mjs"
LOADER = "asterion/runtimes/resources/asterion_pi_extension_loader.mjs"


def _run(command: tuple[str, ...], *, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class TestPrimeP7NativeInstalled(unittest.TestCase):
    def test_installed_legacy_route_runs_without_prime_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-p7-installed-", dir="/tmp") as temporary:
            root = Path(temporary).resolve()
            dist = root / "dist"
            dist.mkdir()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            built = _run(
                ("uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel = next(dist.glob("asterion-*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                self.assertTrue({EXTENSION, LOADER} <= names)
                extension = archive.read(EXTENSION).decode("utf-8")
                self.assertNotIn("//", extension)
                self.assertNotIn("/*", extension)
                for forbidden in ("prime_agent", "@mariozechner", "process.argv"):
                    self.assertNotIn(forbidden, extension)
                self.assertNotIn("PRIME_SOURCE", extension)

            virtual = root / "venv"
            created = _run(("uv", "venv", "--seed", str(virtual)), cwd=root, environment=environment)
            self.assertEqual(created.returncode, 0, created.stderr)
            python = virtual / "bin" / "python"
            installed = _run(
                ("uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            # The Pi extension loader imports `@earendil-works/pi-coding-agent`
            # via ESM, which walks ``./node_modules`` up from the loader file's
            # directory. The package is operator-installed globally
            # (``/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent``),
            # so stage a symlink next to the installed loader. ``NODE_PATH`` is
            # not honored by ESM and is not used. This is environment wiring
            # owned by the test, not a change to the loader or its import.
            purelib = _run(
                (str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(purelib.returncode, 0, purelib.stderr)
            loader_dir = Path(purelib.stdout.strip()) / "asterion" / "runtimes" / "resources"
            self.assertTrue(loader_dir.is_dir(), f"loader dir missing: {loader_dir}")
            earendil_host = Path(
                "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent"
            )
            self.assertTrue(earendil_host.is_dir(), f"global package missing: {earendil_host}")
            loader_node_modules = loader_dir / "node_modules" / "@earendil-works"
            loader_node_modules.mkdir(parents=True, exist_ok=True)
            symlink_target = loader_node_modules / "pi-coding-agent"
            if symlink_target.is_symlink() or symlink_target.exists():
                symlink_target.unlink()
            symlink_target.symlink_to(earendil_host)
            fixture = root / "fake_pi_rpc.py"
            shutil.copy2(FAKE_PI, fixture)
            node = shutil.which("node")
            self.assertIsNotNone(node)
            script = root / "run.py"
            source = '''
import asyncio
import json
import os
import sys
from importlib import resources
from pathlib import Path

from asterion.agents.prime.trace import validate_trace
from asterion.applications.prime.p7.game import P7GameSelection, resolve_game_selection
from asterion.applications.prime.p7.ipython_host import IpythonWorkerResult
from asterion.applications.prime.p7.operator import _resolve_p7_application, build_p7_operator_resources
from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import RuntimeFactoryContext

class Engine:
    game_id = "ls20-9607627b"
    seed = 0
    def __init__(self):
        self.target_level = int(os.environ["P7_TEST_TARGET_LEVEL"])
        self.count = 0
        self.levels = 0
        self.level_actions = 0
        self.failed_second = False
        self.resets = 0
        self.state = "NOT_FINISHED"
    def observe(self):
        return {"available_actions": ["ACTION1"], "frame": [[[self.count]]], "levels_completed": self.levels, "state": self.state, "win_levels": 7}
    def step(self, action):
        self.count += 1
        if action == "RESET":
            assert self.state == "GAME_OVER" and self.levels == 1
            self.resets += 1
            self.level_actions = 0
            self.state = "NOT_FINISHED"
        else:
            assert action == "ACTION1" and self.state == "NOT_FINISHED"
            self.level_actions += 1
            if self.target_level == 7:
                if self.level_actions == 13:
                    self.levels += 1
                    self.level_actions = 0
                    if self.levels == 7:
                        self.state = "WIN"
            elif self.levels == 0 and self.level_actions == 13:
                self.levels = 1
                self.level_actions = 0
            elif self.levels == 1 and not self.failed_second:
                self.failed_second = True
                self.state = "GAME_OVER"
            elif self.levels == 1 and self.level_actions == 13:
                self.levels = 2
                self.state = "FINISHED"
        return self.observe()

class Worker:
    async def start(self, client, *, signal): self.client = client
    async def execute_cell(self, code, *, signal):
        assert code == "fixture.solve()"
        self.broker.act(tuple("ACTION1" for _ in range(13)))
        if self.target_level == 7:
            for _ in range(6):
                self.broker.act(tuple("ACTION1" for _ in range(13)))
        if self.target_level == 2:
            self.broker.act(("ACTION1",))
            self.broker.act(("RESET",))
            self.broker.act(tuple("ACTION1" for _ in range(13)))
        return IpythonWorkerResult("ok", "completed")
    async def close(self): self.closed = True

async def main():
    root = Path.cwd()
    profile = root / "pi-profile"
    profile.mkdir(exist_ok=True)
    (profile / "auth.json").write_text(json.dumps({"deepseek": {"token": "fixture-only"}}))
    (profile / "models-store.json").write_text(json.dumps({"deepseek": {"models": [{"id": "deepseek-flash"}]}}))
    catalog = root / "arc" / "environment_files" / "zx42" / "abc123"
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / "zx42.py").write_text("# fixture source is never imported\\n")
    (catalog / "metadata.json").write_text(json.dumps({"game_id": "zx42-abc123", "baseline_actions": [10, 20, 30], "win_levels": 3}))
    selected = resolve_game_selection({"ASTERION_PRIME_P7_GAME_ID": "zx42"}, root / "arc")
    assert selected.game_id == "zx42-abc123" and selected.target_level == 3
    witness = resolve_game_selection({"ASTERION_PRIME_P7_GAME_ID": "zx42", "ASTERION_PRIME_P7_TARGET_LEVEL": "1"}, root / "arc")
    assert witness.target_level == 1
    target_level = int(__import__("os").environ["P7_TEST_TARGET_LEVEL"])
    trace = root / f"trace-{target_level}"; trace.mkdir()
    extension = Path(str(resources.files("asterion.applications.prime").joinpath("resources/ipython-extension.mjs"))).resolve()
    worker = Worker()
    worker.target_level = target_level
    engine = Engine()
    resources_ = build_p7_operator_resources(
        environment={
            "ASTERION_PRIME_PROVIDER": "deepseek",
            "ASTERION_PRIME_MODEL": "deepseek-flash",
            "ASTERION_PRIME_PI_AGENT_DIR": str(profile),
            "DEEPSEEK_API_KEY": "fixture-only",
            "ASTERION_PRIME_P7_HISTORY_VARIANT": "legacy",
        },
        pi_base_command=(sys.executable, str(root / "fake_pi_rpc.py"), "__NODE__"),
        extension_path=extension,
        working_directory=root,
        worker=worker, engine=engine, private_trace_root=trace,
        game=P7GameSelection("ls20-9607627b", 0, target_level),
    )
    if target_level == 7:
        assert int(resources_.runtime_options["max_actions"]) > 500
    worker.broker = resources_.host_services["prime.arc-broker"]
    receipt = None
    try:
        application = _resolve_p7_application()
        assembly = application.assemblies[0]
        runtime = assembly.runtime_binding.factory(RuntimeFactoryContext(provider_id="prime-applications", application_id="prime.arc-agi-3-solving", application_version="1.0.0", runtime_id="asterion.prime", assembly_path=assembly.path, options=resources_.runtime_options, host_services=resources_.host_services))
        try:
            result = await run_composed_application(assembly.plan, implementations=application.implementations, runtime=runtime, run_id="p7-installed-fixture", input_text=P7_SOLVE_PROMPT, host_services=resources_.host_services)
        except Exception:
            print(f"fixture progress: levels={engine.levels} state={engine.state} actions={engine.count}", file=sys.stderr)
            raise
        broker = resources_.host_services["prime.arc-broker"]
        replay = broker.replay(Engine)
        entries = validate_trace(resources_.host_services["prime.private-trace"].runtime_recorder.entries)
        artifact = result.artifacts[0]["value"]
        receipt = {"levels_completed": artifact["completed_level_count"], "primitive_actions": artifact["primitive_action_count"], "promotion_state": "development-only", "solver_evidence": "deterministic-double", "replay": replay.levels_completed, "resets": engine.resets, "trace_entries": len(entries), "terminal_reason": broker.seal().terminal_reason}
    finally:
        await resources_.close()
    assert receipt is not None and worker.closed is True
    receipt["worker_cleanup"] = True
    print(json.dumps(receipt, sort_keys=True))

asyncio.run(main())
'''
            script.write_text(
                source.replace("__NODE__", str(Path(node).resolve())),
                encoding="utf-8",
            )
            for target_level in (1, 2, 7):
                with self.subTest(target_level=target_level):
                    result = _run(
                        (str(python), "-I", str(script)),
                        cwd=root,
                        environment={
                            **environment,
                            "ASTERION_TEST_FORBID_PRIME_SOURCE": "1",
                            "P7_TEST_TARGET_LEVEL": str(target_level),
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertEqual(receipt["levels_completed"], target_level)
                    self.assertEqual(receipt["promotion_state"], "development-only")
                    self.assertEqual(receipt["solver_evidence"], "deterministic-double")
                    self.assertEqual(receipt["primitive_actions"], 13 if target_level == 1 else 28 if target_level == 2 else 91)
                    self.assertEqual(receipt["replay"], target_level)
                    self.assertEqual(receipt["resets"], 1 if target_level == 2 else 0)
                    self.assertEqual(receipt["terminal_reason"], "game-won" if target_level == 7 else "level-completed")
                    self.assertGreaterEqual(receipt["trace_entries"], 2)
                    self.assertTrue(receipt["worker_cleanup"])


if __name__ == "__main__":
    unittest.main()
