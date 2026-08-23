from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.parity_testing import (
    PRIME_HARNESS_BOUNDED_SCENARIO_IDS,
    PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_HARNESS_SCENARIO_MATRIX,
    build_prime_harness_observations,
    register_prime_harness_scenarios,
)
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
LEDGER = ROOT / "tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json"


def _closed_environment(private_home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    environment["HOME"] = str(private_home)
    return environment


def _node_22() -> Path | None:
    configured = os.environ.get("ASTERION_PRIME_NODE")
    candidates = [Path(configured)] if configured else []
    npm_environment = {
        key: value
        for key in ("HOME", "PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    try:
        completed = subprocess.run(
            (
                "npm",
                "exec",
                "--offline",
                "--yes",
                "--package=node@22",
                "--",
                "which",
                "node",
            ),
            cwd=ROOT,
            env=npm_environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            candidates.append(Path(completed.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        try:
            version = subprocess.run(
                (str(candidate), "--version"),
                cwd=ROOT,
                env=npm_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if version.returncode == 0 and version.stdout.startswith("v22."):
                return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


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
    def test_harness_matrix_is_seven_provider_free_and_one_bounded(self) -> None:
        self.assertEqual(len(PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS), 7)
        self.assertEqual(
            PRIME_HARNESS_BOUNDED_SCENARIO_IDS,
            ("prime-parity.harness.evidence-refinement",),
        )

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

    @unittest.skipUnless(
        PINNED_SOURCE.is_dir() and REAL_HARNESS.is_file(),
        "external pinned Prime continual harness is unavailable",
    )
    def test_provider_free_observation_cannot_promote_evidence_refinement(
        self,
    ) -> None:
        observations = build_prime_harness_observations(run_real_prime_harness())
        registry = ParityScenarioRegistry(
            json.loads(LEDGER.read_text(encoding="utf-8")),
            provider_id="asterion.prime-gateway",
        )

        register_prime_harness_scenarios(
            registry,
            observations=observations,
            bounded_receipt=None,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_HARNESS_SCENARIO_MATRIX))

        self.assertEqual(
            report.passed_scenario_ids,
            PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS,
        )
        self.assertIn(
            "prime-parity.harness.evidence-refinement",
            report.blocking_scenario_ids,
        )

    @unittest.skipUnless(
        PINNED_SOURCE.is_dir() and REAL_HARNESS.is_file(),
        "external pinned Prime continual harness is unavailable",
    )
    def test_observation_rejects_raw_or_reordered_report(self) -> None:
        report = run_real_prime_harness()
        invalid = (
            {**report, "raw_body": "SENTINEL_PRIVATE_HARNESS_BODY"},
            {**report, "scenario_ids": list(reversed(report["scenario_ids"]))},
        )

        for candidate in invalid:
            with self.subTest(candidate=tuple(candidate)), self.assertRaisesRegex(
                Exception, "harness observation is invalid"
            ):
                build_prime_harness_observations(candidate)


if __name__ == "__main__":
    unittest.main()
