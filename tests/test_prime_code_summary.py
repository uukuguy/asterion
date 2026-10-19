"""Code-aware compaction is the summary Prime sends and Pi persists."""

from __future__ import annotations

import hashlib
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
from asterion.applications.prime.p1.operator import _AGENT_SETTINGS
from asterion.capabilities.prime_ipython_coding_native.host import P1RuntimeHostError
from tests.test_asterion_prime_p1_operator import TestP1Operator


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

class TestShippedCodeCompact(unittest.IsolatedAsyncioTestCase):
    async def _resources(self):
        case = TestP1Operator()
        case.addCleanup = self.addCleanup
        case.addAsyncCleanup = self.addAsyncCleanup
        resources, rpc, trace = await case.fixture()
        await resources.open()
        await resources._prompt("prepare", "prepare local state")
        await resources.host.pump()
        self.addAsyncCleanup(resources.close_in_owner_order)
        return resources, rpc, trace

    async def test_shipped_compact_persists_the_code_summary(self) -> None:
        keep_recent = int(_AGENT_SETTINGS["compaction"]["keepRecentTokens"])
        self.assertLess(keep_recent, NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS)
        resources, rpc, _trace = await self._resources()
        callbacks = resources.backend._owner()._kernel.model_callbacks
        compact = await resources.compact()
        sent = rpc.compact_instructions
        self.assertEqual(compact.status, "succeeded")
        self.assertEqual(resources.backend._owner()._kernel.model_callbacks, callbacks)
        self.assertTrue(sent.startswith(CODE_SUMMARY_VERSION + "\n"))
        self.assertIn("\nbelow_native_threshold: true\n", sent)
        self.assertIn(f"keep_recent_tokens: {keep_recent}\n", sent)
        self.assertIn(
            f"native_automatic_keep_recent_tokens: {NATIVE_AUTOMATIC_KEEP_RECENT_TOKENS}\n",
            sent,
        )
        self.assertIn("- class AffineAccumulator\n", sent)
        self.assertIn("- callable accumulator\n", sent)
        self.assertIn("- value input_tuple\n", sent)
        self.assertIn("\ntask_statement:\n", sent)
        self.assertIn("set final_result to that", sent)
        self.assertFalse(is_native_generic_summary(sent))
        self.assertNotIn("## Goal", sent)
        self.assertNotIn("## Constraints", sent)
        digest = hashlib.sha256(sent.encode()).hexdigest()
        self.assertEqual(compact.payload["result"]["summary_sha256"], digest)
        self.assertEqual(resources._code_summary.text, sent)
        self.assertEqual(resources._code_summary.sha256, digest)
        self.assertEqual(resources._code_summary.kind, CODE_SUMMARY_VERSION)
        self.assertTrue(resources._code_summary.below_native_threshold)

    async def test_shipped_compact_rejects_a_native_template(self) -> None:
        resources, rpc, trace = await self._resources()
        callbacks = resources.backend._owner()._kernel.model_callbacks
        rpc.compact_summary_override = SUMMARY_INITIAL_TEMPLATE
        with self.assertRaises(P1RuntimeHostError):
            await resources.compact()
        self.assertEqual(resources.backend._owner()._kernel.model_callbacks, callbacks)
        sent = rpc.compact_instructions
        self.assertTrue(sent.startswith(CODE_SUMMARY_VERSION + "\n"))
        self.assertFalse(is_native_generic_summary(sent))
        self.assertNotIn("## Goal", sent)
        self.assertIsNone(resources._code_summary)
        self.assertNotIn("compact.persist", trace)


if __name__ == "__main__":
    unittest.main()
