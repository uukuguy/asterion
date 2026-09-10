"""Provider-free tests of the installed persistent P1 worker boundary."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import os
from pathlib import Path
import time
import unittest
from unittest.mock import AsyncMock, patch


def setup_cell() -> str:
    return """import json
class AffineAccumulator:
    def __init__(self, multiplier, offset):
        self.multiplier = multiplier
        self.offset = offset
    def __call__(self, value):
        return self.multiplier * value + self.offset
accumulator = AffineAccumulator(input_tuple[0], input_tuple[1])
with open("stage-one.json", "w") as stream:
    stream.write(json.dumps({"input":list(input_tuple), "setup_value":accumulator(input_tuple[2])}, sort_keys=True, separators=(",", ":")) + "\\n")
"""


def verification_cell() -> str:
    return """import hashlib
with open("stage-one.json", "rb") as stream:
    verified_bytes = stream.read()
stage_one_verified = {"object_id":id(accumulator), "probe":accumulator(input_tuple[2]), "file_sha256":hashlib.sha256(verified_bytes).hexdigest()}
"""


def stage_two_cell() -> str:
    return """import json
with open("stage-one.json", "rb") as stream:
    preserved_bytes = stream.read()
preserved = json.loads(preserved_bytes)
final_result = accumulator(input_tuple[3]) + preserved["setup_value"]
"""


class TestP1WorkerContract(unittest.TestCase):
    def test_worker_module_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("asterion.applications.prime.p1"))

    def test_safe_checkpoint_and_cleanup_reject_private_fields(self) -> None:
        from asterion.applications.prime.p1.worker import (
            P1WorkerCheckpoint,
            P1WorkerCleanupReceipt,
            P1WorkerError,
        )

        for factory in (
            lambda: P1WorkerCheckpoint(
                "sentinel-private-path", 2, "a" * 64, "b" * 64, 1, 1, 2, 100, 20
            ),
            lambda: P1WorkerCleanupReceipt(
                "a" * 64, "sentinel-private-value", True, True, True, 1
            ),
        ):
            with self.subTest(factory=factory):
                with self.assertRaises(P1WorkerError) as caught:
                    factory()
                self.assertNotIn("sentinel", str(caught.exception))


class TestP1Worker(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if importlib.util.find_spec("asterion.applications.prime.p1") is None:
            self.skipTest("contract is not implemented yet")
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess

        self.worker = P1WorkerProcess(deadline=time.monotonic() + 20)
        await self.worker.start()
        self.addAsyncCleanup(self.worker.close)

    async def cell(
        self, code: str, request_id: str = "cell-1", turn_id: str = "turn-1"
    ):
        from asterion.applications.prime.p1.worker import P1CellRequest

        return await self.worker.execute_cell(P1CellRequest(request_id, turn_id, code))

    async def test_same_pid_namespace_and_object_across_independent_turns(self) -> None:
        initial = self.worker.snapshot()
        token = self.worker.validate_lifecycle()
        self.assertEqual(initial.seeded_symbols, ("input_tuple", "task_statement"))
        await self.cell(setup_cell())
        await self.cell(verification_cell(), "cell-2", "turn-2")
        snapshot = self.worker.snapshot()
        self.assertEqual(snapshot.identity, initial.identity)
        self.assertIs(self.worker.validate_lifecycle(), token)
        self.assertEqual(
            snapshot.cells[0].accumulator_id, snapshot.cells[1].accumulator_id
        )
        self.assertEqual(snapshot.cells[0].file_bytes, snapshot.cells[1].file_bytes)
        self.assertGreater(snapshot.cells[1].file_reads, 0)
        self.assertEqual(snapshot.cells[1].callable_probe, (40, 58))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(snapshot, "cells", ())

    async def test_ipython_profile_lives_under_exact_worker_root(self) -> None:
        root = self.worker._root
        assert root is not None
        self.assertTrue(Path(root.name, ".ipython").is_dir())

    async def test_duplicate_request_and_code_cap_reject_before_dispatch(self) -> None:
        from asterion.applications.prime.p1.worker import P1WorkerError

        await self.cell("marker = 1")
        for code in ("marker = 2", "#" * 16385):
            with self.subTest(code_length=len(code)):
                with self.assertRaisesRegex(
                    P1WorkerError, "P1 worker request rejected"
                ):
                    await self.cell(code)
        self.assertEqual(len(self.worker.snapshot().cells), 1)
        self.worker.validate_lifecycle()

    async def test_forbidden_cells_fail_closed_and_poison(self) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.worker import P1CellRequest, P1WorkerError

        for code in (
            "open('../sentinel-secret')",
            "open('/etc/passwd')",
            "import os",
            "import subprocess",
            "import socket",
            "import ctypes",
            "import os; print(os.environ)",
            "get_ipython()",
            "print.__globals__",
            "__import__('os')",
            "import asterion.applications.prime.p1.oracle",
        ):
            with self.subTest(code=code):
                worker = P1WorkerProcess(deadline=time.monotonic() + 10)
                await worker.start()
                try:
                    receipt = await worker.execute_cell(
                        P1CellRequest("cell", "turn", code)
                    )
                    self.assertEqual(receipt.status, "uncertain")
                    self.assertNotIn("sentinel-secret", repr(receipt))
                    self.assertGreater(worker.snapshot().cells[-1].audit_denials, 0)
                    with self.assertRaises(P1WorkerError):
                        worker.validate_lifecycle()
                finally:
                    cleanup = await worker.close()
                    self.assertTrue(cleanup.reaped)
                    self.assertTrue(cleanup.root_removed)

    async def test_output_cap_poisons_and_reaps(self) -> None:
        receipt = await self.cell("print('x' * 65537)")
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(receipt.output, "")
        cleanup = await self.worker.close()
        self.assertTrue(cleanup.reaped)
        self.assertEqual(cleanup.reap_count, 1)

    async def test_caught_output_overflow_still_poisons_worker(self) -> None:
        receipt = await self.cell(
            "try:\n    print('x' * 65537)\nexcept Exception:\n    pass"
        )
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(receipt.output, "")

    async def test_caught_audit_denial_still_poisons_worker(self) -> None:
        receipt = await self.cell(
            "try:\n    open('/etc/passwd')\nexcept Exception:\n    pass"
        )
        self.assertEqual(receipt.status, "uncertain")
        self.assertGreater(self.worker.snapshot().cells[-1].audit_denials, 0)

    async def test_format_string_cannot_traverse_private_attributes(self) -> None:
        receipt = await self.cell(
            "import json\nprint('{0.__globals__[__name__]}'.format(json.dumps))"
        )
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(receipt.output, "")

    async def test_pattern_matching_cannot_extract_worker_closures(self) -> None:
        receipt = await self.cell(
            "base = str.mro()[-1]\nmatch open:\n    case base(__closure__=cells):\n        print(len(cells))"
        )
        self.assertEqual(receipt.status, "uncertain")
        self.assertEqual(receipt.output, "")

    async def test_symlink_cannot_escape_descriptor_root(self) -> None:
        root = self.worker._root
        assert root is not None
        Path(root.name, "outside").symlink_to("/etc/passwd")
        receipt = await self.cell("open('outside').read()")
        self.assertEqual(receipt.status, "uncertain")

    async def test_timeout_and_malformed_reply_fence_possible_dispatch(self) -> None:
        with patch.object(
            self.worker,
            "_exchange",
            new=AsyncMock(return_value={"type": "cell", "request_id": "wrong"}),
        ):
            receipt = await self.cell("marker = 1")
        self.assertEqual(receipt.status, "uncertain")
        cleanup = self.worker.cleanup_receipt
        assert cleanup is not None
        self.assertTrue(cleanup.reaped)

    async def test_absolute_deadline_reaps_busy_worker(self) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.worker import P1CellRequest

        worker = P1WorkerProcess(deadline=time.monotonic() + 0.6)
        await worker.start()
        try:
            receipt = await worker.execute_cell(
                P1CellRequest("deadline-cell", "deadline-turn", "while True: pass")
            )
            self.assertEqual(receipt.status, "uncertain")
        finally:
            cleanup = await worker.close()
            self.assertTrue(cleanup.reaped)
            self.assertEqual(cleanup.reap_count, 1)

    async def test_cleanup_failure_is_redacted_and_can_finish_without_second_reap(
        self,
    ) -> None:
        from asterion.applications.prime.p1.worker import P1WorkerError

        root = self.worker._root
        assert root is not None
        with patch.object(
            root, "cleanup", side_effect=RuntimeError("sentinel-cleanup-private-path")
        ):
            with self.assertRaisesRegex(
                P1WorkerError, "P1 worker cleanup failed"
            ) as caught:
                await self.worker.close()
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(caught.exception.__cause__)
        cleanup = await self.worker.close()
        self.assertTrue(cleanup.root_removed)
        self.assertEqual(cleanup.reap_count, 1)

    async def test_cancel_waiting_for_close_lock_is_redacted(self) -> None:
        async with self.worker._close_lock:
            task = asyncio.create_task(self.worker.close())
            await asyncio.sleep(0)
            task.cancel("sentinel-close-cancel")
            with self.assertRaises(asyncio.CancelledError) as caught:
                await task
            self.assertEqual(caught.exception.args, ())
            self.assertIsNone(caught.exception.__context__)

    async def test_lifecycle_replacement_rejected_without_reaping(self) -> None:
        from asterion.applications.prime.p1.worker import P1WorkerError

        process = self.worker._process
        self.worker._process = None
        with self.assertRaises(P1WorkerError):
            self.worker.validate_lifecycle()
        self.assertEqual(self.worker._reap_count, 0)
        self.worker._process = process
        self.worker.validate_lifecycle()

    async def test_cancel_active_cell_is_redacted_and_reaps_once(self) -> None:
        task = asyncio.create_task(self.cell("while True: pass"))
        await asyncio.sleep(0.08)
        task.cancel("sentinel-cancellation")
        with self.assertRaises(asyncio.CancelledError) as raised:
            await task
        self.assertEqual(raised.exception.args, ())
        self.assertIsNone(raised.exception.__context__)
        cleanup = await self.worker.close()
        self.assertIs(await self.worker.close(), cleanup)
        self.assertEqual(cleanup.reap_count, 1)
        self.assertTrue(cleanup.pipes_closed)
        with self.assertRaises(ProcessLookupError):
            os.kill(self.worker.identity.pid, 0)

    async def test_one_active_cell_and_lifecycle_after_close(self) -> None:
        from asterion.applications.prime.p1.worker import P1WorkerError

        task = asyncio.create_task(self.cell("while True: pass"))
        await asyncio.sleep(0.05)
        with self.assertRaisesRegex(P1WorkerError, "P1 worker request rejected"):
            await self.cell("second = 2", "cell-2", "turn-2")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.worker.close()
        with self.assertRaises(P1WorkerError):
            self.worker.validate_lifecycle()
