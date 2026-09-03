"""Real Prime/IPython compatibility witness for programmatic long context."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest
from typing import cast

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    verify_prime_source_lock,
)
from asterion.applications.prime_agent.programmatic_long_context_receipt import (
    ProgrammaticLongContextReceiptError,
    programmatic_long_context_observation_from_public_report,
    verify_programmatic_long_context_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
PRIME_ROOT = ROOT / "3th-party" / "prime-agent"
HARNESS = ROOT / "tests/fixtures/prime_gateway/v1/prime-programmatic-long-context-compat.mjs"
PINNED_LOCK = PrimeSourceLock(
    "a18809e00ea30638584d87b3afea7285a9d7296c",
    "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
)
PUBLIC_KEYS = {
    "format",
    "status",
    "reason",
    "real_prime_runtime",
    "allowed_tool_names",
    "active_tool_names",
    "corpus_sha256",
    "corpus_record_count",
    "selected_record_count",
    "program_sha256",
    "aggregate_sha256",
    "oracle_sha256",
    "ipython_cell_executed",
    "oracle_passed",
    "disposed",
    "reaped",
}


def _external_limited(reason: str, *, reaped: bool = False) -> dict[str, object]:
    return {
        "format": "asterion.prime-programmatic-long-context-compat/v1",
        "status": "External-limited",
        "reason": reason,
        "real_prime_runtime": False,
        "allowed_tool_names": [],
        "active_tool_names": [],
        "corpus_sha256": None,
        "corpus_record_count": 0,
        "selected_record_count": 0,
        "program_sha256": None,
        "aggregate_sha256": None,
        "oracle_sha256": None,
        "ipython_cell_executed": False,
        "oracle_passed": False,
        "disposed": False,
        "reaped": reaped,
    }


def _kernel_python() -> str | None:
    candidate = os.environ.get("PRIME_AGENT_KERNEL_PYTHON")
    if not candidate:
        return None
    path = Path(candidate)
    if not (path.is_absolute() and path.is_file() and os.access(path, os.X_OK)):
        return None
    try:
        probe = subprocess.run(
            (str(path), "-c", "import ipykernel, rlm"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return str(path) if probe.returncode == 0 else None


def _public_report(stdout: str) -> dict[str, object] | None:
    lines = stdout.splitlines()
    if len(lines) != 1:
        return None
    try:
        report = json.loads(lines[0])
    except json.JSONDecodeError:
        return None
    return report if type(report) is dict and set(report) == PUBLIC_KEYS else None


def _run_compatibility(workspace: Path) -> tuple[dict[str, object], str, int]:
    verify_prime_source_lock(PRIME_ROOT, PINNED_LOCK)
    python, node = _kernel_python(), shutil.which("node")
    if python is None or node is None:
        return _external_limited("missing-prerequisite"), "", 0
    home = workspace.parent / "home"
    home.mkdir(mode=0o700, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "NO_PROXY": "*",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "PI_OFFLINE": "1",
        "PIP_NO_INDEX": "1",
        "UV_OFFLINE": "1",
        "npm_config_offline": "true",
        "PRIME_AGENT_INSTALL_UV": "0",
        "PRIME_AGENT_KERNEL_PYTHON": python,
    }
    process = subprocess.Popen(
        (node, str(HARNESS), str(PRIME_ROOT), str(workspace)),
        cwd=workspace,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, _ = process.communicate()
        return _public_report(stdout) or _external_limited("kernel-start-timeout", reaped=True), "", 0
    try:
        os.killpg(process.pid, 0)
        reaped = False
    except ProcessLookupError:
        reaped = True
    return {**(_public_report(stdout) or _external_limited("unsupported-prime-api")), "reaped": reaped}, "", process.returncode


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "node_modules" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class TestPrimeProgrammaticLongContextCompat(unittest.TestCase):
    def test_real_prime_ipython_corpus_compatibility_is_public_safe(self) -> None:
        self.assertTrue(HARNESS.is_file())
        before = _tree_digest(PRIME_ROOT)
        with tempfile.TemporaryDirectory(prefix="asterion-prime-context-", dir="/tmp") as temporary:
            workspace = Path(temporary, "workspace")
            workspace.mkdir(mode=0o700)
            report, stderr, returncode = _run_compatibility(workspace)

        self.assertEqual(stderr, "")
        self.assertEqual(returncode, 0)
        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertIn(report["status"], {"PASS", "External-limited"})
        public = json.dumps(report, sort_keys=True, separators=(",", ":"))
        self.assertNotIn("CORPUS-SENTINEL", public)
        self.assertNotIn("PROGRAM-SENTINEL", public)
        if report["status"] == "PASS":
            self.assertEqual(report["reason"], "supported")
            self.assertTrue(report["real_prime_runtime"])
            self.assertEqual(report["allowed_tool_names"], ["ipython"])
            self.assertEqual(report["active_tool_names"], ["ipython"])
            self.assertTrue(report["ipython_cell_executed"])
            self.assertTrue(report["oracle_passed"])
            self.assertGreater(
                cast(int, report["corpus_record_count"]),
                cast(int, report["selected_record_count"]),
            )
            self.assertTrue(report["disposed"])
            self.assertTrue(report["reaped"])
            self.assertEqual(
                verify_programmatic_long_context_receipt(
                    programmatic_long_context_observation_from_public_report(report)
                ).scenario_id,
                "prime.programmatic-long-context/v1",
            )
        else:
            self.assertIn(
                report["reason"],
                {"missing-prerequisite", "missing-ipython", "unsupported-prime-api", "kernel-start-timeout"},
            )
            with self.assertRaises(ProgrammaticLongContextReceiptError):
                programmatic_long_context_observation_from_public_report(report)
        self.assertEqual(before, _tree_digest(PRIME_ROOT))
        source = HARNESS.read_text(encoding="utf-8")
        self.assertTrue(all(value not in source for value in ("fetch(", "docker", ".env", "npm install")))


if __name__ == "__main__":
    unittest.main()
