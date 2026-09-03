"""Static protocol tests for the fixed launcher source."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest

from asterion.applications.prime_agent.operator.ipython_workload import (
    PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "src/asterion/applications/prime_agent/operator/image"


class TestPrimeIpythonLauncherProtocol(unittest.TestCase):
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
        self.assertIn("1024", launcher)
        self.assertIn(PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, launcher)
        self.assertIn("hashlib.sha256", launcher)
        self.assertIn('"result_digest"', launcher)
        self.assertNotIn('{"terminal":"completed"}', launcher)
        self.assertIn('value["workload_digest"] != WORKLOAD_DIGEST', launcher)
        self.assertLess(
            launcher.index('value["workload_digest"] != WORKLOAD_DIGEST'),
            launcher.index("execute_fixture()"),
        )
        for prohibited in ("os.environ", "socket", "provider", "transcript", "subprocess"):
            self.assertNotIn(prohibited, launcher.lower())

    def test_python_launcher_executes_only_image_owned_fixture_via_ipython(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")
        dockerfile = (IMAGE / "Dockerfile").read_text(encoding="utf-8")
        for required in (
            "InteractiveShell",
            "run_line_magic",
            '"/opt/prime-fixture/starter/solution.py"',
            '"/opt/prime-fixture/oracle/oracle.py"',
            '"/workspace/solution.py"',
            "fixture_source.replace(\"return 0\", \"return 42\", 1)",
            "execute_fixture()",
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
        self.assertNotIn("launcher.mjs", dockerfile)

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
