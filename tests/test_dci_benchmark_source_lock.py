from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from asterion.applications.dci_agent_lite.benchmark_instances import (
    select_benchmark_instance,
)
from asterion.applications.dci_agent_lite.benchmark_source_lock import (
    DciBenchmarkSourceLockError,
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)
from asterion.capability_packages import (
    CapabilityPackageCandidate,
    CapabilityPackageRef,
    validate_capability_source_lock,
)
from asterion.capability_packages.payload import open_portable_payload


PAYLOAD_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src/asterion/capabilities/dci/payload"
)
DCI_REF = CapabilityPackageRef("dci", "1.0.0")


class RecordingSource:
    def __init__(self, source_id: str = "test.source") -> None:
        self.payload = open_portable_payload(PAYLOAD_ROOT)
        self.candidate = CapabilityPackageCandidate(
            package_ref=DCI_REF,
            source_id=source_id,
            source_kind="local-directory",
            payload_sha256=None,
            metadata={"private": "SECRET-source-locator"},
        )
        self.provider_loads = 0
        self.validations = 0

    def discover_metadata(self):
        return (self.candidate,)

    def open_payload(self, candidate):
        if candidate is not self.candidate:
            raise AssertionError("wrong candidate")
        return self.payload

    def validate_source_identity(self, candidate, payload):
        if candidate is not self.candidate or payload is not self.payload:
            raise AssertionError("identity changed")
        self.validations += 1

    def load_provider(self, candidate):
        del candidate
        self.provider_loads += 1
        raise AssertionError("provider must not load")


class DciBenchmarkSourceLockTests(unittest.TestCase):
    def test_resolves_verified_payload_without_loading_provider(self) -> None:
        source = RecordingSource()

        lock = resolve_benchmark_source_lock(
            select_benchmark_instance("dci.local-fixture@1.0.0"),
            package_sources=(source,),
        )

        self.assertEqual(source.validations, 1)
        self.assertEqual(source.provider_loads, 0)
        self.assertEqual(lock.entries[0].package_ref, DCI_REF)
        self.assertEqual(lock.entries[0].source_id, "test.source")
        self.assertEqual(
            lock.entries[0].payload_sha256,
            source.payload.payload_sha256,
        )
        self.assertNotIn("SECRET-source-locator", repr(lock))

    def test_zero_or_ambiguous_sources_fail_closed_and_redacted(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        for sources in ((), (RecordingSource("first.source"), RecordingSource("second.source"))):
            with self.subTest(count=len(sources)), self.assertRaises(
                DciBenchmarkSourceLockError
            ) as raised:
                resolve_benchmark_source_lock(instance, package_sources=sources)
            self.assertEqual(
                str(raised.exception),
                "DCI benchmark source lock is invalid",
            )
            self.assertNotIn("SECRET", repr(raised.exception))

    def test_writer_creates_canonical_private_file_and_never_overwrites(self) -> None:
        lock = resolve_benchmark_source_lock(
            select_benchmark_instance("dci.local-fixture@1.0.0"),
            package_sources=(RecordingSource(),),
        )
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "lock.json"
            write_benchmark_source_lock(lock, output)

            content = output.read_bytes()
            self.assertTrue(content.endswith(b"\n"))
            self.assertEqual(
                validate_capability_source_lock(json.loads(content)),
                lock,
            )
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            with self.assertRaises(DciBenchmarkSourceLockError):
                write_benchmark_source_lock(lock, output)

    def test_writer_rejects_missing_parent_and_symlink(self) -> None:
        lock = resolve_benchmark_source_lock(
            select_benchmark_instance("dci.local-fixture@1.0.0"),
            package_sources=(RecordingSource(),),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(DciBenchmarkSourceLockError):
                write_benchmark_source_lock(lock, root / "missing/lock.json")
            target = root / "target"
            target.write_text("preserve", encoding="utf-8")
            linked = root / "linked"
            try:
                linked.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaises(DciBenchmarkSourceLockError):
                write_benchmark_source_lock(lock, linked)
            self.assertEqual(target.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
