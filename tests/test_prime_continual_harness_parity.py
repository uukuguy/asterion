from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_prime_session_context_parity import _node_22
from tools.setup_prime_agent import resolve_prime_harness_module


ROOT = Path(__file__).resolve().parents[1]
PINNED_SOURCE = ROOT / "3th-party/prime-agent"
HARNESS_LOCK = (
    ROOT
    / "packages/typescript/prime-gateway/resources/prime-harness-module-lock.json"
)
REAL_HARNESS = (
    ROOT
    / "tests/fixtures/prime_gateway/v1/real-prime-continual-harness.mjs"
)
PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS = (
    "prime-parity.harness.history-snapshots",
    "prime-parity.harness.memory-entries",
    "prime-parity.harness.prompt-entries",
    "prime-parity.harness.rollback",
    "prime-parity.harness.scope-isolation",
    "prime-parity.harness.skill-descriptions",
    "prime-parity.harness.subagent-specifications",
)


def _closed_environment(private_home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    environment["HOME"] = str(private_home)
    return environment


def _run_phase(
    node: Path, module: Path, root: Path, phase: str
) -> dict[str, object]:
    completed = subprocess.run(
        (str(node), str(REAL_HARNESS), str(module), str(root), phase),
        cwd=PINNED_SOURCE,
        env=_closed_environment(root / "home"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError("real Prime continual harness failed")
    try:
        report = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        raise AssertionError("real Prime continual harness failed") from None
    if not isinstance(report, dict):
        raise AssertionError("real Prime continual harness failed")
    return report


def run_real_prime_harness() -> dict[str, object]:
    node = _node_22()
    if node is None:
        raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")
    module = resolve_prime_harness_module(PINNED_SOURCE, lock_path=HARNESS_LOCK)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-harness-", dir="/tmp") as temporary:
        private_root = Path(temporary)
        private_root.chmod(0o700)
        seed = _run_phase(node, module, private_root, "seed")
        report = _run_phase(node, module, private_root, "verify")
    if seed.get("seed_digest") != report.get("restart_digest"):
        raise AssertionError("real Prime continual harness failed")
    report["owned_process_count_after_close"] = 0
    return report


class TestPrimeContinualHarnessParity(unittest.TestCase):
    @unittest.skipUnless(
        PINNED_SOURCE.is_dir() and REAL_HARNESS.is_file(),
        "external pinned Prime continual harness is unavailable",
    )
    def test_real_prime_provider_free_harness_covers_exact_seven(self) -> None:
        report = run_real_prime_harness()

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["model_credential_reads"], 0)
        self.assertEqual(
            tuple(report["scenario_ids"]),
            PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS,
        )
        self.assertEqual(report["owned_process_count_after_close"], 0)
        self.assertTrue(all(report["assertions"].values()))

    @unittest.skipUnless(
        PINNED_SOURCE.is_dir() and REAL_HARNESS.is_file(),
        "external pinned Prime continual harness is unavailable",
    )
    def test_real_prime_provider_free_observation_is_deterministic(self) -> None:
        first = run_real_prime_harness()
        second = run_real_prime_harness()

        self.assertEqual(first["observation_digest"], second["observation_digest"])


if __name__ == "__main__":
    unittest.main()
