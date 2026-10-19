"""P4 process handoff resumes the P1 kernel from an empty private root."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime.compose import (
    KERNEL_OBJECTS,
    ComposeError,
    run_kernel_handoff,
)


_CELL = """
class AffineAccumulator:
    def __init__(self, multiplier, offset):
        self.multiplier = multiplier
        self.offset = offset
    def __call__(self, value):
        return self.multiplier * value + self.offset

accumulator = AffineAccumulator(input_tuple[0], input_tuple[1])
"""


class _Ask:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []
        self.usage = {"input_tokens": 3, "output_tokens": 2, "cost_micros": 1}

    async def __call__(self, prompt, signal):
        self.prompts.append(prompt)
        if signal.cancelled:
            raise AssertionError("cancelled")
        return self.text


class TestP1KernelHandoff(unittest.IsolatedAsyncioTestCase):
    async def test_handoff_resumes_named_objects_under_strict_identity(self) -> None:
        identities = []
        for _ in range(2):
            ask = _Ask(_CELL)
            with tempfile.TemporaryDirectory() as temporary:
                receipt = await run_kernel_handoff(
                    private_root=Path(temporary) / "store", ask=ask
                )
            self.assertEqual(receipt.status, "completed")
            self.assertEqual(receipt.identity_match, "strict")
            self.assertEqual(receipt.generation, 2)
            self.assertEqual(receipt.resumed_kernel_objects, KERNEL_OBJECTS)
            self.assertEqual(
                list(receipt.resumed_kernel_objects),
                ["AffineAccumulator", "accumulator"],
            )
            self.assertNotEqual(
                receipt.commit_worker_identity_sha256,
                receipt.resume_worker_identity_sha256,
            )
            self.assertEqual(len(receipt.kernel_object_identity), 64)
            self.assertEqual(len(receipt.receipt_sha256), 64)
            self.assertEqual(len(receipt.prior_checkpoint_sha256), 64)
            self.assertNotEqual(
                receipt.receipt_sha256, receipt.prior_checkpoint_sha256
            )
            self.assertEqual(receipt.model_call_count, 1)
            self.assertEqual(len(ask.prompts), 1)
            self.assertIn("AffineAccumulator", ask.prompts[0])
            identities.append(receipt.kernel_object_identity)
        self.assertEqual(identities[0], identities[1])

    async def test_wrong_cell_does_not_resume(self) -> None:
        ask = _Ask(
            "class AffineAccumulator:\n"
            "    def __init__(self, multiplier, offset):\n"
            "        self.multiplier = multiplier\n"
            "        self.offset = offset\n"
            "    def __call__(self, value):\n"
            "        return 0\n"
            "accumulator = AffineAccumulator(input_tuple[0], input_tuple[1])\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ComposeError):
                await run_kernel_handoff(
                    private_root=Path(temporary) / "store", ask=ask
                )


if __name__ == "__main__":
    unittest.main()
