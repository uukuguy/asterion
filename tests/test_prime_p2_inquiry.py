"""P2 model queries stay in the application and commit notes only after identity checks."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.memory import ResearchMemoryStore
from asterion.agents.prime.research_notes import ResearchNotes
from asterion.applications.prime.p2.context_service import P2ContextService
from asterion.applications.prime.p2.inquiry import P2InquiryError, run_model_inquiry
from asterion.applications.prime.p2.task import P2_TASK_STATEMENT
from asterion.applications.prime.p2.worker import P2ContextServiceWorker


CORPUS = Path(__file__).resolve().parent / "fixtures" / "prime_p2" / "small_corpus.json"
SENTINEL = "The first bounded retrieval target."


class _Model:
    def __init__(self, query, answer_text="fragment accepted", *, cited=None):
        self.query = query
        self.answer_text = answer_text
        self.cited = cited
        self.tasks = []

    def write_query(self, task):
        self.tasks.append(task)
        return dict(self.query)

    def write_answer(self, task, fragment):
        self.tasks.append(task)
        cited = fragment["fragment_sha256"] if self.cited is None else self.cited
        return {"text": self.answer_text, "fragment_sha256": cited}


class TestP2ModelInquiry(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = P2ContextService(CORPUS)

    def _notes(self, revision):
        scope = {
            "application_id": "prime.programmatic-long-context",
            "corpus_sha256": P2ContextServiceWorker(self.service).corpus_sha256,
        }
        return ResearchNotes(
            ResearchMemoryStore(root=self.root / "memory", scope=scope),
            accepted_revision=revision,
        )

    def test_model_query_commits_a_note_without_publishing_the_corpus(self):
        model = _Model({
            "operation": "transform",
            "bounds": [1, 2],
            "select_keys": ["id"],
        })
        result = run_model_inquiry(service=self.service, model=model, notes_root=self.root)
        self.assertEqual(result.operation, "transform")
        self.assertEqual(result.bounds, (1, 2))
        self.assertNotIn(SENTINEL, json.dumps(asdict(result)))
        self.assertNotIn(SENTINEL, "".join(model.tasks))
        self.assertEqual(model.tasks[0], P2_TASK_STATEMENT)
        record = self._notes(result.notes_revision).read()
        self.assertEqual(record["text"], "fragment accepted")
        self.assertEqual(record["evidence_refs"], [{
            "fragment_sha256": result.fragment_sha256,
            "operation": "transform",
            "bounds": [1, 2],
        }])
        self.assertNotIn(SENTINEL, json.dumps(record["evidence_refs"]))
        self.assertNotIn(SENTINEL, repr(result))

    def test_wrong_fragment_identity_does_not_move_the_epoch(self):
        model = _Model({"operation": "retrieve", "bounds": [0, 1]}, cited="0" * 64)
        with self.assertRaises(P2InquiryError):
            run_model_inquiry(service=self.service, model=model, notes_root=self.root)
        self.assertFalse((self.root / "accepted.json").exists())
        revisions = self.root / "memory" / "revisions"
        self.assertFalse(revisions.exists() and any(revisions.iterdir()))

    def test_second_answer_is_a_child_of_the_accepted_note(self):
        first = run_model_inquiry(
            service=self.service,
            model=_Model({"operation": "retrieve", "bounds": [0, 1]}, answer_text="first"),
            notes_root=self.root,
        )
        second = run_model_inquiry(
            service=self.service,
            model=_Model({
                "operation": "transform",
                "bounds": [2, 3],
                "select_keys": ["title"],
            }, answer_text="second"),
            notes_root=self.root,
        )
        record = self._notes(second.notes_revision).read()
        self.assertEqual(record["text"], "second")
        self.assertEqual(record["parent_revision"], first.notes_revision)
        raw = json.loads((self.root / "accepted.json").read_text())
        self.assertEqual(raw["revision"], second.notes_revision)


if __name__ == "__main__":
    unittest.main()
