"""P5 operator: env-driven success + limits witness.

The operator is the sole bridge between the P5 native implementation and
the Makefile ``asterion-prime-p5-run`` / ``-run-limits`` supervisors
(Task 9 will add those targets). Three invariants anchor it:

* ``success`` mode emits exactly one JSON line with
  ``status="completed"``, ``terminal_reason="success"``,
  ``propose_step_count=1``, ``verify_step_count=2``,
  ``repair_step_count=1``, ``failed_verify_count=1``, and a non-null
  ``receipt_sha256``.
* ``limits`` mode emits three JSON lines, in fixed order, with
  scenarios ``iteration-cap`` / ``duration-cap`` / ``no-progress`` —
  each carrying a closed-enum ``terminal_reason`` and a non-null
  ``receipt_sha256``. Per D-2026-09-19-01 cancellation folds into the
  closed ``terminal_reason`` enum but is NOT a separately-asserted
  witness record, so the limits path emits exactly three records, not
  four.
* An unrecognised ``ASTERION_PRIME_P5_MODE`` causes the operator to
  exit non-zero (preflight gate).

Four tests back this contract:

* :class:`P5OperatorSuccess` runs the operator in ``success`` mode and
  asserts the success-path wire format.
* :class:`P5OperatorLimits` runs in ``limits`` mode and asserts the
  three refusal records are emitted in spec order.
* :class:`P5OperatorUnknownMode` exercises the preflight gate for an
  unrecognised ``ASTERION_PRIME_P5_MODE``.
* :class:`P5OperatorNoSpawnOnCancellation` asserts that the
  ``cancelled`` terminal_reason does NOT cause a fourth refusal record
  to be emitted on the limits path (per D-2026-09-19-01).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType
import unittest

from asterion.applications.prime.p5.operator import (
    P5LimitsRecord,
    P5OperatorError,
    P5PublicResult,
    _build_resources,
    _invoke_composed_loop,
    _preflight,
    run_limits_path,
    run_success_path,
)


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P5_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P5_MODE"


def _subprocess_env(
    *, operator_root: Path, private_root: Path, mode: str
) -> dict[str, str]:
    env = dict(os.environ)
    env[_OPERATOR_ROOT_ENV] = str(operator_root)
    env[_PRIVATE_ROOT_ENV] = str(private_root)
    env[_MODE_ENV] = mode
    env["LANG"] = "C.UTF-8"
    return env


def _run_operator_subprocess(
    *, operator_root: Path, private_root: Path, mode: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-m", "asterion.applications.prime.p5.operator"],
        capture_output=True,
        text=True,
        timeout=60,
        env=_subprocess_env(
            operator_root=operator_root, private_root=private_root, mode=mode
        ),
        cwd=str(operator_root),
    )


def _parse_stdout_lines(
    completed: subprocess.CompletedProcess[str],
) -> list[dict[str, object]]:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, (
        f"operator stdout empty; stderr={completed.stderr!r}, "
        f"rc={completed.returncode}"
    )
    parsed: list[dict[str, object]] = []
    for line in lines:
        record = json.loads(line)
        assert isinstance(record, dict), f"operator line is not a dict: {line!r}"
        parsed.append(record)
    return parsed


class P5OperatorSuccess(unittest.TestCase):
    """Run operator in success mode and assert the one-line JSON wire."""

    def test_success_path_emits_completed_json_with_one_repair(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-success-test"
            completed = _run_operator_subprocess(
                operator_root=operator_root,
                private_root=private_root,
                mode="success",
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"success rc={completed.returncode}; "
                f"stderr={completed.stderr!r}",
            )
            records = _parse_stdout_lines(completed)
            self.assertEqual(len(records), 1, "success mode emits exactly one record")
            record = records[0]
            self.assertEqual(record["status"], "completed")
            # Success-path witness invariants (per P5 plan §"Task 8"):
            # 1 propose → 1 verify-fail → 1 repair → 1 verify-pass.
            self.assertEqual(record["propose_step_count"], 1)
            self.assertEqual(record["verify_step_count"], 2)
            self.assertEqual(record["repair_step_count"], 1)
            self.assertEqual(record["failed_verify_count"], 1)
            self.assertEqual(record["terminal_reason"], "success")
            self.assertEqual(record["root_generation"], 1)
            self.assertEqual(record["private_root_redacted"], True)
            # Required non-null fields.
            root_run_id = record["root_run_id"]
            assert isinstance(root_run_id, str) and root_run_id
            joined_digest = record["joined_workspace_digest"]
            assert isinstance(joined_digest, str) and len(joined_digest) == 64
            receipt_sha = record["receipt_sha256"]
            assert isinstance(receipt_sha, str) and len(receipt_sha) == 64


class P5OperatorLimits(unittest.TestCase):
    """Run operator in limits mode and assert three refusal records in order."""

    def test_limits_path_emits_three_refusal_records(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-limits-test"
            completed = _run_operator_subprocess(
                operator_root=operator_root,
                private_root=private_root,
                mode="limits",
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"limits rc={completed.returncode}; "
                f"stderr={completed.stderr!r}",
            )
            records = _parse_stdout_lines(completed)
            self.assertEqual(
                len(records), 3, "limits mode emits exactly three records"
            )
            scenarios = [record["scenario"] for record in records]
            self.assertEqual(
                scenarios,
                ["iteration-cap", "duration-cap", "no-progress"],
            )
            expected_reasons = [
                "iteration-cap-exceeded",
                "duration-cap-exceeded",
                "no-progress",
            ]
            for record, expected_reason in zip(records, expected_reasons):
                self.assertEqual(record["status"], "refused")
                self.assertEqual(record["terminal_reason"], expected_reason)
                self.assertEqual(record["private_root_redacted"], True)
                self.assertIsNotNone(record["receipt_sha256"])
                receipt_sha = record["receipt_sha256"]
                assert isinstance(receipt_sha, str)
                self.assertEqual(len(receipt_sha), 64)
                joined_digest = record["joined_workspace_digest"]
                if expected_reason == "no-progress":
                    # The no-progress scenario's joined_workspace_digest
                    # equals the propose digest (per the dedup-adapter).
                    # The other two scenarios have non-null joined_digest.
                    assert isinstance(joined_digest, str)
                    self.assertEqual(len(joined_digest), 64)
                else:
                    assert isinstance(joined_digest, str)
                    self.assertEqual(len(joined_digest), 64)


class P5OperatorUnknownMode(unittest.TestCase):
    """Preflight gate rejects unrecognised ``ASTERION_PRIME_P5_MODE``."""

    def test_operator_exits_nonzero_on_unknown_mode(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-unknown-test"
            env = _subprocess_env(
                operator_root=operator_root,
                private_root=private_root,
                mode="garbage",
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-m", "asterion.applications.prime.p5.operator"],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
                cwd=str(operator_root),
            )
            self.assertNotEqual(
                completed.returncode,
                0,
                f"unknown mode should exit non-zero; "
                f"rc={completed.returncode}, stderr={completed.stderr!r}",
            )
            # In-process verification: preflight raises on unknown mode.
            with self.assertRaises(P5OperatorError):
                _preflight(
                    MappingProxyType(
                        {
                            _OPERATOR_ROOT_ENV: str(operator_root),
                            _PRIVATE_ROOT_ENV: str(private_root),
                            _MODE_ENV: "garbage",
                        }
                    )
                )


class P5OperatorNoSpawnOnCancellation(unittest.TestCase):
    """Per D-2026-09-19-01 cancellation is a closed-enum terminal_reason
    value but NOT a separately-asserted witness record. The limits path
    must NOT emit a fourth ``cancelled`` record.
    """

    def test_no_spawn_when_terminal_reason_is_cancelled(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-no-spawn-cancel-test"
            completed = _run_operator_subprocess(
                operator_root=operator_root,
                private_root=private_root,
                mode="limits",
            )
            self.assertEqual(completed.returncode, 0)
            records = _parse_stdout_lines(completed)
            self.assertEqual(
                len(records),
                3,
                "limits mode emits exactly three records "
                "(cancellation is folded into the closed enum, not a "
                "4th scenario)",
            )
            scenarios = [record["scenario"] for record in records]
            self.assertNotIn(
                "cancellation",
                scenarios,
                "cancellation is not a separate witness scenario per "
                "D-2026-09-19-01",
            )

    def test_limits_in_process_no_cancellation_record(self) -> None:
        """In-process check: the limits path produces exactly three
        refusal records with no ``cancellation`` scenario.
        """

        import asyncio

        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-no-spawn-in-process"
            env = MappingProxyType(
                {
                    _OPERATOR_ROOT_ENV: str(operator_root),
                    _PRIVATE_ROOT_ENV: str(private_root),
                    _MODE_ENV: "limits",
                }
            )
            preflight = _preflight(env)

            async def _drive() -> list[dict[str, object]]:
                resources = await _build_resources(preflight)
                return await _invoke_composed_loop(resources)

            records = asyncio.run(_drive())
            self.assertEqual(len(records), 3)
            scenarios = [record["scenario"] for record in records]
            self.assertEqual(
                scenarios,
                ["iteration-cap", "duration-cap", "no-progress"],
            )
            self.assertNotIn("cancellation", scenarios)


class P5OperatorPublicResultShape(unittest.TestCase):
    """Verify the public result dataclasses carry exactly the wire fields."""

    def test_success_dataclass_field_set(self) -> None:
        from dataclasses import fields as dc_fields

        names = {f.name for f in dc_fields(P5PublicResult)}
        self.assertEqual(
            names,
            {
                "status",
                "root_run_id",
                "root_generation",
                "propose_step_count",
                "verify_step_count",
                "repair_step_count",
                "failed_verify_count",
                "terminal_reason",
                "joined_workspace_digest",
                "receipt_sha256",
                "private_root_redacted",
            },
        )

    def test_limits_dataclass_field_set(self) -> None:
        from dataclasses import fields as dc_fields

        names = {f.name for f in dc_fields(P5LimitsRecord)}
        self.assertEqual(
            names,
            {
                "status",
                "scenario",
                "terminal_reason",
                "verify_step_count",
                "repair_step_count",
                "failed_verify_count",
                "last_step_timed_out",
                "joined_workspace_digest",
                "receipt_sha256",
                "private_root_redacted",
            },
        )


class P5OperatorRunFunctions(unittest.TestCase):
    """In-process entry points: ``run_success_path`` and ``run_limits_path``.

    These are exposed for the Makefile supervisor and the unit-test
    driver. Both return an int exit code (0 success, 2 preflight, 1 error).
    """

    def test_run_success_path_in_process(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-run-success"
            env = MappingProxyType(
                {
                    _OPERATOR_ROOT_ENV: str(operator_root),
                    _PRIVATE_ROOT_ENV: str(private_root),
                    _MODE_ENV: "success",
                }
            )
            # The function emits to stdout. Capture via redirect.
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_success_path(dict(env))
            self.assertEqual(rc, 0)
            lines = [line for line in buf.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["terminal_reason"], "success")

    def test_run_limits_path_in_process(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p5-run-limits"
            env = MappingProxyType(
                {
                    _OPERATOR_ROOT_ENV: str(operator_root),
                    _PRIVATE_ROOT_ENV: str(private_root),
                    _MODE_ENV: "limits",
                }
            )
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run_limits_path(dict(env))
            self.assertEqual(rc, 0)
            lines = [line for line in buf.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 3)
            scenarios = [json.loads(line)["scenario"] for line in lines]
            self.assertEqual(
                scenarios, ["iteration-cap", "duration-cap", "no-progress"]
            )


if __name__ == "__main__":
    unittest.main()
