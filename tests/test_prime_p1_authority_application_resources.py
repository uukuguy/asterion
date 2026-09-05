"""Boundary tests for the fixed Prime P1 application-resource admission."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_resources import (
    PrimeP1AuthorityResourceError,
)
from asterion.applications.prime_agent.operator.authority_application_resources import (
    AdmittedPrimeP1ApplicationResources,
    admit_prime_p1_application_resources,
)


class TestPrimeP1AuthorityApplicationResources(unittest.TestCase):
    def test_admits_exact_packaged_resource_set(self) -> None:
        admitted = admit_prime_p1_application_resources()
        self.assertIs(type(admitted), AdmittedPrimeP1ApplicationResources)
        self.assertEqual(repr(admitted), "AdmittedPrimeP1ApplicationResources(redacted)")
        admitted.close()
        admitted.close()

    def test_verifier_failure_is_redacted(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        with patch.object(module, "_read_verified_resource", side_effect=RuntimeError("SECRET")):
            with self.assertRaises(PrimeP1AuthorityResourceError) as raised:
                admit_prime_p1_application_resources()
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("SECRET", str(raised.exception))
        self.assertNotIn("SECRET", repr(raised.exception))

    def test_descriptor_mutation_is_rejected(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        descriptor = module._descriptor_path()
        original = descriptor.read_bytes()
        value = json.loads(original)
        value["resources"][0]["path"] = "../outside"
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            altered = Path(directory) / "lock.json"
            altered.write_bytes(json.dumps(value, separators=(",", ":")).encode())
            with patch.object(module, "_read_relative_file", return_value=altered.read_bytes()):
                with self.assertRaises(PrimeP1AuthorityResourceError):
                    admit_prime_p1_application_resources()

    def test_symlink_fifo_and_hardlink_are_rejected(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("x")
            symlink = root / "symlink"
            symlink.symlink_to(target)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            hardlink = root / "hardlink"
            os.link(target, hardlink)
            for path in (symlink, fifo, hardlink):
                with self.subTest(path=path.name):
                    with self.assertRaises(ValueError):
                        module._read_relative_file(root, (path.name,), 1024)
