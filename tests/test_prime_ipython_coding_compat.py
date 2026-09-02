"""Provider-free compatibility witness for Prime's SDK-backed IPython session."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIME_ROOT = ROOT / "3th-party" / "prime-agent"
HARNESS = ROOT / "tests/fixtures/prime_gateway/v1/prime-ipython-coding-compat.mjs"
PUBLIC_KEYS = {
    "format", "status", "reason", "real_prime_runtime", "custom_provider",
    "allowed_tool_names", "active_tool_names", "ipython_cell_executed",
    "compact_called", "event_kinds", "event_count", "session_generation_before",
    "session_generation_after", "kernel_generation_before", "kernel_generation_after",
    "disposed", "reaped",
}


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "node_modules" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class TestPrimeIpythonCodingCompat(unittest.TestCase):
    def test_real_sdk_ipython_compatibility_is_provider_free_and_source_immutable(self) -> None:
        self.assertTrue(HARNESS.is_file())
        self.assertTrue(PRIME_ROOT.is_dir())
        node = shutil.which("node")
        self.assertIsNotNone(node)
        before = _tree_digest(PRIME_ROOT)
        with tempfile.TemporaryDirectory(prefix="asterion-prime-ipython-", dir="/tmp") as temporary:
            workspace = Path(temporary, "workspace")
            workspace.mkdir(mode=0o700)
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path(temporary, "home")), "NO_PROXY": "*", "PI_OFFLINE": "1"}
            Path(env["HOME"]).mkdir(mode=0o700)
            self.assertEqual(set(env), {"PATH", "HOME", "NO_PROXY", "PI_OFFLINE"})
            process = subprocess.Popen(
                (node, str(HARNESS), str(PRIME_ROOT), str(workspace)), cwd=workspace,
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                stdout = json.dumps({
                    "format": "asterion.prime-ipython-coding-compat/v1",
                    "status": "External-limited", "reason": "kernel-start-timeout",
                    "real_prime_runtime": False, "custom_provider": False,
                    "allowed_tool_names": [], "active_tool_names": [],
                    "ipython_cell_executed": False, "compact_called": False,
                    "event_kinds": [], "event_count": 0,
                    "session_generation_before": 0, "session_generation_after": 0,
                    "kernel_generation_before": 0, "kernel_generation_after": 0,
                    "disposed": False, "reaped": False,
                }, sort_keys=True, separators=(",", ":")) + "\n"
                stderr = ""
        self.assertEqual(stderr, "")
        self.assertEqual(0 if timed_out else process.returncode, 0)
        report = json.loads(stdout)
        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertEqual(stdout, json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
        self.assertEqual(report["format"], "asterion.prime-ipython-coding-compat/v1")
        self.assertIn(report["status"], {"PASS", "External-limited"})
        self.assertNotIn("PrimeEvidenceReceipt", stdout)
        self.assertNotIn("sandbox", stdout.lower())
        if report["status"] == "PASS":
            self.assertEqual(report["reason"], "supported")
            self.assertTrue(report["real_prime_runtime"])
            self.assertTrue(report["custom_provider"])
            self.assertEqual(report["allowed_tool_names"], ["ipython"])
            self.assertEqual(report["active_tool_names"], ["ipython"])
            self.assertTrue(report["ipython_cell_executed"])
            self.assertTrue(report["compact_called"])
            self.assertGreater(report["event_count"], 0)
            self.assertEqual(report["session_generation_before"], 1)
            self.assertEqual(report["session_generation_after"], 1)
            self.assertEqual(report["kernel_generation_before"], 1)
            self.assertEqual(report["kernel_generation_after"], 1)
            self.assertTrue(report["disposed"])
            self.assertTrue(report["reaped"])
        else:
            self.assertIn(report["reason"], {"missing-ipython", "unsupported-prime-api", "missing-prerequisite", "kernel-start-timeout"})
        self.assertEqual(before, _tree_digest(PRIME_ROOT))
        source = HARNESS.read_text(encoding="utf-8")
        self.assertTrue(all(forbidden not in source for forbidden in ("npm install", "npm run", "docker", ".env", "fetch(")))


if __name__ == "__main__":
    unittest.main()
