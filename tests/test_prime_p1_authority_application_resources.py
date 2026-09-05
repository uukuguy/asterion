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
    def test_declared_and_packaged_resource_paths_are_lexicographically_sorted(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        declared = module._EXPECTED_PATHS
        packaged = tuple(
            item["path"] for item in json.loads(module._descriptor_path().read_bytes())["resources"]
        )
        self.assertEqual(declared, tuple(sorted(declared)))
        self.assertEqual(packaged, tuple(sorted(packaged)))

    def test_admits_exact_packaged_resource_set(self) -> None:
        admitted = admit_prime_p1_application_resources()
        self.assertIs(type(admitted), AdmittedPrimeP1ApplicationResources)
        self.assertEqual(repr(admitted), "AdmittedPrimeP1ApplicationResources(redacted)")
        admitted.close()
        admitted.close()

    def test_admitted_resource_set_retains_exact_private_receipt_projection(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        expected = {
            item["path"]: item["sha256"]
            for item in json.loads(module._descriptor_path().read_bytes())["resources"]
        }
        admitted = admit_prime_p1_application_resources()
        projection = admitted._receipt_projection()

        self.assertEqual(
            projection.assembly_sha256,
            expected["applications/prime_agent/assemblies/prime-ipython-coding.json"],
        )
        self.assertEqual(
            projection.package_manifest_sha256,
            expected["capabilities/prime_agent/payload/capability-package.json"],
        )
        self.assertEqual(
            projection.workload_sha256,
            expected["applications/prime_agent/operator/image/fixture/workload.json"],
        )
        self.assertEqual(
            projection.starter_sha256,
            expected["applications/prime_agent/operator/image/fixture/starter/solution.py"],
        )
        self.assertEqual(
            projection.oracle_sha256,
            expected["applications/prime_agent/operator/image/fixture/oracle/oracle.py"],
        )

    def test_closed_resource_set_withholds_private_receipt_projection(self) -> None:
        admitted = admit_prime_p1_application_resources()
        admitted.close()

        with self.assertRaises(ValueError):
            admitted._receipt_projection()

    def test_forged_private_receipt_projection_is_rejected(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        admitted = admit_prime_p1_application_resources()
        forged = object.__new__(module._ApplicationReceiptProjection)
        for field in module._RECEIPT_RESOURCE_PATHS:
            object.__setattr__(forged, field, "0" * 64)
        admitted._projection = forged

        with self.assertRaises(ValueError):
            admitted._receipt_projection()

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

    def test_descriptor_schema_identity_and_digest_mutations_are_rejected(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        descriptor = module._descriptor_path()
        original = descriptor.read_bytes()
        original_read = module._read_relative_file
        mutations = (
            ("schema", lambda value: value.pop("protocol")),
            ("identity", lambda value: value["identity"].__setitem__("runtime_id", 1)),
            ("digest", lambda value: value["resources"][0].__setitem__("sha256", "0" * 64)),
            ("starter-digest", lambda value: value["resources"][3].__setitem__("sha256", "0" * 64)),
        )
        for name, mutate in mutations:
            with self.subTest(mutation=name):
                value = json.loads(original)
                mutate(value)
                altered = json.dumps(value, separators=(",", ":")).encode()

                def read(root: Path, parts: tuple[str, ...], maximum: int) -> bytes:
                    if root == module._operator_root() and parts == module._DESCRIPTOR_PARTS:
                        return altered
                    return original_read(root, parts, maximum)

                with patch.object(module, "_read_relative_file", side_effect=read):
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

    def test_hardlink_created_during_read_is_rejected(self) -> None:
        import asterion.applications.prime_agent.operator.authority_application_resources as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("x")
            original_read = os.read
            created = False

            def read(fd: int, length: int) -> bytes:
                nonlocal created
                if not created:
                    os.link(target, root / "hardlink")
                    created = True
                return original_read(fd, length)

            with patch.object(module.os, "read", side_effect=read):
                with self.assertRaises(ValueError):
                    module._read_relative_file(root, (target.name,), 1024)
