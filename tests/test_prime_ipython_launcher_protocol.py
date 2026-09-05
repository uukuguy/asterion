"""Static protocol tests for the fixed launcher source."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import runpy
import shutil
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest

from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256,
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "src/asterion/applications/prime_agent/operator/image"


class _SpoofableInteractiveShell:
    def run_line_magic(self, name: str, path: str) -> None:
        if name != "run":
            raise AssertionError("unexpected magic")
        runpy.run_path(path)

    def run_cell(self, cell: str, *, store_history: bool) -> SimpleNamespace:
        del store_history
        try:
            exec(cell, {"InteractiveShell": type(self), "Path": Path})
        except BaseException as error:
            return SimpleNamespace(error_in_exec=error, error_before_exec=None)
        return SimpleNamespace(error_in_exec=None, error_before_exec=None)


def _load_launcher() -> tuple[ModuleType, dict[str, ModuleType | None]]:
    module_names = (
        "IPython",
        "IPython.core",
        "IPython.core.interactiveshell",
    )
    previous = {name: sys.modules.get(name) for name in module_names}
    ipython = ModuleType("IPython")
    core = ModuleType("IPython.core")
    interactive = ModuleType("IPython.core.interactiveshell")
    setattr(interactive, "InteractiveShell", _SpoofableInteractiveShell)
    sys.modules.update({
        "IPython": ipython,
        "IPython.core": core,
        "IPython.core.interactiveshell": interactive,
    })
    spec = importlib.util.spec_from_file_location("prime_ipython_launcher_under_test", IMAGE / "launcher.py")
    if spec is None or spec.loader is None:
        raise AssertionError("launcher must load")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher, previous


def _restore_ipython(previous: dict[str, ModuleType | None]) -> None:
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class TestPrimeIpythonLauncherProtocol(unittest.TestCase):
    def test_workload_identity_is_distinct_from_existing_launcher_result_identity(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")

        self.assertNotEqual(
            PRIME_IPYTHON_CODING_WORKLOAD_DIGEST.removeprefix("sha256:"),
            PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256,
        )
        self.assertIn(PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256, launcher)
        self.assertNotIn(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, launcher)

    def test_fixture_starts_failing_then_can_pass_without_oracle_mutation(self) -> None:
        starter = IMAGE / "fixture/starter/solution.py"
        oracle = IMAGE / "fixture/oracle/oracle.py"
        lock = json.loads((IMAGE / "fixture/fixture-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["starter_sha256"], sha256(starter.read_bytes()).hexdigest())
        self.assertEqual(lock["oracle_sha256"], sha256(oracle.read_bytes()).hexdigest())
        self.assertIn("return 0", starter.read_text(encoding="utf-8"))
        self.assertIn("answer() == 42", oracle.read_text(encoding="utf-8"))
        self.assertIn("initial_oracle_must_fail", lock)
        immutable_oracle = oracle.read_bytes()
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            copied_starter = workspace / "solution.py"
            copied_oracle = workspace / "oracle.py"
            shutil.copyfile(starter, copied_starter)
            shutil.copyfile(oracle, copied_oracle)
            sys.path.insert(0, str(workspace))
            try:
                with self.assertRaises(AssertionError):
                    runpy.run_path(str(copied_oracle))
                copied_starter.write_text("def answer() -> int:\n    return 42\n", encoding="utf-8")
                sys.modules.pop("solution", None)
                runpy.run_path(str(copied_oracle))
            finally:
                sys.modules.pop("solution", None)
                sys.path.remove(str(workspace))
        self.assertEqual(oracle.read_bytes(), immutable_oracle)

    def test_python_launcher_has_one_canonical_selfcheck_and_bound_completion(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")
        expected = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True)
        self.assertIn(expected, launcher)
        self.assertIn("_FRAME_LIMIT", launcher)
        self.assertIn(PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256, launcher)
        self.assertNotIn(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, launcher)
        self.assertIn("hashlib.sha256", launcher)
        self.assertIn('"result_digest"', launcher)
        self.assertNotIn('{"terminal":"completed"}', launcher)
        self.assertIn('value.get("workload_digest") != WORKLOAD_DIGEST', launcher)
        self.assertLess(
            launcher.index('value.get("workload_digest") != WORKLOAD_DIGEST'),
            launcher.index("emit_model_request()"),
        )
        for prohibited in ("os.environ", "socket", "provider", "transcript"):
            self.assertNotIn(prohibited, launcher.lower())
        for required in (
            "subprocess.run",
            '"-I"',
            '"-S"',
            '"-B"',
            "_MODEL_CELL_PROGRAM",
            "input=cell.encode(\"utf-8\")",
            "stdin=subprocess.DEVNULL",
            "stdout=subprocess.DEVNULL",
            "stderr=subprocess.DEVNULL",
        ):
            with self.subTest(required=required):
                self.assertIn(required, launcher)
        self.assertNotIn("shell.run_cell", launcher)

    def test_python_launcher_accepts_only_a_host_mediated_ipython_model_response(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")
        dockerfile = (IMAGE / "Dockerfile").read_text(encoding="utf-8")
        for required in (
            "InteractiveShell",
            '"/opt/prime-fixture/starter/solution.py"',
            '"/opt/prime-fixture/oracle/oracle.py"',
            '"/workspace/solution.py"',
            "initial_oracle_failure",
            "read_control()",
            "emit_model_request()",
            "read_model_response()",
            'value["tool"] != "ipython"',
            "_MODEL_CELL_PROGRAM",
            "final_oracle_success",
            "emit_completion()",
        ):
            with self.subTest(required=required):
                self.assertIn(required, launcher)
        for required in (
            "FROM python:3.11.11-bookworm@sha256:4ca910a51a1a474e5d95aa52455331b2a94272eeae3c498be1ad7a2ff9b00bf3",
            "COPY requirements.lock /opt/prime-requirements.lock",
            "pip install --no-cache-dir --require-hashes",
            "COPY launcher.py /usr/local/bin/prime-ipython-coding.py",
            'ENTRYPOINT [\"/usr/local/bin/prime-ipython-coding.py\"]',
        ):
            with self.subTest(dockerfile=required):
                self.assertIn(required, dockerfile)
        for prohibited in (
            'replace("return 0", "return 42", 1)',
            "def answer()",
            "execute_fixture()",
            "manual",
            "fake",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, launcher.lower())
        self.assertNotIn("launcher.mjs", dockerfile)

    def test_launcher_frames_are_closed_duplex_and_terminal_facts_are_causal(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")
        for required in (
            '"control"', '"model-request"', '"model-response"', '"completed"',
            '"host_model_operations": 1', '"tools": ["ipython"]',
            '"model_caused_ipython_mutation": True',
            '"oracle_initially_failed": True', '"oracle_eventually_passed": True',
            "PRIME_SDK_SESSION_PIN", "_FRAME_LIMIT", "canonical(value)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, launcher)
        self.assertLess(launcher.rindex("initial_oracle_failure()"), launcher.rindex("emit_model_request()"))
        self.assertLess(launcher.rindex("read_model_response()"), launcher.rindex("final_oracle_success()"))

    def test_final_oracle_rejects_incorrect_workspace_mutation_from_model_cell(self) -> None:
        launcher, previous = _load_launcher()
        self.addCleanup(_restore_ipython, previous)
        starter = IMAGE / "fixture/starter/solution.py"
        oracle = IMAGE / "fixture/oracle/oracle.py"
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            solution = workspace / "solution.py"
            copied_oracle = workspace / "oracle.py"
            shutil.copyfile(starter, solution)
            shutil.copyfile(oracle, copied_oracle)
            setattr(launcher, "_STARTER", starter)
            setattr(launcher, "_ORACLE", copied_oracle)
            setattr(launcher, "_WORKSPACE_SOLUTION", solution)
            setattr(launcher, "_MODEL_CELL_PROGRAM", "import sys; exec(sys.stdin.read(), {})")
            try:
                launcher.initial_oracle_failure()
                launcher.execute_model_ipython_cell(
                    "\n".join((
                        "from pathlib import Path",
                        f"Path({str(solution)!r}).write_text("
                        "'def answer() -> int:\\n    return -1\\n', encoding='utf-8')",
                    )),
                )
                with self.assertRaises(RuntimeError):
                    launcher.final_oracle_success()
            finally:
                sys.modules.pop("solution", None)

    def test_model_cell_cannot_emit_terminal_frame_or_mutate_supervisor_globals(self) -> None:
        launcher, previous = _load_launcher()
        self.addCleanup(_restore_ipython, previous)
        starter = IMAGE / "fixture/starter/solution.py"
        oracle = IMAGE / "fixture/oracle/oracle.py"
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            solution = workspace / "solution.py"
            copied_oracle = workspace / "oracle.py"
            shutil.copyfile(starter, solution)
            shutil.copyfile(oracle, copied_oracle)
            setattr(launcher, "_STARTER", starter)
            setattr(launcher, "_ORACLE", copied_oracle)
            setattr(launcher, "_WORKSPACE_SOLUTION", solution)
            setattr(launcher, "_MODEL_CELL_PROGRAM", "import sys; exec(sys.stdin.read(), {})")
            original_completion = launcher.emit_completion
            try:
                launcher.initial_oracle_failure()
                launcher.execute_model_ipython_cell(
                    "\n".join((
                        "import json, sys",
                        "from pathlib import Path",
                        "print(json.dumps({'terminal': 'completed'}))",
                        "import __main__",
                        "__main__.emit_completion = lambda: None",
                        f"Path({str(solution)!r}).write_text("
                        "'def answer() -> int:\\n    return -1\\n', encoding='utf-8')",
                    )),
                )
                self.assertIs(launcher.emit_completion, original_completion)
                with self.assertRaises(RuntimeError):
                    launcher.final_oracle_success()
            finally:
                sys.modules.pop("solution", None)

    def test_python_launcher_keeps_closed_worker_checks_before_selfcheck(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")
        cases = {
            "writable root": 'mount_point == "/"',
            "other writable mount": 'mount_point != "/workspace"',
            "credential sentinel": "_CREDENTIAL_SENTINELS",
            "safe result": "root_read_only and workspace_writable",
        }
        for name, assertion in cases.items():
            with self.subTest(name=name):
                self.assertIn(assertion, launcher)
