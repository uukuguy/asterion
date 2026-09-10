"""Provider-free P1 oracle and safe receipt contract checks."""

import importlib.util
from dataclasses import asdict, replace
import json
import time
from typing import cast
import unittest

from tests.test_asterion_prime_p1_worker import (
    setup_cell,
    stage_two_cell,
    verification_cell,
)


class TestP1OracleContract(unittest.TestCase):
    def test_native_oracle_and_receipt_contracts_exist(self) -> None:
        for module in (
            "asterion.applications.prime.p1.oracle",
            "asterion.applications.prime.p1.receipt",
        ):
            with self.subTest(module=module):
                try:
                    spec = importlib.util.find_spec(module)
                except ModuleNotFoundError:
                    spec = None
                self.assertIsNotNone(spec, "native P1 oracle contract is missing")

    def test_oracle_receipt_rejects_private_or_invalid_fields(self) -> None:
        from asterion.applications.prime.p1.oracle import (
            P1OracleError,
            P1StageOneReceipt,
        )

        for value in ("sentinel-private-path", "A" * 64, 7):
            with self.subTest(value=value):
                with self.assertRaisesRegex(P1OracleError, "^P1 oracle rejected$"):
                    P1StageOneReceipt(cast(str, value), "a" * 64, "b" * 64, 2)


