"""Provider-free compatibility witness for Prime's SDK-backed IPython session."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    verify_prime_source_lock,
)


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
PINNED_LOCK = PrimeSourceLock(
    "a18809e00ea30638584d87b3afea7285a9d7296c",
    "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
)


_MODULE = __name__


def _external_limited(reason: str, *, reaped: bool = False) -> dict[str, object]:
    return {
        "format": "asterion.prime-ipython-coding-compat/v1",
        "status": "External-limited", "reason": reason,
        "real_prime_runtime": False, "custom_provider": False,
        "allowed_tool_names": [], "active_tool_names": [],
        "ipython_cell_executed": False, "compact_called": False,
        "event_kinds": [], "event_count": 0,
        "session_generation_before": 0, "session_generation_after": 0,
        "kernel_generation_before": 0, "kernel_generation_after": 0,
        "disposed": False, "reaped": reaped,
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
            (str(path), "-c", "import ipykernel, rlm; assert callable(rlm.run) and callable(rlm.host_request)"),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=False, env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
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
    return report if isinstance(report, dict) and set(report) == PUBLIC_KEYS else None


def _process_group_gone(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _reap_process_group(process: subprocess.Popen[str]) -> tuple[str, bool]:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        stdout, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, _ = process.communicate()
    if _process_group_gone(process.pid):
        return stdout or "", True
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return stdout or "", True
    deadline = time.monotonic() + 5
    reaped = _process_group_gone(process.pid)
    while not reaped and time.monotonic() < deadline:
        time.sleep(0.05)
        reaped = _process_group_gone(process.pid)
    return stdout or "", reaped


def _run_compatibility(workspace: Path) -> tuple[dict[str, object], str, int]:
    verify_prime_source_lock(PRIME_ROOT, PINNED_LOCK)
    python = _kernel_python()
    if python is None:
        return _external_limited("missing-prerequisite"), "", 0
    node = shutil.which("node")
    if node is None:
        return _external_limited("missing-prerequisite"), "", 0
    home = workspace.parent / "home"
    home.mkdir(mode=0o700, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""), "HOME": str(home),
        "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
        "PI_OFFLINE": "1", "PIP_NO_INDEX": "1", "UV_OFFLINE": "1",
        "npm_config_offline": "true", "PRIME_AGENT_INSTALL_UV": "0",
        "PRIME_AGENT_KERNEL_PYTHON": python,
    }
    process = subprocess.Popen(
        (node, str(HARNESS), str(PRIME_ROOT), str(workspace)), cwd=workspace,
        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=15)
    except subprocess.TimeoutExpired as timeout:
        stdout = timeout.output if isinstance(timeout.output, str) else ""
        reaped_stdout, reaped = _reap_process_group(process)
        stdout = stdout or reaped_stdout
        report = _public_report(stdout) or _external_limited("kernel-start-timeout")
        return {**report, "reaped": reaped}, "", 0
    report = _public_report(stdout) or _external_limited("unsupported-prime-api")
    report = {**report, "reaped": _process_group_gone(process.pid)}
    return report, "", process.returncode


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "node_modules" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class TestPrimeIpythonCodingCompat(unittest.TestCase):
    def test_missing_preprovisioned_kernel_returns_external_limited_without_node(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(f"{_MODULE}.subprocess.Popen") as popen,
        ):
            report, stderr, returncode = _run_compatibility(Path("/tmp/workspace"))
        self.assertEqual(report, _external_limited("missing-prerequisite"))
        self.assertEqual(stderr, "")
        self.assertEqual(returncode, 0)
        popen.assert_not_called()

    def test_timeout_preserves_existing_public_reason_and_reaps_group(self) -> None:
        valid = json.dumps(_external_limited("missing-ipython"), sort_keys=True, separators=(",", ":")) + "\n"
        process = mock.Mock(pid=123, returncode=None)
        process.communicate.side_effect = [subprocess.TimeoutExpired(("node",), 15, output=valid, stderr="private"), (valid, "private")]
        with (
            mock.patch(f"{_MODULE}.subprocess.Popen", return_value=process),
            mock.patch(f"{_MODULE}.os.killpg", side_effect=[None, ProcessLookupError]),
            mock.patch(f"{_MODULE}._kernel_python", return_value="/tmp/python"),
        ):
            report, stderr, returncode = _run_compatibility(Path("/tmp/workspace"))
        self.assertEqual(report, _external_limited("missing-ipython", reaped=True))
        self.assertEqual(stderr, "")
        self.assertEqual(returncode, 0)

    def test_reaped_is_reported_only_after_parent_confirms_group_is_gone(self) -> None:
        process = mock.Mock(pid=123, returncode=0)
        process.communicate.return_value = (json.dumps(_external_limited("missing-ipython", reaped=True)) + "\n", "private")
        with (
            mock.patch(f"{_MODULE}.subprocess.Popen", return_value=process),
            mock.patch(f"{_MODULE}.os.killpg", return_value=None) as killpg,
            mock.patch(f"{_MODULE}._kernel_python", return_value="/tmp/python"),
        ):
            report, _, _ = _run_compatibility(Path("/tmp/workspace"))
        self.assertFalse(report["reaped"])
        killpg.assert_called_once_with(123, 0)

    def test_timeout_kills_lingering_group_before_reporting_reaped(self) -> None:
        process = mock.Mock(pid=123, returncode=None)
        process.communicate.side_effect = [subprocess.TimeoutExpired(("node",), 15), ("", "")]
        with (
            mock.patch(f"{_MODULE}.subprocess.Popen", return_value=process),
            mock.patch(f"{_MODULE}.os.killpg", side_effect=[None, None, None, ProcessLookupError]) as killpg,
            mock.patch(f"{_MODULE}._kernel_python", return_value="/tmp/python"),
        ):
            report, _, _ = _run_compatibility(Path("/tmp/workspace"))
        self.assertTrue(report["reaped"])
        self.assertEqual(killpg.call_args_list, [
            mock.call(123, signal.SIGTERM), mock.call(123, 0),
            mock.call(123, signal.SIGKILL), mock.call(123, 0),
        ])

    def test_source_lock_is_verified_before_node_process_starts(self) -> None:
        with (
            mock.patch(f"{_MODULE}.verify_prime_source_lock", side_effect=ValueError("invalid")) as verify,
            mock.patch(f"{_MODULE}.subprocess.Popen") as popen,
        ):
            with self.assertRaises(ValueError):
                _run_compatibility(Path("/tmp/workspace"))
        verify.assert_called_once_with(PRIME_ROOT, PINNED_LOCK)
        popen.assert_not_called()

    def test_node_environment_disables_bootstrap_and_package_network_access(self) -> None:
        process = mock.Mock(pid=123, returncode=0)
        process.communicate.return_value = (json.dumps(_external_limited("missing-ipython")) + "\n", "")
        with (
            mock.patch(f"{_MODULE}.subprocess.Popen", return_value=process) as popen,
            mock.patch(f"{_MODULE}.os.killpg", side_effect=ProcessLookupError),
            mock.patch(f"{_MODULE}._kernel_python", return_value="/tmp/python"),
        ):
            _run_compatibility(Path("/tmp/workspace"))
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["PRIME_AGENT_INSTALL_UV"], "0")
        self.assertEqual(env["PI_OFFLINE"], "1")
        self.assertEqual(env["UV_OFFLINE"], "1")
        self.assertEqual(env["PIP_NO_INDEX"], "1")
        self.assertEqual(env["npm_config_offline"], "true")

    def test_real_sdk_ipython_compatibility_is_provider_free_and_source_immutable(self) -> None:
        self.assertTrue(HARNESS.is_file())
        self.assertTrue(PRIME_ROOT.is_dir())
        before = _tree_digest(PRIME_ROOT)
        with tempfile.TemporaryDirectory(prefix="asterion-prime-ipython-", dir="/tmp") as temporary:
            workspace = Path(temporary, "workspace")
            workspace.mkdir(mode=0o700)
            report, stderr, returncode = _run_compatibility(workspace)
        self.assertEqual(stderr, "")
        self.assertEqual(returncode, 0)
        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertEqual(report["format"], "asterion.prime-ipython-coding-compat/v1")
        self.assertIn(report["status"], {"PASS", "External-limited"})
        public = json.dumps(report, sort_keys=True, separators=(",", ":"))
        self.assertNotIn("PrimeEvidenceReceipt", public)
        self.assertNotIn("sandbox", public.lower())
        if report["status"] == "PASS":
            self.assertEqual(report["reason"], "supported")
            self.assertTrue(report["real_prime_runtime"])
            self.assertTrue(report["custom_provider"])
            self.assertEqual(report["allowed_tool_names"], ["ipython"])
            self.assertEqual(report["active_tool_names"], ["ipython"])
            self.assertTrue(report["ipython_cell_executed"])
            self.assertTrue(report["compact_called"])
            self.assertGreater(cast(int, report["event_count"]), 0)
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
