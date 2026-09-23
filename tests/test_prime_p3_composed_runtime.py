"""P3's operator preset executes through the selected application runner."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p3 import operator
from asterion.runner.application import ApplicationRunError
from asterion.applications.prime.p3.runtime_binding import (
    P3_RUNTIME_OPTIONS,
    _P3RuntimeSession,
    build_p3_runtime,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import RunRequest


class _MutableSignal:
    cancelled = False


class _SlowHost:
    async def run_root(self, *, parent_run_id, child_request, signal):
        await asyncio.sleep(0.05)

    async def wait_finalization(self, *, signal):
        raise AssertionError("deadline must stop before finalization")


class PrimeP3ComposedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_binding_rejects_declared_child_runner_drift_before_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = await operator._build_resources(
                operator._Preflight(root, Path(sys.executable), root / "private", "success", None)
            )
            backend = operator._OperatorP3RuntimeHost(resources)
            services = {
                "prime.child-runner": await operator._open_child_runner(),
                "prime.p3-oracle": resources.p3_oracle,
                "prime.pi-extension": resources.pi_extension,
                "prime.private-trace": resources.private_trace,
                "prime.session-backend": backend,
            }
            with self.assertRaises(RuntimeFactoryError):
                build_p3_runtime(
                    RuntimeFactoryContext(
                        "prime-applications", "prime.recursive-workflow", "1.0.0",
                        "asterion.prime", root / "assembly.json", P3_RUNTIME_OPTIONS,
                        services,
                    )
                )
            self.assertIsNone(backend.result)

    async def test_runtime_deadline_bounds_host_work(self) -> None:
        session = _P3RuntimeSession(
            session_backend=_SlowHost(), child_runner=object(),
            oracle=object(), private_trace=None,
        )
        request = RunRequest(
            run_id="p3-slow", input_text="fixed-recursive-workflow",
            requested_capabilities=(), deadline_ms=5,
        )
        with self.assertRaises(TimeoutError):
            [event async for event in session.run(request, signal=_MutableSignal())]

    async def test_selected_workflow_calls_host_and_returns_its_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = await operator._build_resources(
                operator._Preflight(root, Path(sys.executable), root / "private", "success", None)
            )
            with patch.object(operator, "_drive_success", wraps=operator._drive_success) as drive:
                public = await operator._invoke_composed_success(resources)
            self.assertEqual(drive.await_count, 1)
            self.assertEqual(public.status, "completed")
            self.assertEqual(len(public.receipt_sha256), 64)
            self.assertEqual(public.depth_reached, 2)

    async def test_host_failure_cannot_be_projected_as_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = await operator._build_resources(
                operator._Preflight(root, Path(sys.executable), root / "private", "success", None)
            )
            with patch.object(operator, "_drive_success", side_effect=RuntimeError("SENTINEL")):
                with self.assertRaises(ApplicationRunError) as raised:
                    await operator._invoke_composed_success(resources)
            self.assertEqual(str(raised.exception), "application capability execution failed")
            self.assertNotIn("SENTINEL", str(raised.exception))

    async def test_cancellation_after_host_work_does_not_sign_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = await operator._build_resources(
                operator._Preflight(root, Path(sys.executable), root / "private", "success", None)
            )
            original = operator._drive_success

            async def cancel_after_work(resources, signal):
                result = await original(resources, signal)
                signal.cancelled = True
                return result

            with patch.object(operator, "_drive_success", side_effect=cancel_after_work):
                with self.assertRaises(asyncio.CancelledError):
                    await operator._invoke_composed_success(resources, _MutableSignal())


if __name__ == "__main__":
    unittest.main()
