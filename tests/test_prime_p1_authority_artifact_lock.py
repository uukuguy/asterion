"""Tests for the packaged Prime P1 authority artifact admission boundary."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator.authority_resources import (
    PrimeP1AuthorityResourceError,
)
from asterion.applications.prime_agent.operator.authority_artifact_lock import (
    admit_authority_artifact_lock,
)


MODULE = "asterion.applications.prime_agent.operator.authority_artifact_lock"


class TestPrimeP1AuthorityArtifactLock(unittest.TestCase):
    def test_admits_only_the_exact_packaged_authority_artifact_set(self) -> None:
        resource = admit_authority_artifact_lock()
        self.addCleanup(resource.close)
        self.assertEqual(repr(resource), "AdmittedPrimeP1AuthorityArtifacts(redacted)")

    def test_rejects_a_digest_or_regular_file_change_without_leaking_the_path(
        self,
    ) -> None:
        with mock.patch(
            f"{MODULE}._read_verified_artifact", side_effect=ValueError("sentinel/path")
        ):
            with self.assertRaises(PrimeP1AuthorityResourceError) as caught:
                admit_authority_artifact_lock()
        self.assertEqual(str(caught.exception), "prime P1 authority resource is unavailable")
        self.assertNotIn("sentinel", str(caught.exception))

    @unittest.skipUnless(hasattr(os, "O_NONBLOCK"), "O_NONBLOCK is unavailable")
    def test_rejects_leaf_fifo_without_waiting_for_a_writer(self) -> None:
        import asterion.applications.prime_agent.operator.authority_artifact_lock as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            fifo = root / "artifact"
            os.mkfifo(fifo)
            finished = threading.Event()
            errors: list[BaseException] = []

            def read_fifo() -> None:
                try:
                    module._read_relative_file(root, (fifo.name,), 1024)
                except BaseException as error:
                    errors.append(error)
                finally:
                    finished.set()

            thread = threading.Thread(target=read_fifo, daemon=True)
            thread.start()
            self.assertTrue(finished.wait(1), "leaf FIFO open waited for a writer")
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)

    def test_rejects_artifact_linked_during_read(self) -> None:
        import asterion.applications.prime_agent.operator.authority_artifact_lock as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            artifact.write_bytes(b"immutable")
            linked = root / "linked-artifact"
            read_bounded = module._read_bounded

            def link_during_read(fd: int, maximum: int) -> bytes:
                os.link(artifact, linked)
                return read_bounded(fd, maximum)

            with mock.patch.object(module, "_read_bounded", side_effect=link_during_read):
                with self.assertRaises(ValueError):
                    module._read_relative_file(root, (artifact.name,), 1024)
