from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from collections.abc import Generator, Mapping, Sequence
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from asterion.control.parity import validate_parity_ledger
import tools.check_prime_parity as parity_checker
from tools.verify_native_controller_core import (
    EXPECTED_CONFORMANCE_SCENARIOS,
    EXPECTED_CRASH_POINTS,
    EXPECTED_DIFFERENTIAL_CASES,
    EXPECTED_NATIVE_CONTROLLER_CORE_REPORT,
    NativeControllerCoreVerificationError,
    build_native_controller_core_report,
    main,
    render_native_controller_core_report,
)


ROOT = Path(__file__).resolve().parents[1]


def _ledger() -> Mapping[str, object]:
    return parity_checker.load_prime_parity_ledger()


def _mutable_ledger() -> dict[str, object]:
    return json.loads(
        parity_checker.default_ledger_path().read_text(encoding="utf-8")
    )


def _load_ledger(_path: Path | None = None) -> Mapping[str, object]:
    return _ledger()


def _observations(
    *,
    scenario_id: str = "complete",
    case_id: str = "lifecycle-order",
    crash_point: str = "command-before-publish",
    status: str = "PASS",
    provider_operations: int = 0,
) -> Mapping[str, Sequence[Mapping[str, object]]]:
    counters = {
        "provider_operations": provider_operations,
        "model_operations": 0,
        "credential_reads": 0,
        "network_operations": 0,
        "application_operations": 0,
        "upload_operations": 0,
    }
    return {
        "conformance": (
            {"scenario_id": scenario_id, "status": status, **counters},
        ),
        "differential": (
            {"case_id": case_id, "status": status, **counters},
        ),
        "crash": (
            {
                "crash_point": crash_point,
                "status": status,
                "duplicate_commands": 0,
                "duplicate_turns": 0,
                "duplicate_actions": 0,
                "sequence_gaps": 0,
                "terminal_count": 1,
                "owned_processes_after_close": 0,
                **counters,
            },
        ),
    }


def _full_observations() -> Mapping[str, Sequence[Mapping[str, object]]]:
    counters = {
        "provider_operations": 0,
        "model_operations": 0,
        "credential_reads": 0,
        "network_operations": 0,
        "application_operations": 0,
        "upload_operations": 0,
    }
    return {
        "conformance": tuple(
            {"scenario_id": scenario_id, "status": "PASS", **counters}
            for scenario_id in EXPECTED_CONFORMANCE_SCENARIOS
        ),
        "differential": tuple(
            {"case_id": case_id, "status": "PASS", **counters}
            for case_id in EXPECTED_DIFFERENTIAL_CASES
        ),
        "crash": tuple(
            {
                "crash_point": crash_point,
                "status": "PASS",
                "duplicate_commands": 0,
                "duplicate_turns": 0,
                "duplicate_actions": 0,
                "sequence_gaps": 0,
                "terminal_count": 1,
                "owned_processes_after_close": 0,
                **counters,
            }
            for crash_point in EXPECTED_CRASH_POINTS
        ),
    }


class _ImmediateAwaitable:
    def __init__(self, value: object) -> None:
        self._value = value

    def __await__(self) -> Generator[object, None, object]:
        async def resolve() -> object:
            return self._value

        return resolve().__await__()


