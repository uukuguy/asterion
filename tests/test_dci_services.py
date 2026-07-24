from __future__ import annotations

import os
import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import asterion.dci.services as dci_services
from asterion.dci.services import (
    AnswerJudgeService,
    AnswerJudgeServiceError,
    LocalCorpusService,
    LocalCorpusServiceError,
    create_answer_judge_service_factory,
    create_local_corpus_service_factory,
)
from asterion.services.registry import (
    HostServiceFactoryContext,
    HostServiceRegistryError,
)
from asterion.runtime.working_directory import (
    ProcessWorkingDirectory,
    prepare_process_launch,
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

    async def test_process_directory_binding_keeps_pinned_identity_at_start(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            root = base / "corpus"
            root.mkdir()
            (root / "marker").write_text("ORIGINAL")
            binding = create_local_corpus_service_factory()

            async with binding.factory(_context(root)) as service:
                with service.open_process_working_directory() as working:
                    self.assertIsInstance(working, ProcessWorkingDirectory)
                    duplicate = (
                        working.pass_fds[0]
                        if working.pass_fds
                        else int(Path(working.cwd).name)
                    )
                    moved = base / "moved"
                    os.rename(root, moved)
                    root.mkdir()
                    (root / "marker").write_text("REPLACEMENT")
                    environment = dict(os.environ)
                    with prepare_process_launch(
                        working,
                        command=(
                            sys.executable,
                            "-c",
                            "from pathlib import Path; "
                            "print(Path('marker').read_text())",
                        ),
                        environment=environment,
                    ) as launch:
                        completed = subprocess.run(
                            launch.command,
                            cwd=working.cwd,
                            env=environment,
                            pass_fds=launch.pass_fds,
                            capture_output=True,
                            text=True,
                            check=True,
                        )

                self.assertEqual(completed.stdout.strip(), "ORIGINAL")
                with self.assertRaises(OSError):
                    os.fstat(duplicate)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin exec shim")
    async def test_exec_shim_closes_control_fds_before_target_exec(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            binding = create_local_corpus_service_factory()

            async with binding.factory(_context(root)) as service:
                with service.open_process_working_directory() as working:
                    self.assertEqual(working.cwd, "/")
                    self.assertEqual(
                        working.command_prefix[:3],
                        (sys.executable, "-I", "-S"),
                    )
                    helper = Path(working.command_prefix[3])
                    self.assertTrue(helper.is_absolute())
                    self.assertEqual(helper.name, "cwd_exec.py")
                    self.assertTrue(helper.is_file())
                    self.assertNotIn("-m", working.command_prefix)
                    environment = {"EXACT": "value"}
                    with prepare_process_launch(
                        working,
                        command=(
                            sys.executable,
                            "-c",
                            "import os\n"
                            "leaked = []\n"
                            "for fd in range(3, 256):\n"
                            " try:\n"
                            "  os.fstat(fd)\n"
                            " except OSError:\n"
                            "  continue\n"
                            " leaked.append(fd)\n"
                            "print('LEAK' if leaked else 'CLOSED')\n",
                        ),
                        environment=environment,
                    ) as launch:
                        self.assertNotIn("value", launch.command)
                        self.assertNotIn("value", repr(launch))
                        completed = subprocess.run(
                            launch.command,
                            cwd=working.cwd,
                            env=environment,
                            pass_fds=launch.pass_fds,
                            capture_output=True,
                            text=True,
                            check=True,
                        )

                self.assertEqual(completed.stdout.strip(), "CLOSED")

    async def test_factory_rejects_unknown_context_and_opens_exact_judge(
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
        judge_context = HostServiceFactoryContext(
            provider_id="dci-agent-lite",
            application_id="dci.complete-application",
            application_version="1.0.0",
            capability_id="evaluation.answer-judge",
            options={},
        )
        sentinel_key = "SENTINEL_KEY"
        with patch.dict(
            os.environ,
            {"DCI_EVAL_JUDGE_API_KEY": sentinel_key},
            clear=False,
        ):
            async with judge.factory(judge_context) as service:
                self.assertIsInstance(service, AnswerJudgeService)
                self.assertNotIn(sentinel_key, repr(service))
                self.assertNotIn(sentinel_key, repr(service.public_identity))
                self.assertEqual(len(service.public_identity["request_shape_sha256"]), 64)

        with self.assertRaises(HostServiceRegistryError):
            async with judge.factory(
                HostServiceFactoryContext(
                    provider_id="dci-agent-lite",
                    application_id="dci.research-capability",
                    application_version="1.0.0",
                    capability_id="evaluation.answer-judge",
                    options={},
                )
            ):
                self.fail("unreachable")

    async def test_secure_primitive_absence_fails_closed_and_redacted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            binding = create_local_corpus_service_factory()
            cases = (
                patch.object(os, "supports_dir_fd", set()),
                patch.object(dci_services.sys, "platform", "win32"),
                patch.object(
                    dci_services.os,
                    "open",
                    side_effect=NotImplementedError("SECRET-NOT-SUPPORTED"),
                ),
                patch.object(
                    dci_services.os,
                    "open",
                    side_effect=TypeError("SECRET-BAD-DIR-FD"),
                ),
            )
            for unavailable in cases:
                with (
                    self.subTest(unavailable=type(unavailable).__name__),
                    unavailable,
                    self.assertRaises(LocalCorpusServiceError) as raised,
                ):
                    async with binding.factory(_context(root)):
                        self.fail("unreachable")
                self.assertNotIn("SECRET", str(raised.exception))

    async def test_judge_cancellation_reaches_owned_transport_and_is_redacted(
        self,
    ) -> None:
        class Signal:
            cancelled = False

        signal = Signal()
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def operation(**kwargs):
            self.assertEqual(kwargs["question"], "SENTINEL_QUESTION")
            self.assertEqual(kwargs["gold_answer"], "SENTINEL_GOLD")
            self.assertEqual(kwargs["predicted_answer"], "SENTINEL_PREDICTION")
            self.assertEqual(kwargs["config"].api_key, "SENTINEL_KEY")
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                stopped.set()

        context = HostServiceFactoryContext(
            provider_id="dci-agent-lite",
            application_id="dci.complete-application",
            application_version="1.0.0",
            capability_id="evaluation.answer-judge",
            options={},
        )
        with (
            patch.dict(
                os.environ,
                {"DCI_EVAL_JUDGE_API_KEY": "SENTINEL_KEY"},
                clear=False,
            ),
            patch.object(dci_services, "judge_answer_async", operation),
        ):
            async with create_answer_judge_service_factory().factory(context) as service:
                task = asyncio.create_task(
                    service.judge(
                        question="SENTINEL_QUESTION",
                        gold_answer="SENTINEL_GOLD",
                        predicted_answer="SENTINEL_PREDICTION",
                        signal=signal,
                    )
                )
                await asyncio.wait_for(started.wait(), timeout=1)
                signal.cancelled = True
                with self.assertRaises(AnswerJudgeServiceError) as raised:
                    await asyncio.wait_for(task, timeout=3)

        self.assertTrue(stopped.is_set())
        self.assertNotIn("SENTINEL", str(raised.exception))

    async def test_judge_factory_requires_credentials_without_leaking_env(
        self,
    ) -> None:
        context = HostServiceFactoryContext(
            provider_id="dci-agent-lite",
            application_id="dci.complete-application",
            application_version="1.0.0",
            capability_id="evaluation.answer-judge",
            options={},
        )
        with patch.dict(
            os.environ,
            {
                "DCI_EVAL_JUDGE_API_KEY": "",
                "ASTERION_DCI_JUDGE_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaises(HostServiceRegistryError) as raised:
                async with create_answer_judge_service_factory().factory(context):
                    self.fail("unreachable")

        self.assertEqual(
            str(raised.exception), "answer judge service is unavailable"
        )


if __name__ == "__main__":
    unittest.main()
