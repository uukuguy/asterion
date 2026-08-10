from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import tools.check_prime_parity as parity_checker
from asterion.control.parity import validate_parity_ledger


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "prime-parity" / "v1"
PINNED_SOURCE = ROOT / "3th-party" / "prime-agent"
PINNED_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c"


def _ledger(name: str = "prime-agent-0.7.1.json"):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return validate_parity_ledger(value)


class TestCheckPrimeParity(unittest.TestCase):
    def test_explicit_source_check_proves_every_declared_file_and_anchor(self) -> None:
        report = parity_checker.verify_prime_source_evidence(
            _ledger(), source_root=PINNED_SOURCE
        )

        self.assertEqual(report.source_commit, PINNED_COMMIT)
        self.assertEqual(report.feature_count, 63)
        self.assertEqual(report.evidence_record_count, 70)
        self.assertEqual(report.file_count, 48)
        self.assertEqual(report.anchor_count, 76)
        self.assertNotIn(str(PINNED_SOURCE), repr(report))

    def test_inventory_without_source_root_is_metadata_only(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(
                parity_checker,
                "verify_prime_source_evidence",
                side_effect=AssertionError("source verifier must not run"),
            ),
            redirect_stdout(output),
        ):
            exit_code = parity_checker.main(["--claim", "inventory"])

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["feature_count"], 63)
        self.assertEqual(report["mandatory_feature_count"], 61)
        self.assertEqual(report["excluded_feature_count"], 2)
        self.assertEqual(report["scenario_count"], 61)
        self.assertFalse(report["source_verified"])
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["application_operations"], 0)

    def test_verified_system_claim_fails_closed_with_only_stable_ids(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                ["--claim", "verified-system-parity"]
            )

        rendered = output.getvalue()
        report = json.loads(rendered)
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["blocking_feature_count"], 61)
        self.assertEqual(len(report["blocking_feature_ids"]), 61)
        self.assertEqual(report["passed_feature_count"], 0)
        self.assertNotIn("prime_evidence", rendered)
        self.assertNotIn("anchors", rendered)
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn(PINNED_COMMIT, rendered)

    def test_source_mismatch_and_symlink_fail_without_rendering_values(self) -> None:
        fixture = json.loads(
            (FIXTURES / "valid-ledger-minimal.json").read_text(encoding="utf-8")
        )
        fixture["features"][0]["prime_evidence"][0]["anchors"] = [  # type: ignore[index]
            "SENTINEL_SECRET"
        ]
        missing_anchor = validate_parity_ledger(fixture)
        source_report = SimpleNamespace(source_commit=PINNED_COMMIT)

        with (
            mock.patch.object(
                parity_checker,
                "verify_prime_checkout",
                return_value=source_report,
            ),
            self.assertRaises(parity_checker.PrimeParityCheckError) as raised,
        ):
            parity_checker.verify_prime_source_evidence(
                missing_anchor, source_root=PINNED_SOURCE
            )
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
        self.assertNotIn(str(PINNED_SOURCE), str(raised.exception))

        clean = _ledger("valid-ledger-minimal.json")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            outside = temporary / "outside"
            target = outside / "coding-agent" / "src" / "core"
            target.mkdir(parents=True)
            (target / "session-manager.ts").write_text(
                "export class SessionManager {}\n", encoding="utf-8"
            )
            (temporary / "root").mkdir()
            (temporary / "root" / "packages").symlink_to(outside)
            with (
                mock.patch.object(
                    parity_checker,
                    "verify_prime_checkout",
                    return_value=source_report,
                ),
                self.assertRaises(parity_checker.PrimeParityCheckError),
            ):
                parity_checker.verify_prime_source_evidence(
                    clean, source_root=temporary / "root"
                )

    def test_source_check_requires_the_exact_artifact_lock_contract(self) -> None:
        fixture = json.loads(
            (FIXTURES / "valid-ledger-minimal.json").read_text(encoding="utf-8")
        )
        fixture["baseline"]["artifact_lock"] = "asterion.other-lock/v1"  # type: ignore[index]
        ledger = validate_parity_ledger(fixture)

        with (
            mock.patch.object(
                parity_checker,
                "verify_prime_checkout",
                side_effect=AssertionError("checkout must not be inspected"),
            ),
            self.assertRaises(parity_checker.PrimeParityCheckError),
        ):
            parity_checker.verify_prime_source_evidence(
                ledger, source_root=PINNED_SOURCE
            )


if __name__ == "__main__":
    unittest.main()
