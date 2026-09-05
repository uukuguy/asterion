"""Focused tests for Prime P1 authority evidence-root admission."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from types import MappingProxyType
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfig,
)
from asterion.applications.prime_agent.operator.authority_evidence import (
    PrimeP1EvidenceResourceError,
    admit_evidence_root,
)


def _config(*, evidence_root: str) -> PrimeP1OperatorConfig:
    return PrimeP1OperatorConfig(
        MappingProxyType({"ASTERION_PRIME_P1_EVIDENCE_ROOT": evidence_root}), object()  # type: ignore[arg-type]
    )


class TestPrimeP1AuthorityEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temporary.name) / "evidence"
        self.root.mkdir(mode=0o700)
        self.symlink = Path(self.temporary.name) / "evidence-link"
        self.symlink.symlink_to(self.root, target_is_directory=True)
        self.symlink_parent = Path(self.temporary.name) / "evidence-parent-link"
        self.symlink_parent.symlink_to(self.temporary.name, target_is_directory=True)
        self.world_readable = Path(self.temporary.name) / "world-readable"
        self.world_readable.mkdir(mode=0o700)
        self.world_readable.chmod(0o755)
        self.other_owned = Path(self.temporary.name) / "other-owned"
        self.other_owned.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_admits_exact_owner_mode_directory_without_public_path(self) -> None:
        resource = admit_evidence_root(_config(evidence_root=str(self.root)))
        self.assertEqual(repr(resource), "AdmittedPrimeP1EvidenceRoot(redacted)")
        with self.assertRaises(TypeError):
            resource.__reduce__()
        resource.close()

    def test_rejects_relative_and_final_component_symlink(self) -> None:
        for root in ("relative", str(self.symlink)):
            with self.subTest(root=root):
                with self.assertRaises(PrimeP1EvidenceResourceError):
                    admit_evidence_root(_config(evidence_root=root))

    def test_rejects_ancestor_symlink(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        with patch.object(module.os, "fstat", wraps=os.fstat) as fstat:
            with self.assertRaises(PrimeP1EvidenceResourceError):
                admit_evidence_root(
                    _config(evidence_root=str(self.symlink_parent / self.root.name))
                )
        fstat.assert_not_called()

    def test_rejects_wrong_mode_after_opening_directory(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        with (
            patch.object(module.os, "fstat", wraps=os.fstat) as fstat,
            self.assertRaises(PrimeP1EvidenceResourceError),
        ):
            admit_evidence_root(_config(evidence_root=str(self.world_readable)))
        fstat.assert_called_once()

    def test_rejects_wrong_owner_after_opening_directory(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        with (
            patch.object(module.os, "fstat", wraps=os.fstat) as fstat,
            patch.object(module.os, "geteuid", return_value=os.geteuid() + 1),
            self.assertRaises(PrimeP1EvidenceResourceError),
        ):
            admit_evidence_root(_config(evidence_root=str(self.other_owned)))
        fstat.assert_called_once()

    def test_normalizes_path_os_error_without_exception_chain(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        with patch.object(module.os, "open", side_effect=OSError("PATH_SENTINEL")):
            with self.assertRaises(PrimeP1EvidenceResourceError) as raised:
                admit_evidence_root(_config(evidence_root=str(self.root)))
        self.assertNotIn("PATH_SENTINEL", str(raised.exception))
        self.assertNotIn("PATH_SENTINEL", repr(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_metadata_rejection_closes_opened_final_descriptor_once(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        original_fstat = os.fstat

        def wrong_mode(received_fd: int) -> os.stat_result:
            info = original_fstat(received_fd)
            values = list(info)
            values[0] = stat.S_IFDIR | 0o755
            return os.stat_result(values)

        with (
            patch.object(
                module, "_open_absolute_directory_without_symlinks", return_value=fd
            ),
            patch.object(module.os, "fstat", side_effect=wrong_mode),
            patch.object(module.os, "close", wraps=os.close) as close,
            self.assertRaises(PrimeP1EvidenceResourceError),
        ):
            admit_evidence_root(_config(evidence_root=str(self.root)))
        close.assert_called_once_with(fd)

    def test_close_is_exactly_once_when_called_concurrently(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        resource = admit_evidence_root(_config(evidence_root=str(self.root)))
        with patch.object(module.os, "close", wraps=os.close) as close:
            threads = [threading.Thread(target=resource.close) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
