"""Installed-wheel proof for the provider-free native P7 route."""

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
    def test_installed_route_runs_without_prime_checkout(self) -> None:
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
            fixture = root / "fake_pi_rpc.py"
            shutil.copy2(FAKE_PI, fixture)
            node = shutil.which("node")
            self.assertIsNotNone(node)
            script = root / "run.py"
            source = '''
import asyncio
import json
import sys
from importlib import resources
from pathlib import Path

from asterion.agents.prime.trace import validate_trace
from asterion.applications.prime import create_provider
from asterion.applications.prime.p7.ipython_host import IpythonWorkerResult
from asterion.applications.prime.p7.operator import build_p7_operator_resources
from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
from asterion.applications.provider import resolve_installed_provider
from asterion.capabilities.prime_arc_agi_3_solver.provider import create_prime_arc_agi_3_solver_package
from asterion.runner.composed import run_composed_application
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext

class Engine:
    game_id = "ls20-9607627b"
    seed = 0
    def __init__(self): self.count = 0
    def observe(self):
        return {"available_actions": ["ACTION1"], "frame": [[[self.count]]], "levels_completed": 0, "state": "NOT_FINISHED", "win_levels": 7}
    def step(self, action):
        assert action == "ACTION1"
        self.count += 1
        return {"available_actions": ["ACTION1"], "frame": [[[self.count]]], "levels_completed": int(self.count == 13), "state": "FINISHED" if self.count == 13 else "NOT_FINISHED", "win_levels": 7}

class Worker:
    async def start(self, client, *, signal): self.client = client
    async def execute_cell(self, code, *, signal):
        assert code == "fixture.solve()"
        self.broker.act(tuple("ACTION1" for _ in range(13)))
        return IpythonWorkerResult("ok", "completed")
    async def close(self): self.closed = True

async def main():
    root = Path.cwd()
    trace = root / "trace"; trace.mkdir()
    extension = Path(str(resources.files("asterion.applications.prime").joinpath("resources/ipython-extension.mjs"))).resolve()
    worker = Worker()
    resources_ = build_p7_operator_resources(
        environment={"DEEPSEEK_API_KEY": "fixture-only"},
        pi_base_command=(sys.executable, str(root / "fake_pi_rpc.py"), "__NODE__"),
        extension_path=extension,
        working_directory=root,
        worker=worker, engine=Engine(), private_trace_root=trace,
    )
    worker.broker = resources_.host_services["prime.arc-broker"]
    receipt = None
    try:
        provider = resolve_installed_provider(create_provider(), runtime_factories=default_runtime_factory_registry(), installed_packages=(create_prime_arc_agi_3_solver_package(),))
        application = provider.applications[0]
        assembly = application.assemblies[0]
        runtime = assembly.runtime_binding.factory(RuntimeFactoryContext(provider_id="prime-applications", application_id="prime.arc-agi-3-solving", application_version="1.0.0", runtime_id="asterion.prime", assembly_path=assembly.path, options=resources_.runtime_options, host_services=resources_.host_services))
        result = await run_composed_application(assembly.plan, implementations=application.implementations, runtime=runtime, run_id="p7-installed-fixture", input_text=P7_SOLVE_PROMPT, host_services=resources_.host_services)
        broker = resources_.host_services["prime.arc-broker"]
        replay = broker.replay(Engine)
        entries = validate_trace(resources_.host_services["prime.private-trace"].runtime_recorder.entries)
        artifact = result.artifacts[0]["value"]
        receipt = {"levels_completed": artifact["completed_level_count"], "primitive_actions": artifact["primitive_action_count"], "promotion_state": "development-only", "solver_evidence": "deterministic-double", "replay": replay.levels_completed, "trace_entries": len(entries)}
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
            result = _run(
                (str(python), "-I", str(script)),
                cwd=root,
                environment={**environment, "ASTERION_TEST_FORBID_PRIME_SOURCE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["levels_completed"], 1)
            self.assertEqual(receipt["promotion_state"], "development-only")
            self.assertEqual(receipt["solver_evidence"], "deterministic-double")
            self.assertEqual(receipt["primitive_actions"], 13)
            self.assertEqual(receipt["replay"], 1)
            self.assertGreaterEqual(receipt["trace_entries"], 2)
            self.assertTrue(receipt["worker_cleanup"])


if __name__ == "__main__":
    unittest.main()
