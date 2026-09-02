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

    def test_launcher_has_one_canonical_selfcheck_then_one_redacted_release_barrier(self) -> None:
        launcher = (IMAGE / "launcher.mjs").read_text(encoding="utf-8")
        expected = json.dumps({"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}, separators=(",", ":"), sort_keys=True)
        self.assertIn(expected, launcher)
        self.assertIn("1024", launcher)
        self.assertIn('{"release":true}', launcher)
        self.assertIn("releaseCount !== 1", launcher)
        self.assertIn("unproven", launcher)
        for prohibited in ("process.env", "socket", "provider", "transcript"):
            self.assertNotIn(prohibited, launcher.lower())

    def test_launcher_requires_exact_mount_writable_and_credential_checks_before_frame(self) -> None:
        launcher = (IMAGE / "launcher.mjs").read_text(encoding="utf-8")
        for required in (
            "parseMounts",
            'mountPoint === "/"',
            'mountPoint === "/workspace"',
            'options.has("ro")',
            'options.has("rw")',
            "workspaceOnlyWritable",
            "credentialSentinelAbsent",
            "requireClosedWorker();\nprocess.stdout.write",
        ):
            with self.subTest(required=required):
                self.assertIn(required, launcher)
        self.assertNotIn('mounts.includes(" / ")', launcher)
        self.assertNotIn('mounts.includes(" /workspace ")', launcher)

    def test_launcher_rejects_writable_root_other_mount_and_credential_sentinel(self) -> None:
        launcher = (IMAGE / "launcher.mjs").read_text(encoding="utf-8")
        cases = {
            "writable root": 'if (mountPoint === "/") rootReadOnly = options.has("ro");',
            "other writable mount": 'options.has("rw") && mountPoint !== "/workspace" && !writableKernelMounts.has(mountPoint)',
            "credential sentinel": "return credentialSentinels.every((sentinel) => !existsSync(sentinel));",
            "safe result": "return rootReadOnly && workspaceWritable;",
        }
        for name, assertion in cases.items():
            with self.subTest(name=name):
                self.assertIn(assertion, launcher)
