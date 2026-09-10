"""Supported-Python imports and non-reaping worker liveness on macOS."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

_PYTHON310 = (
    sys.executable if sys.version_info[:2] == (3, 10) else shutil.which("python3.10")
)


class TestP1PortableImports(unittest.TestCase):
    @unittest.skipUnless(_PYTHON310, "Python 3.10 is not installed")
    def test_python310_capability_package_import(self) -> None:
        assert _PYTHON310 is not None
        source = str(Path(__file__).resolve().parents[1] / "src")
        result = subprocess.run(
            [
                _PYTHON310,
                "-I",
                "-c",
                f"import sys; sys.path.insert(0, {source!r}); import asterion.capability_packages.model",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(
        _PYTHON310,
        "Python 3.10 is not installed",
    )
    def test_python310_native_worker_import(self) -> None:
        assert _PYTHON310 is not None
        source = str(Path(__file__).resolve().parents[1] / "src")
        result = subprocess.run(
            [
                _PYTHON310,
                "-I",
                "-c",
                f"import sys; sys.path.insert(0, {source!r}); import asterion.applications.prime.p1.ipython_host",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(
    hasattr(select, "kqueue"), "requires macOS/BSD process observation"
)
class TestP1PortableLiveness(unittest.IsolatedAsyncioTestCase):
    async def test_observer_registration_failure_closes_descriptor_and_reaps_worker(
        self,
    ) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.worker import P1WorkerError

        descriptor = select.kqueue()
        failed_watch = Mock(wraps=descriptor)
        failed_watch.control.side_effect = OSError("sentinel-observer-registration")
        worker = P1WorkerProcess(deadline=time.monotonic() + 10)
        try:
            with (
                patch.object(select, "kqueue", return_value=failed_watch),
                patch.object(os, "waitid", None, create=True),
            ):
                with self.assertRaisesRegex(
                    P1WorkerError, "^P1 worker start failed$"
                ) as caught:
                    await worker.start()
            self.assertIsNone(caught.exception.__context__)
            self.assertTrue(descriptor.closed)
            cleanup = worker.cleanup_receipt
            assert cleanup is not None
            self.assertTrue(cleanup.reaped)
            self.assertTrue(cleanup.pipes_closed)
            self.assertTrue(cleanup.root_removed)
            self.assertEqual(cleanup.reap_count, 1)
        finally:
            descriptor.close()
            await worker.close()

    async def test_missing_exit_primitives_reject_before_process_creation(self) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.worker import P1WorkerError

        with (
            patch.object(select, "kqueue", None),
            patch.object(os, "waitid", None, create=True),
        ):
            with self.assertRaises(P1WorkerError):
                P1WorkerProcess(deadline=time.monotonic() + 10)

    async def test_missing_waitid_preserves_live_worker_and_rejects_unreaped_exit(
        self,
    ) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.worker import P1WorkerError

        with patch.object(os, "waitid", None, create=True):
            worker = P1WorkerProcess(deadline=time.monotonic() + 10)
            await worker.start()
            try:
                process = worker._process
                assert process is not None
                with (
                    patch.object(
                        process, "poll", side_effect=AssertionError("poll steals reap")
                    ),
                    patch.object(
                        process, "wait", side_effect=AssertionError("wait steals reap")
                    ),
                    patch.object(
                        os, "waitpid", side_effect=AssertionError("waitpid steals reap")
                    ),
                ):
                    try:
                        token = worker.validate_lifecycle()
                    except P1WorkerError:
                        self.fail(
                            "a live owned worker must support Python without os.waitid"
                        )
                    self.assertIs(worker.validate_lifecycle(), token)
                    self.assertIsNone(process.returncode)
                    self.assertEqual(worker._reap_count, 0)
                    os.kill(process.pid, signal.SIGKILL)
                    # Wait for kernel/pipe exit observation, without any wait/reap call.
                    for _ in range(100):
                        await asyncio.sleep(0.01)
                        try:
                            worker.validate_lifecycle()
                        except P1WorkerError:
                            break
                    else:
                        self.fail("an exited owned worker must be rejected")
                    self.assertTrue(worker._has_exited(process))
                    self.assertIsNone(process.returncode)
                    self.assertEqual(worker._reap_count, 0)
            finally:
                try:
                    cleanup = await worker.close()
                except P1WorkerError:
                    self.fail("cleanup must reap an already exited owned worker")
                self.assertTrue(cleanup.reaped)
                self.assertTrue(cleanup.pipes_closed)
                self.assertTrue(cleanup.root_removed)
                self.assertEqual(cleanup.reap_count, 1)
                self.assertIsNone(worker._exit_watch)
                self.assertIs(await worker.close(), cleanup)

    async def test_unavailable_waitid_uses_supported_process_observer(self) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.worker import P1WorkerError

        with patch.object(os, "waitid", side_effect=NotImplementedError, create=True):
            worker = P1WorkerProcess(deadline=time.monotonic() + 10)
            await worker.start()
            try:
                try:
                    worker.validate_lifecycle()
                except P1WorkerError:
                    self.fail(
                        "platform process observation must not require an unavailable waitid"
                    )
            finally:
                await worker.close()
