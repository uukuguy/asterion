"""P3's operator preset executes through the selected application runner."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p3 import operator
from asterion.runner.application import ApplicationRunError


class PrimeP3ComposedRuntimeTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
