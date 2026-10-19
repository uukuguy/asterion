"""Code-aware compaction is a kernel interface list, not the native template."""

from __future__ import annotations

import asyncio
import time
import unittest

from asterion.agents.prime.code_summary import (
    CODE_SUMMARY_VERSION,
    NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS,
    CodeSummaryError,
    KernelBinding,
    build_code_aware_summary,
    is_native_generic_summary,
)
from asterion.agents.prime.summarization import SUMMARY_INITIAL_TEMPLATE
from asterion.applications.prime.p1.code_summary import summarize_worker
from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
from asterion.applications.prime.p1.operator import _AGENT_SETTINGS
from asterion.applications.prime.p1.worker import P1CellRequest
from tests.test_asterion_prime_p1_worker import setup_cell


class TestCodeAwareCompaction(unittest.TestCase):
    def test_native_template_is_not_a_code_summary(self) -> None:
        summary = build_code_aware_summary(
            (KernelBinding("AffineAccumulator", "class"),),
            keep_recent_tokens=256,
        )
        self.assertEqual(summary.kind, CODE_SUMMARY_VERSION)
        self.assertTrue(is_native_generic_summary(SUMMARY_INITIAL_TEMPLATE))
        self.assertFalse(is_native_generic_summary(summary.text))
        self.assertNotIn(SUMMARY_INITIAL_TEMPLATE, summary.text)
        self.assertNotIn("## Goal", summary.text)
        self.assertTrue(summary.below_native_threshold)
        self.assertLess(256, NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS)
        high = build_code_aware_summary(
            (KernelBinding("AffineAccumulator", "class"),),
            keep_recent_tokens=NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS,
        )
        self.assertFalse(high.below_native_threshold)
        with self.assertRaises(CodeSummaryError):
            build_code_aware_summary((), keep_recent_tokens=256)

    def test_shipped_compaction_summarizes_the_live_kernel(self) -> None:
        keep_recent = int(_AGENT_SETTINGS["compaction"]["keepRecentTokens"])
        self.assertLess(keep_recent, NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS)

        async def run() -> None:
            worker = P1WorkerProcess(deadline=time.monotonic() + 30)
            try:
                await worker.start()
                receipt = await worker.execute_cell(
                    P1CellRequest("code-summary-setup", "code-summary-turn", setup_cell())
                )
                self.assertEqual(receipt.status, "ok")
                summary = summarize_worker(
                    worker.snapshot(), keep_recent_tokens=keep_recent
                )
            finally:
                await worker.close()
            self.assertEqual(summary.kind, CODE_SUMMARY_VERSION)
            self.assertEqual(
                summary.bindings[:2], ("AffineAccumulator", "accumulator")
            )
            self.assertIn("input_tuple", summary.bindings)
            self.assertTrue(summary.below_native_threshold)
            self.assertFalse(is_native_generic_summary(summary.text))
            self.assertNotIn("## Goal", summary.text)
            self.assertEqual(len(summary.sha256), 64)
            self.assertIn("class AffineAccumulator", summary.text)
            self.assertIn("callable accumulator", summary.text)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
