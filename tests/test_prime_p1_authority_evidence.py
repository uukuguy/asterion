"""Focused tests for Prime P1 authority evidence-root admission."""

from __future__ import annotations

import os
from pathlib import Path
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
        self.world_readable = Path(self.temporary.name) / "world-readable"
        self.world_readable.mkdir(mode=0o700)
        self.world_readable.chmod(0o755)
        self.other_owned = Path(self.temporary.name) / "other-owned"
        self.other_owned.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_admits_exact_owner_mode_directory_without_public_path(self) -> None:
        with self._single_link_root():
            resource = admit_evidence_root(_config(evidence_root=str(self.root)))
        self.assertEqual(repr(resource), "AdmittedPrimeP1EvidenceRoot(redacted)")
        with self.assertRaises(TypeError):
            resource.__reduce__()
        resource.close()

    def test_rejects_relative_symlink_wrong_mode_or_wrong_owner(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        for root in ("relative", str(self.symlink), str(self.world_readable)):
            with self.subTest(root=root):
                with self.assertRaises(PrimeP1EvidenceResourceError):
                    admit_evidence_root(_config(evidence_root=root))
        with patch.object(module.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(PrimeP1EvidenceResourceError):
                admit_evidence_root(_config(evidence_root=str(self.other_owned)))

    def test_close_is_exactly_once_when_called_concurrently(self) -> None:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        with self._single_link_root():
            resource = admit_evidence_root(_config(evidence_root=str(self.root)))
            with patch.object(module.os, "close", wraps=os.close) as close:
                threads = [threading.Thread(target=resource.close) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        close.assert_called_once()

    def _single_link_root(self) -> object:
        import asterion.applications.prime_agent.operator.authority_evidence as module

        original_fstat = os.fstat

        def fstat(fd: int) -> os.stat_result:
            info = original_fstat(fd)
            if info.st_ino != self.root.stat().st_ino:
                return info
            values = list(info)
            values[3] = 1
            return os.stat_result(values)

        return patch.object(module.os, "fstat", side_effect=fstat)


if __name__ == "__main__":
    unittest.main()