class TestNativeControllerCoreVerification(unittest.TestCase):
    def test_report_closes_only_core_and_keeps_all_native_rows_missing(self) -> None:
        report = build_native_controller_core_report(ROOT)

        self.assertEqual(report, EXPECTED_NATIVE_CONTROLLER_CORE_REPORT)
        self.assertEqual(report["claim"], "native-controller-core")
        self.assertEqual(report["common_scenarios"], 10)
        self.assertEqual(report["differential_cases"], 5)
        self.assertEqual(report["crash_points"], 8)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["model_operations"], 0)
        self.assertEqual(report["credential_reads"], 0)
        self.assertEqual(report["network_operations"], 0)
        self.assertEqual(report["application_operations"], 0)
        self.assertEqual(report["upload_operations"], 0)
        self.assertEqual(report["native_mandatory_total"], 61)
        self.assertEqual(report["native_mandatory_missing"], 61)
        self.assertEqual(report["promoted_feature_ids"], [])

    def test_cli_prints_the_exact_canonical_report(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            output.getvalue(),
            json.dumps(
                EXPECTED_NATIVE_CONTROLLER_CORE_REPORT,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )

    def test_script_entrypoint_prints_the_exact_canonical_report(self) -> None:
        process = subprocess.run(
            [sys.executable, "tools/verify_native_controller_core.py"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(
            process.stdout,
            json.dumps(
                EXPECTED_NATIVE_CONTROLLER_CORE_REPORT,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )

    def test_default_runner_accepts_custom_non_coroutine_awaitable_helpers(self) -> None:
        observations = _full_observations()
        modules = {
            "tests.test_native_control_conformance": SimpleNamespace(
                run_native_conformance_observations=lambda: _ImmediateAwaitable(
                    observations["conformance"]
                )
            ),
            "tests.test_native_prime_differential": SimpleNamespace(
                run_native_prime_differential_observations=lambda: _ImmediateAwaitable(
                    observations["differential"]
                )
            ),
            "tests.test_native_control_process_recovery": SimpleNamespace(
                run_native_crash_observations=lambda: _ImmediateAwaitable(
                    observations["crash"]
                )
            ),
        }

        with mock.patch(
            "tools.verify_native_controller_core.importlib.import_module",
            side_effect=lambda module_name: modules[module_name],
        ):
            report = build_native_controller_core_report(
                ROOT,
                ledger_loader=_load_ledger,
            )

        self.assertEqual(report, EXPECTED_NATIVE_CONTROLLER_CORE_REPORT)

    def test_render_rejects_noncanonical_report_shape(self) -> None:
        with self.assertRaises(NativeControllerCoreVerificationError):
            render_native_controller_core_report(
                {**EXPECTED_NATIVE_CONTROLLER_CORE_REPORT, "extra": 0}
            )

    def test_malformed_ledger_and_accidental_native_pass_are_rejected(self) -> None:
        with self.assertRaises(NativeControllerCoreVerificationError):
            build_native_controller_core_report(
                ROOT,
                ledger_loader=lambda _path=None: validate_parity_ledger({}),
                observation_runner=lambda: _observations(),
            )

        value = _mutable_ledger()
        features = value["features"]
        assert isinstance(features, list)
        first = features[0]
        assert isinstance(first, dict)
        results = first["provider_results"]
        assert isinstance(results, list)
        native_result = results[0]
        assert isinstance(native_result, dict)
        native_result["status"] = "provider-free-pass"
        native_result["evidence_ids"] = ["evidence.native.accidental"]

        with self.assertRaises(NativeControllerCoreVerificationError):
            build_native_controller_core_report(
                ROOT,
                ledger_loader=lambda _path=None: validate_parity_ledger(value),
                observation_runner=lambda: _observations(),
            )

    def test_observations_reject_missing_wrong_nonpass_nonzero_and_open_shapes(
        self,
    ) -> None:
        cases = (
            (
                "wrong-scenario",
                lambda: _observations(scenario_id="missing"),
            ),
            (
                "wrong-case",
                lambda: _observations(case_id="missing"),
            ),
            (
                "wrong-crash",
                lambda: _observations(crash_point="missing"),
            ),
            (
                "non-pass",
                lambda: _observations(status="FAIL"),
            ),
            (
                "nonzero-counter",
                lambda: _observations(provider_operations=1),
            ),
            (
                "open-shape",
                lambda: {
                    **_observations(),
                    "conformance": (
                        {
                            **_observations()["conformance"][0],
                            "private_path": str(ROOT),
                        },
                    ),
                },
            ),
        )
        for label, runner in cases:
            with self.subTest(label=label):
                with self.assertRaises(NativeControllerCoreVerificationError):
                    build_native_controller_core_report(
                        ROOT,
                        ledger_loader=_load_ledger,
                        observation_runner=runner,
                    )

    def test_missing_harness_module_and_secret_path_errors_are_redacted(self) -> None:
        output = io.StringIO()
        with (
            mock.patch(
                "tools.verify_native_controller_core.importlib.import_module",
                side_effect=ModuleNotFoundError(str(ROOT) + "/SENTINEL_SECRET"),
            ),
            redirect_stdout(output),
        ):
            exit_code = main([])

        rendered = output.getvalue()
        self.assertEqual(exit_code, 2)
        report = json.loads(rendered)
        self.assertEqual(report["status"], "ERROR")
        self.assertEqual(report["reason_codes"], ["verification-invalid"])
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn("SENTINEL_SECRET", rendered)

    def test_full_native_parity_remains_blocked_with_all_mandatory_ids(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = parity_checker.main(
                [
                    "--claim",
                    "verified-system-parity",
                    "--provider",
                    "asterion.native",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["blocking_feature_count"], 61)
        self.assertEqual(report["passed_feature_count"], 0)
        self.assertEqual(report["excluded_feature_count"], 2)
        self.assertEqual(len(report["blocking_feature_ids"]), 61)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["application_operations"], 0)


if __name__ == "__main__":
    unittest.main()
