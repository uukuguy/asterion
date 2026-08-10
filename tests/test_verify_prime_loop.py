from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.verify_prime_loop import (
    PrimeVerificationError,
    load_bounded_authority,
    verify_provider_free,
)


EXPECTED_IDS = (
    "prime-loop-application",
    "prime-loop-child",
    "prime-loop-detach-attach",
    "prime-loop-checkpoint",
    "prime-loop-gateway-crash",
    "prime-loop-supervisor-crash",
    "prime-loop-worker-crash",
    "prime-loop-cancel",
    "prime-loop-budget",
    "prime-loop-redaction",
)


def _authorization(**authority_changes: object) -> dict[str, object]:
    authority: dict[str, object] = {
        "authority_id": "authority-1",
        "revision": 1,
        "allowed_portfolio": [
            {
                "provider_id": "example.provider",
                "application_id": "alpha",
                "version": "1.0.0",
                "runtime_id": "fake.runtime",
            }
        ],
        "allowed_operations": [
            "application.invoke",
            "checkpoint.create",
            "child.cancel",
            "child.message",
            "child.spawn",
            "goal.complete",
            "goal.fail",
        ],
        "budget_limit": {
            "controller_tokens": 100,
            "application_tokens": 100,
            "child_tokens": 100,
            "aggregate_tokens": 300,
            "cost_micros": 1_000,
        },
        "expires_at_ms": 100_000,
        "max_action_deadline_ms": 10_000,
        "max_recursion_depth": 1,
        "max_concurrent_children": 1,
        "execution_domain": "trusted-local",
        "host_service_grants": ["artifact.write"],
        "cancelled": False,
    }
    authority.update(authority_changes)
    return {
        "format": "asterion.prime-bounded-authorization/v1",
        "authority": authority,
    }


class TestVerifyPrimeLoop(unittest.TestCase):
    def test_provider_free_report_requires_all_exact_zero_provider_scenarios(self) -> None:
        results = tuple(
            SimpleNamespace(
                scenario_id=scenario_id,
                status="PASS",
                provider_operations=0,
                application_operations=1 if scenario_id == EXPECTED_IDS[0] else 0,
            )
            for scenario_id in EXPECTED_IDS
        )

        report = verify_provider_free(lambda: results)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["scenario_count"], 10)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["application_operations"], 1)

        for mutation in (
            results[:-1],
            (*results[:-1], SimpleNamespace(**{**vars(results[-1]), "status": "FAIL"})),
            (*results[:-1], SimpleNamespace(**{**vars(results[-1]), "provider_operations": 1})),
        ):
            with self.subTest(length=len(mutation)), self.assertRaises(
                PrimeVerificationError
            ):
                verify_provider_free(lambda mutation=mutation: mutation)

    def test_bounded_authority_requires_finite_consistent_trusted_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            valid.write_text(json.dumps(_authorization()))

            envelope = load_bounded_authority(
                valid, max_cost_micros=1_000, now_ms=1_000
            )

            self.assertEqual(envelope.authority_id, "authority-1")
            self.assertEqual(envelope.max_recursion_depth, 1)
            self.assertEqual(envelope.max_concurrent_children, 1)

            invalid_values = (
                ("zero-cap", valid, 0),
                ("lower-cap", valid, 999),
                (
                    "restricted",
                    _write(root / "restricted.json", _authorization(execution_domain="restricted")),
                    1_000,
                ),
                (
                    "expired",
                    _write(root / "expired.json", _authorization(expires_at_ms=1_000)),
                    1_000,
                ),
                (
                    "too-many-children",
                    _write(
                        root / "children.json",
                        _authorization(max_concurrent_children=2),
                    ),
                    1_000,
                ),
            )
            for name, path, maximum in invalid_values:
                with self.subTest(name=name), self.assertRaises(
                    PrimeVerificationError
                ):
                    load_bounded_authority(
                        path, max_cost_micros=maximum, now_ms=1_000
                    )

    def test_bounded_authority_errors_never_render_private_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.json"
            path.write_text("SENTINEL_SECRET")
            with self.assertRaises(PrimeVerificationError) as raised:
                load_bounded_authority(path, max_cost_micros=1, now_ms=1)
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
            self.assertNotIn(str(path), str(raised.exception))


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value))
    return path


if __name__ == "__main__":
    unittest.main()