class TestP1Oracle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        try:
            spec = importlib.util.find_spec("asterion.applications.prime.p1.oracle")
        except ModuleNotFoundError:
            spec = None
        self.assertIsNotNone(spec, "native P1 oracle contract is missing")
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.oracle import P1Oracle

        self.worker = P1WorkerProcess(deadline=time.monotonic() + 20)
        await self.worker.start()
        self.addAsyncCleanup(self.worker.close)
        self.oracle = P1Oracle(self.worker)

    async def cell(self, code: str, number: int, *, turn: str | None = None):
        from asterion.applications.prime.p1.worker import P1CellRequest

        return await self.worker.execute_cell(
            P1CellRequest(f"cell-{number}", turn or f"turn-{number}", code)
        )

    async def first_stage(self):
        await self.cell(setup_cell(), 1)
        await self.cell(verification_cell(), 2)
        return self.oracle.verify_stage_one(self.worker.snapshot())

    def checkpoint(self, *, kernel_generation: int = 1):
        from asterion.applications.prime.p1.worker import P1WorkerCheckpoint

        checkpoint = P1WorkerCheckpoint(
            worker_identity_sha256=self.worker.identity.sha256(),
            after_sequence=2,
            checkpoint_sha256="a" * 64,
            compact_receipt_sha256="b" * 64,
            kernel_generation=kernel_generation,
            before_attachment_generation=1,
            after_attachment_generation=2,
            before_context_tokens=1024,
            after_context_tokens=256,
        )
        self.worker.mark_compact_checkpoint(checkpoint)
        return checkpoint

    async def final_stage(self):
        first = await self.first_stage()
        self.checkpoint()
        await self.cell(stage_two_cell(), 3)
        return self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_verification_cannot_rewrite_identical_file(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        await self.cell(setup_cell(), 1)
        rewrite = 'with open("./stage-one.json", "w") as rewritten:\n    rewritten.write(\'{"input":[3,7,11,17],"setup_value":40}\\n\')\n'
        await self.cell(rewrite + verification_cell(), 2)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_one(self.worker.snapshot())

    async def test_continuation_cannot_rewrite_identical_file(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        self.checkpoint()
        rewrite = 'with open("stage-one.json", "w") as rewritten:\n    rewritten.write(\'{"input":[3,7,11,17],"setup_value":40}\\n\')\n'
        await self.cell(rewrite + stage_two_cell(), 3)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_continuation_cannot_replace_file_inode(self) -> None:
        from pathlib import Path
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        self.checkpoint()
        root = self.worker._root
        assert root is not None
        target = Path(root.name, "stage-one.json")
        original = target.read_bytes()
        target.rename(Path(root.name, "original-stage-one.json"))
        with target.open("wb") as stream:
            stream.write(original)
        await self.cell(stage_two_cell(), 3)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_two_stages_and_safe_receipt_bind_actual_cleanup(self) -> None:
        from asterion.applications.prime.p1.receipt import (
            build_native_receipt,
            seal_cleanup_receipt,
        )

        initial = self.worker.snapshot()
        self.assertEqual(initial.seeded_symbols, ("input_tuple", "task_statement"))
        self.assertEqual(initial.cells, ())
        result = await self.final_stage()
        self.assertTrue(result.succeeded)
        self.assertEqual(self.worker.snapshot().identity, initial.identity)
        cleanup = await self.worker.close()
        sealed = seal_cleanup_receipt(
            self.oracle,
            result,
            cleanup,
            backend_closed=True,
            pi_reaped=True,
            extension_closed=True,
            private_store_removed=True,
        )
        receipt = build_native_receipt(self.oracle, result, sealed)
        self.assertEqual(receipt.final_status, "verified")
        self.assertEqual(receipt.oracle_receipt_sha256, result.sha256())
        self.assertEqual(receipt.cleanup_receipt_sha256, sealed.sha256())
        self.assertEqual(receipt.compact_usage, "reservation-charged")
        public = json.dumps(asdict(receipt), sort_keys=True)
        for private in ("final_result", "file_bytes", "object_id", "input_tuple"):
            self.assertNotIn(private, public)
        self.assertEqual(receipt.sha256(), receipt.sha256())

    async def test_self_report_and_display_text_are_not_evidence(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        await self.cell('print("verified"); final_result = 98', 1)
        await self.cell('stage_one_verified = {"succeeded": True}', 2)
        with self.assertRaisesRegex(P1OracleError, "P1 oracle rejected"):
            self.oracle.verify_stage_one(self.worker.snapshot())

    async def test_fabricated_snapshot_and_receipt_are_rejected(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        snapshot = self.worker.snapshot()
        bad_cell = replace(snapshot.cells[-1], final_result=98)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_one(
                replace(snapshot, cells=(*snapshot.cells[:-1], bad_cell))
            )
        self.checkpoint()
        await self.cell(stage_two_cell(), 3)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), replace(first))

    async def test_verification_requires_distinct_turn(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        await self.cell(setup_cell(), 1)
        await self.cell(verification_cell(), 2, turn="turn-1")
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_one(self.worker.snapshot())

    async def test_stage_two_requires_checkpoint(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        await self.cell(stage_two_cell(), 3)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_checkpoint_cannot_change_initial_kernel_generation(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        self.checkpoint(kernel_generation=2)
        await self.cell(stage_two_cell(), 3)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_setup_requires_actual_accumulator_call(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        await self.cell(setup_cell().replace("accumulator(input_tuple[2])", "40"), 1)
        await self.cell(verification_cell(), 2)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_one(self.worker.snapshot())

    async def test_stage_two_self_report_does_not_replace_object_and_file_use(
        self,
    ) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        self.checkpoint()
        await self.cell('print("verified"); final_result = 98', 3)
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_stage_two_replaced_object_is_rejected(self) -> None:
        from asterion.applications.prime.p1.oracle import P1OracleError

        first = await self.first_stage()
        self.checkpoint()
        await self.cell(
            "previous_accumulator = accumulator\n"
            "accumulator = AffineAccumulator(input_tuple[0], input_tuple[1])\n"
            + stage_two_cell(),
            3,
        )
        with self.assertRaises(P1OracleError):
            self.oracle.verify_stage_two(self.worker.snapshot(), first)

    async def test_actual_complete_file_bytes_are_required_in_both_reading_stages(
        self,
    ) -> None:
        from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
        from asterion.applications.prime.p1.oracle import P1Oracle, P1OracleError
        from asterion.applications.prime.p1.worker import (
            P1CellRequest,
            P1WorkerCheckpoint,
        )

        expected_bytes = b'{"input":[3,7,11,17],"setup_value":40}\n'
        for stage in ("verification", "continuation"):
            for read in ("stream.read(0)", "stream.read(1)", "old_stream.read()"):
                with self.subTest(stage=stage, read=read):
                    worker = P1WorkerProcess(deadline=time.monotonic() + 10)
                    await worker.start()
                    try:
                        oracle = P1Oracle(worker)
                        setup = setup_cell()
                        if read == "old_stream.read()":
                            setup += 'old_stream = open("stage-one.json", "rb")\nold_stream.read()\n'
                        await worker.execute_cell(
                            P1CellRequest("setup", "setup", setup)
                        )
                        verification = verification_cell()
                        if stage == "verification":
                            verification = verification.replace("stream.read()", read)
                            verification = verification.replace(
                                "stage_one_verified =",
                                f"verified_bytes = {expected_bytes!r}\nstage_one_verified =",
                            )
                        await worker.execute_cell(
                            P1CellRequest("verify", "verify", verification)
                        )
                        if stage == "verification":
                            with self.assertRaises(P1OracleError):
                                oracle.verify_stage_one(worker.snapshot())
                            continue
                        first = oracle.verify_stage_one(worker.snapshot())
                        worker.mark_compact_checkpoint(
                            P1WorkerCheckpoint(
                                worker.identity.sha256(),
                                2,
                                "a" * 64,
                                "b" * 64,
                                1,
                                1,
                                2,
                                1024,
                                256,
                            )
                        )
                        code = (
                            f'with open("stage-one.json", "rb") as stream:\n    ignored = {read}\n'
                            "final_result = accumulator(input_tuple[3]) + 40"
                        )
                        await worker.execute_cell(P1CellRequest("final", "final", code))
                        with self.assertRaises(P1OracleError):
                            oracle.verify_stage_two(worker.snapshot(), first)
                    finally:
                        await worker.close()

    async def test_incomplete_and_fabricated_cleanup_fail_closed(self) -> None:
        from asterion.applications.prime.p1.worker import P1WorkerCleanupReceipt
        from asterion.applications.prime.p1.receipt import (
            P1ReceiptError,
            build_native_receipt,
            seal_cleanup_receipt,
        )

        result = await self.final_stage()
        bits = dict(
            backend_closed=True,
            pi_reaped=True,
            extension_closed=True,
            private_store_removed=True,
        )
        try:
            seal_cleanup_receipt(
                self.oracle, result, cast(P1WorkerCleanupReceipt, None), **bits
            )
        except Exception as error:
            self.assertIsInstance(error, P1ReceiptError)
            self.assertEqual(str(error), "P1 receipt rejected")
        else:
            self.fail("cleanup must complete before receipt sealing")
        cleanup = await self.worker.close()
        for field in bits:
            with self.subTest(field=field):
                with self.assertRaises(P1ReceiptError):
                    seal_cleanup_receipt(
                        self.oracle, result, cleanup, **{**bits, field: False}
                    )
        with self.assertRaises(P1ReceiptError):
            seal_cleanup_receipt(self.oracle, result, replace(cleanup), **bits)
        sealed = seal_cleanup_receipt(self.oracle, result, cleanup, **bits)
        with self.assertRaises(P1ReceiptError):
            build_native_receipt(self.oracle, replace(result), sealed)
        with self.assertRaises(P1ReceiptError):
            build_native_receipt(self.oracle, result, replace(sealed))
