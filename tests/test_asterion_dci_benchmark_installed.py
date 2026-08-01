from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
INSTANCE = "dci.local-fixture@1.0.0"


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
    )


class InstalledDciBenchmarkTests(unittest.TestCase):
    def test_wheel_console_runs_and_resumes_local_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            environment["PYTHONSAFEPATH"] = "1"

            built = _run(
                (
                    "uv",
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(wheelhouse),
                    str(PROJECT),
                ),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            wheels = tuple(wheelhouse.glob("asterion-*.whl"))
            self.assertEqual(len(wheels), 1)

            virtual = root / "venv"
            created = _run(
                ("uv", "venv", "--seed", str(virtual)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            installed = _run(
                (
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(virtual / "bin" / "python"),
                    str(wheels[0]),
                ),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            executable = str(virtual / "bin" / "asterion-dci")
            lock = root / "source-lock.json"
            evidence = root / "evidence"
            instances = self._command(
                executable,
                ("benchmark", "instances", "--json"),
                root,
                environment,
            )
            locked = self._command(
                executable,
                (
                    "benchmark",
                    "lock",
                    "--instance",
                    INSTANCE,
                    "--output",
                    str(lock),
                ),
                root,
                environment,
            )
            plan = self._command(
                executable,
                (
                    "benchmark",
                    "plan",
                    "--instance",
                    INSTANCE,
                    "--capability-source-lock",
                    str(lock),
                ),
                root,
                environment,
            )
            run = self._command(
                executable,
                (
                    "benchmark",
                    "run",
                    "--instance",
                    INSTANCE,
                    "--case-limit",
                    "1",
                    "--capability-source-lock",
                    str(lock),
                    "--evidence-root",
                    str(evidence),
                    "--execute",
                ),
                root,
                environment,
            )
            resume = self._command(
                executable,
                (
                    "benchmark",
                    "resume",
                    "--instance",
                    INSTANCE,
                    "--run-id",
                    run["run_id"],
                    "--case-limit",
                    "1",
                    "--capability-source-lock",
                    str(lock),
                    "--evidence-root",
                    str(evidence),
                    "--execute",
                ),
                root,
                environment,
            )
            module_path = self._command(
                str(virtual / "bin" / "python"),
                (
                    "-I",
                    "-c",
                    (
                        "import json\n"
                        "from pathlib import Path\n"
                        "import asterion.capabilities.dci as value\n"
                        "print(json.dumps({'path': str(Path(value.__file__).resolve())}))\n"
                    ),
                ),
                root,
                environment,
            )

        self.assertEqual(len(instances), 15)
        self.assertEqual(locked, {"instance": INSTANCE, "locked": True})
        self.assertEqual(plan["application"], "dci.local-benchmark-application@1.0.0")
        self.assertEqual(plan["suite"], "dci.all@1.0.0")
        self.assertEqual(plan["case_limit"], 1)
        self.assertEqual(len(plan["tasks"]), 15)
        self.assertEqual(plan["package_locks"][0]["source_id"], "dci.builtin")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(run["tasks"]), 15)
        self.assertEqual(resume, run)
        self.assertTrue(Path(module_path["path"]).is_relative_to(virtual))
        self.assertFalse(Path(module_path["path"]).is_relative_to(PROJECT))

    def _command(
        self,
        executable: str,
        arguments: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
    ):
        result = _run(
            (executable, *arguments),
            cwd=cwd,
            environment=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail("installed DCI command did not return JSON")


if __name__ == "__main__":
    unittest.main()
