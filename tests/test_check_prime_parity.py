from __future__ import annotations

import io
import json
import os
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


def pinned_prime_source_root() -> Path:
    configured = os.environ.get("ASTERION_PRIME_SOURCE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return PINNED_SOURCE


def _ledger(name: str = "prime-agent-0.7.1.json"):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return validate_parity_ledger(value)


class TestCheckPrimeParity(unittest.TestCase):
    @unittest.skipUnless(
        pinned_prime_source_root().is_dir(),
        "external pinned Prime source checkout is unavailable",
    )
    def test_explicit_source_check_proves_every_declared_file_and_anchor(self) -> None:
        prime_source = pinned_prime_source_root()
        report = parity_checker.verify_prime_source_evidence(
            _ledger(), source_root=prime_source
        )

        self.assertEqual(report.source_commit, PINNED_COMMIT)
        self.assertEqual(report.feature_count, 63)
        self.assertEqual(report.evidence_record_count, 70)
        self.assertEqual(report.file_count, 48)
        self.assertEqual(report.anchor_count, 76)
        self.assertNotIn(str(prime_source), repr(report))

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

    def test_verified_system_claim_passes_only_with_closed_union(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--claim",
                    "verified-system-parity",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        rendered = output.getvalue()
        report = json.loads(rendered)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["passed_feature_count"], 61)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["blocking_feature_ids"], [])
        self.assertEqual(report["excluded_feature_count"], 2)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["application_operations"], 0)
        self.assertNotIn("prime_evidence", rendered)
        self.assertNotIn("anchors", rendered)
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn(PINNED_COMMIT, rendered)

    def test_domain_report_is_provider_specific_and_reports_closed_domain(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--domain",
                    "session.context",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["claim"], "feature-parity")
        self.assertEqual(report["selection_kind"], "domain")
        self.assertEqual(report["selection_id"], "session.context")
        self.assertEqual(report["selected_feature_count"], 9)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["blocking_feature_ids"], [])
        self.assertEqual(report["passed_feature_count"], 9)
        self.assertEqual(report["reason_codes"], [])
        self.assertEqual(report["status"], "PASS")

    def test_interface_operation_features_close_without_system_parity(self) -> None:
        selected = (
            "interface.sdk,interface.cli-interactive,interface.rpc,interface.acp,"
            "interface.json-stream,interface.headless-print,interface.tui-commands,"
            "interface.tui-extension-ui,interface.export-share"
        )
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                ["--features", selected, "--provider", "asterion.prime-gateway"]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["selected_feature_count"], 9)
        self.assertEqual(report["passed_feature_count"], 9)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["application_operations"], 0)

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--domain",
                    "interfaces.operations",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["selected_feature_count"], 15)
        self.assertEqual(report["passed_feature_count"], 15)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["blocking_feature_ids"], [])
        self.assertEqual(report["reason_codes"], [])
        self.assertEqual(report["status"], "PASS")

        selected = (
            "operation.auth,operation.model-selection,"
            "operation.settings-keybindings,operation.telemetry-usage,"
            "operation.doctor,operation.controlled-update-restart"
        )
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                ["--features", selected, "--provider", "asterion.prime-gateway"]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["selected_feature_count"], 6)
        self.assertEqual(report["passed_feature_count"], 6)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["status"], "PASS")

    def test_continual_harness_domain_closes_only_with_seven_plus_one(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--domain",
                    "harness.continual",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["selected_feature_count"], 8)
        self.assertEqual(report["passed_feature_count"], 8)
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["status"], "PASS")

    def test_feature_report_canonicalizes_exact_phase1_passing_selection(
        self,
    ) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--features",
                    "operation.goals,operation.detach-attach-replay",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["selection_kind"], "features")
        self.assertEqual(
            report["selected_feature_ids"],
            [
                "operation.detach-attach-replay",
                "operation.goals",
            ],
        )
        self.assertEqual(report["blocking_feature_count"], 0)
        self.assertEqual(report["passed_feature_count"], 2)
        self.assertEqual(report["reason_codes"], [])
        self.assertEqual(report["status"], "PASS")

    def test_invalid_feature_selection_returns_one_fixed_redacted_object(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--features",
                    "session.delivery,SENTINEL_SECRET",
                    "--provider",
                    "asterion.prime-gateway",
                ]
            )

        rendered = output.getvalue()
        report = json.loads(rendered)
        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "ERROR")
        self.assertEqual(report["reason_codes"], ["selection-invalid"])
        self.assertNotIn("SENTINEL_SECRET", rendered)

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
