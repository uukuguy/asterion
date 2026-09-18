"""P3 operator: env-driven success + limits witness.

The operator is the sole bridge between the P3 native implementation and
the Makefile ``asterion-prime-p3-run`` / ``-run-limits`` supervisors. Two
invariants anchor it:

* ``success`` mode emits exactly one JSON line with ``status="completed"``,
  ``depth_reached=2``, ``child_generation == root_generation + 1``, and a
  non-null ``receipt_sha256``.
* ``limits`` mode emits four JSON lines, in fixed order, with scenarios
  ``depth`` / ``concurrency`` / ``budget`` / ``cancellation`` — each
  carrying the closed-enum ``refusal_reason`` and a non-null
  ``receipt_sha256``. Admission must NOT spawn a worker payload on a
  refused attempt.

Four tests back this contract:

* :class:`P3OperatorSuccess` runs the operator in ``success`` mode and
  asserts the success-path wire format.
* :class:`P3OperatorLimits` runs in ``limits`` mode and asserts the four
  refusal records are emitted in spec order.
* :class:`P3OperatorUnknownMode` exercises the preflight gate for an
  unrecognised ``ASTERION_PRIME_P3_MODE``.
* :class:`P3OperatorNoSpawnOnRefusal` asserts that admission refusals on
  the limits path do NOT cause the deterministic fake-worker to fire.
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

from asterion.applications.prime.p3.operator import (
    P3LimitsRecord,
    P3OperatorError,
    P3PublicResult,
    _build_resources,
    _invoke_composed_root_async,
    _preflight,
    run_limits_path,
    run_success_path,
)


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P3_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P3_MODE"


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
        [sys.executable, "-I", "-m", "asterion.applications.prime.p3.operator"],
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


class P3OperatorSuccess(unittest.TestCase):
    """Run operator in success mode and assert the one-line JSON wire."""

    def test_success_path_emits_completed_json_with_child_joined(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-success-test"
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
            self.assertEqual(record["depth_reached"], 2)
            self.assertEqual(record["refusal_reason"], None)
            self.assertEqual(record["private_root_redacted"], True)
            # Child invariants: admitted and joined.
            self.assertIsNotNone(record["child_run_id"])
            child_run_id = record["child_run_id"]
            assert isinstance(child_run_id, str)
            self.assertIsNotNone(record["child_result_sha256"])
            self.assertIsNotNone(record["joined_result_sha256"])
            self.assertIsNotNone(record["receipt_sha256"])
            # Generation monotonicity: child = root + 1.
            self.assertEqual(
                record["child_generation"], record["root_generation"] + 1
            )
            self.assertEqual(record["root_generation"], 1)
            self.assertEqual(record["child_generation"], 2)
            # child_result_sha256 must differ from root_result_sha256.
            # root_result_sha256 is not surfaced; assert child SHA differs
            # from the joined-result SHA instead (both are derived from
            # different canonical payloads).
            assert isinstance(record["child_result_sha256"], str)
            assert isinstance(record["joined_result_sha256"], str)
            self.assertNotEqual(
                record["child_result_sha256"], record["joined_result_sha256"]
            )


class P3OperatorLimits(unittest.TestCase):
    """Run operator in limits mode and assert four refusal records in order."""

    def test_limits_path_emits_four_refusal_records(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-limits-test"
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
            self.assertEqual(len(records), 4, "limits mode emits exactly four records")
            scenarios = [record["scenario"] for record in records]
            self.assertEqual(
                scenarios,
                ["depth", "concurrency", "budget", "cancellation"],
            )
            expected_refusals = [
                "depth-exceeded",
                "concurrency-exceeded",
                "budget-exceeded",
                "cancelled",
            ]
            for record, expected_reason in zip(records, expected_refusals):
                self.assertEqual(record["status"], "refused")
                self.assertEqual(record["refusal_reason"], expected_reason)
                self.assertEqual(record["private_root_redacted"], True)
                self.assertIsNotNone(record["receipt_sha256"])
                receipt_sha = record["receipt_sha256"]
                assert isinstance(receipt_sha, str)
                self.assertEqual(len(receipt_sha), 64)


class P3OperatorUnknownMode(unittest.TestCase):
    """Preflight gate rejects unrecognised ``ASTERION_PRIME_P3_MODE``."""

    def test_operator_exits_nonzero_on_unknown_mode(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-unknown-test"
            env = _subprocess_env(
                operator_root=operator_root,
                private_root=private_root,
                mode="garbage",
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-m", "asterion.applications.prime.p3.operator"],
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
            with self.assertRaises(P3OperatorError):
                _preflight(
                    MappingProxyType(
                        {
                            _OPERATOR_ROOT_ENV: str(operator_root),
                            _PRIVATE_ROOT_ENV: str(private_root),
                            _MODE_ENV: "garbage",
                        }
                    )
                )


class P3OperatorNoSpawnOnRefusal(unittest.TestCase):
    """Refused admissions on the limits path do not spawn a fake-worker."""

    def test_admission_refused_does_not_spawn_model(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-no-spawn-test"
            env = _subprocess_env(
                operator_root=operator_root,
                private_root=private_root,
                mode="limits",
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-m", "asterion.applications.prime.p3.operator"],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
                cwd=str(operator_root),
            )
            self.assertEqual(completed.returncode, 0)
            records = _parse_stdout_lines(completed)
            # Each refusal record is a single line carrying the refusal
            # reason and a receipt SHA. There are NO ``child_run_id``
            # fields (no admission succeeded), NO ``child_result_sha256``
            # fields (no worker payload was computed), and NO
            # ``joined_result_sha256`` fields. The schema is the
            # P3LimitsRecord dataclass: status, scenario,
            # refusal_reason, receipt_sha256, private_root_redacted.
            limits_keys = {
                "status",
                "scenario",
                "refusal_reason",
                "receipt_sha256",
                "private_root_redacted",
            }
            for record in records:
                self.assertEqual(set(record), limits_keys)
                self.assertNotIn("child_run_id", record)
                self.assertNotIn("child_result_sha256", record)
                self.assertNotIn("joined_result_sha256", record)

    def test_admission_refused_in_process_no_spawn(self) -> None:
        """In-process check: refused scenarios do not invoke the
        fake-worker payload computation. Each limit scenario's
        refusal record is sealed against the closed refusal tuple,
        not against a child_result_sha256.
        """

        import asyncio

        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-no-spawn-in-process"
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
                return await _invoke_composed_root_async(resources)

            records = asyncio.run(_drive())
            self.assertEqual(len(records), 4)
            for record in records:
                # No success-path fields present in any refusal record.
                self.assertNotIn("child_run_id", record)
                self.assertNotIn("child_result_sha256", record)
                self.assertNotIn("joined_result_sha256", record)
                self.assertNotIn("depth_reached", record)


class P3OperatorPublicResultShape(unittest.TestCase):
    """Verify the public result dataclasses carry exactly the wire fields."""

    def test_success_dataclass_field_set(self) -> None:
        from dataclasses import fields as dc_fields

        names = {f.name for f in dc_fields(P3PublicResult)}
        self.assertEqual(
            names,
            {
                "status",
                "root_run_id",
                "root_generation",
                "child_run_id",
                "child_generation",
                "child_result_sha256",
                "joined_result_sha256",
                "depth_reached",
                "refusal_reason",
                "receipt_sha256",
                "private_root_redacted",
            },
        )

    def test_limits_dataclass_field_set(self) -> None:
        from dataclasses import fields as dc_fields

        names = {f.name for f in dc_fields(P3LimitsRecord)}
        self.assertEqual(
            names,
            {
                "status",
                "scenario",
                "refusal_reason",
                "receipt_sha256",
                "private_root_redacted",
            },
        )


class P3OperatorRunFunctions(unittest.TestCase):
    """In-process entry points: ``run_success_path`` and ``run_limits_path``.

    These are exposed for the Makefile supervisor and the unit-test
    driver. Both return an int exit code (0 success, 2 preflight, 1 error).
    """

    def test_run_success_path_in_process(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-run-success"
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

    def test_run_limits_path_in_process(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p3-run-limits"
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
            self.assertEqual(len(lines), 4)
            scenarios = [json.loads(line)["scenario"] for line in lines]
            self.assertEqual(
                scenarios, ["depth", "concurrency", "budget", "cancellation"]
            )


if __name__ == "__main__":
    unittest.main()
