"""The host interprets one retrieval statement and the context service runs it."""
from pathlib import Path
import unittest

from asterion.applications.prime.p2.context_service import P2ContextService
from asterion.applications.prime.p2.program import (
    P2ProgramError,
    execute_program,
    interpret,
)


CORPUS = Path(__file__).resolve().parent / "fixtures" / "prime_p2" / "small_corpus.json"
SENTINEL = "The first bounded retrieval target."


class TestP2Program(unittest.TestCase):
    def test_interpret_accepts_one_service_call(self):
        cases = (
            ("retrieve(0, 1)", {"operation": "retrieve", "bounds": [0, 1]}),
            ("result = retrieve(0, 1)", {"operation": "retrieve", "bounds": [0, 1]}),
            ("```python\nretrieve(0, 1)\n```", {"operation": "retrieve", "bounds": [0, 1]}),
            (
                'transform(0, 2, "id", "title")',
                {
                    "operation": "transform",
                    "bounds": [0, 2],
                    "select_keys": ["id", "title"],
                },
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(interpret(source, 3), expected)

    def test_interpret_rejects_anything_but_one_bounded_call(self):
        rejected = (
            "import os",
            "retrieve(0, 1)\nretrieve(1, 2)",
            "retrieve(0, 9)",
            "retrieve(start=0, end=1)",
            "service.retrieve(0, 1)",
            "answer = retrieve(0, 1)",
            "",
            "retrieve(True, 1)",
        )
        for source in rejected:
            with self.subTest(source=source):
                with self.assertRaises(P2ProgramError):
                    interpret(source, 3)

    def test_execute_program_matches_the_service_slice(self):
        service = P2ContextService(CORPUS)
        source = "retrieve(0, 1)"
        self.assertNotIn(SENTINEL, source)
        produced = execute_program(source, service)
        self.assertEqual(produced, service.retrieve(bounds=(0, 1)))
        self.assertEqual(produced.payload[0]["body"], service.retrieve(bounds=(0, 1)).payload[0]["body"])
        self.assertIn(SENTINEL, produced.payload[0]["body"])


if __name__ == "__main__":
    unittest.main()
