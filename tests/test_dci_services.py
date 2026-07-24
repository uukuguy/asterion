from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from asterion.dci.services import (
    LocalCorpusService,
    LocalCorpusServiceError,
    create_answer_judge_service_factory,
    create_local_corpus_service_factory,
)
from asterion.services.registry import (
    HostServiceFactoryContext,
    HostServiceRegistryError,
)


def _context(root: Path) -> HostServiceFactoryContext:
    return HostServiceFactoryContext(
        provider_id="dci-agent-lite",
        application_id="dci.research-capability",
        application_version="1.0.0",
        capability_id="corpus.local-root",
        options={"root": str(root)},
    )


class LocalCorpusServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_regular_directory_is_pinned_with_body_free_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve() / "corpus"
            root.mkdir()
            document = root / "SECRET-CONTENT.txt"
            document.write_text("FIRST PRIVATE BODY")
            binding = create_local_corpus_service_factory()

            async with binding.factory(_context(root)) as service:
                self.assertIsInstance(service, LocalCorpusService)
                self.assertEqual(service.root, root)
                self.assertNotIn(str(root), repr(service))
                first = service.identity_sha256
                document.write_text("SECOND PRIVATE BODY")
                self.assertEqual(service.identity_sha256, first)
                self.assertEqual(len(first), 64)
                self.assertTrue(all(character in "0123456789abcdef" for character in first))

            with self.assertRaises(LocalCorpusServiceError):
                _ = service.root

    async def test_missing_symlink_and_noncanonical_roots_fail_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            target = base / "target"
            target.mkdir()
            symlink = base / "SECRET-SYMLINK"
            symlink.symlink_to(target, target_is_directory=True)
            intermediate = base / "SECRET-INTERMEDIATE"
            intermediate.symlink_to(base, target_is_directory=True)
            sentinel = "SECRET-CORPUS-PATH"
            cases = (
                base / sentinel,
                symlink,
                intermediate / "target",
                Path(str(base) + "/target/../target"),
            )
            binding = create_local_corpus_service_factory()
            for root in cases:
                with self.subTest(root=root):
                    context = _context(root)
                    with self.assertRaises(LocalCorpusServiceError) as raised:
                        async with binding.factory(context):
                            self.fail("unreachable")
                    self.assertNotIn(sentinel, str(raised.exception))
                    self.assertNotIn("SECRET-", str(raised.exception))

    async def test_replacement_is_detected_without_exposing_path_or_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            root = base / "SECRET-CORPUS"
            root.mkdir()
            (root / "document").write_text("SECRET-CONTENT-BODY")
            binding = create_local_corpus_service_factory()

            async with binding.factory(_context(root)) as service:
                moved = base / "old"
                os.rename(root, moved)
                root.mkdir()
                with self.assertRaises(LocalCorpusServiceError) as raised:
                    _ = service.root

            rendered = str(raised.exception)
            self.assertNotIn("SECRET-CORPUS", rendered)
            self.assertNotIn("SECRET-CONTENT-BODY", rendered)

    async def test_factory_rejects_unknown_context_and_judge_is_fail_closed(
        self,
    ) -> None:
        corpus = create_local_corpus_service_factory()
        self.assertEqual(corpus.capability_id, "corpus.local-root")
        self.assertEqual(corpus.option_names, ("root",))
        judge = create_answer_judge_service_factory()
        self.assertEqual(judge.capability_id, "evaluation.answer-judge")
        self.assertEqual(judge.option_names, ())

        wrong = HostServiceFactoryContext(
            provider_id="dci-agent-lite",
            application_id="dci.research-capability",
            application_version="1.0.0",
            capability_id="service.wrong",
            options={},
        )
        with self.assertRaises(LocalCorpusServiceError):
            async with corpus.factory(wrong):
                self.fail("unreachable")
        with self.assertRaises(HostServiceRegistryError):
            async with judge.factory(
                HostServiceFactoryContext(
                    provider_id="dci-agent-lite",
                    application_id="dci.complete-application",
                    application_version="1.0.0",
                    capability_id="evaluation.answer-judge",
                    options={},
                )
            ):
                self.fail("unreachable")


if __name__ == "__main__":
    unittest.main()
