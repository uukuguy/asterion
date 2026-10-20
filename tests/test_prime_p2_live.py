"""P2 live inquiry commits a note only after the model cites the returned fragment."""
import asyncio
import json
from pathlib import Path
import re
import tempfile
import unittest

from asterion.applications.prime.live_model import LiveModelReply, LiveModelUsage
from asterion.applications.prime.p2.context_service import P2ContextService
from asterion.applications.prime.p2.live import P2LiveError, run_live_inquiry
from asterion.applications.prime.p2.task import P2_TASK_STATEMENT


CORPUS = Path(__file__).resolve().parent / "fixtures" / "prime_p2" / "small_corpus.json"
SENTINEL = "The first bounded retrieval target."


def _usage(incoming=11, outgoing=7):
    return LiveModelUsage(incoming, outgoing, 3)


def _answer(text: str) -> str:
    digest = re.search(r'"fragment_sha256":"([0-9a-f]{64})"', text).group(1)
    return json.dumps({"text": "fragment accepted", "fragment_sha256": digest})


class TestP2LiveInquiry(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = P2ContextService(CORPUS)

    def test_model_turns_commit_a_note_and_hide_the_corpus_from_the_query(self):
        seen = []

        async def prompt(text, *, signal):
            seen.append(text)
            if len(seen) == 1:
                return LiveModelReply("retrieve(0, 1)", _usage())
            return LiveModelReply(_answer(text), _usage(13, 9))

        result = asyncio.run(run_live_inquiry(
            service=self.service,
            notes_root=self.root,
            prompt=prompt,
            provider="deepseek",
            model="deepseek-flash",
        ))
        self.assertEqual(result.status, "verified")
        self.assertEqual((result.provider, result.model), ("deepseek", "deepseek-flash"))
        self.assertEqual(result.operation, "retrieve")
        self.assertEqual(result.bounds, (0, 1))
        self.assertEqual(result.model_call_count, 2)
        self.assertEqual(result.input_tokens, 24)
        self.assertTrue(seen[0].startswith(P2_TASK_STATEMENT))
        self.assertIn("retrieve(start, end)", seen[0])
        self.assertIn("Use no tools", seen[0])
        self.assertIn("retrieve(0, 1)", seen[0])
        self.assertNotIn(SENTINEL, seen[0])
        self.assertIn(SENTINEL, seen[1])
        public = {
            "status": result.status,
            "fragment_sha256": result.fragment_sha256,
            "notes_revision": result.notes_revision,
        }
        self.assertNotIn(SENTINEL, json.dumps(public))
        self.assertTrue((self.root / "accepted.json").is_file())

    def test_malformed_query_gets_one_replacement_ask(self):
        seen = []

        async def prompt(text, *, signal):
            seen.append(text)
            if len(seen) == 1:
                return LiveModelReply("import os", _usage())
            if len(seen) == 2:
                return LiveModelReply("retrieve(0, 1)", _usage())
            return LiveModelReply(_answer(text), _usage())

        result = asyncio.run(run_live_inquiry(
            service=self.service,
            notes_root=self.root,
            prompt=prompt,
            provider="deepseek",
            model="deepseek-flash",
        ))
        self.assertEqual(result.model_call_count, 3)
        self.assertIn("previous reply", seen[1])

    def test_zero_token_reply_is_rejected(self):
        async def prompt(text, *, signal):
            return LiveModelReply(
                "retrieve(0, 1)",
                LiveModelUsage(0, 0, 0),
            )

        with self.assertRaises(P2LiveError):
            asyncio.run(run_live_inquiry(
                service=self.service,
                notes_root=self.root,
                prompt=prompt,
                provider="deepseek",
                model="deepseek-flash",
            ))
        self.assertFalse((self.root / "accepted.json").exists())


if __name__ == "__main__":
    unittest.main()
