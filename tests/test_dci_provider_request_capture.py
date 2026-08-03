from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.dci.implementation.evaluation.provider_requests import (
    ProviderRequestCapture,
    ProviderRequestCaptureError,
)
from asterion.pathlight import ProviderRequestObservation


FIXTURES = Path(__file__).parent / "fixtures/pathlight-provider-request/v1"
CAPTURE_NAME = "provider-requests.jsonl"
FIXED_ERROR = "provider request capture is invalid"
PRIVATE_FIELDS = {
    "schema",
    "request_index",
    "captured_at",
    "payload_json",
    "payload_sha256",
    "payload_bytes",
    "shape_sha256",
    "summary_sha256",
}


def _fixture(name: str) -> dict[str, object]:
    return json.loads(FIXTURES.joinpath(name).read_text(encoding="utf-8"))


def _captured_pair(
    fixture: dict[str, object], request_index: int = 1
) -> tuple[bytes, dict[str, object]]:
    payload = fixture["payload"]
    summary = fixture["summary"]
    assert isinstance(summary, dict)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    record = {
        "schema": "dci.private-provider-request/v1",
        "request_index": request_index,
        "captured_at": "2026-08-03T04:05:06.789Z",
        "payload_json": payload_json,
        "payload_sha256": summary["payload_sha256"],
        "payload_bytes": summary["payload_bytes"],
        "shape_sha256": summary["shape_sha256"],
        "summary_sha256": summary["summary_sha256"],
    }
    raw = (
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()
    safe = {
        "schema": "dci.provider-request-observation/v1",
        "request_index": request_index,
        "capture_status": "captured",
        **summary,
    }
    return raw, safe


class ProviderRequestCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)

    def tearDown(self) -> None:
        os.close(self.directory_fd)
        self.temporary.cleanup()

    def _open(self) -> ProviderRequestCapture:
        return ProviderRequestCapture.open_at(self.directory_fd)

    def _write(self, capture: ProviderRequestCapture, raw: bytes) -> None:
        offset = 0
        while offset < len(raw):
            offset += os.write(capture.child_fd, raw[offset:])

    def _assert_invalid(self, capture: ProviderRequestCapture, safe: object) -> None:
        with self.assertRaises(ProviderRequestCaptureError) as raised:
            capture.validate(safe)  # type: ignore[arg-type]
        self.assertEqual(str(raised.exception), FIXED_ERROR)
        self.assertIsNone(raised.exception.__cause__)

    def test_open_at_exclusively_creates_descriptor_relative_regular_0600_file(
        self,
    ) -> None:
        capture = self._open()
        try:
            metadata = os.fstat(capture.child_fd)
            path_metadata = os.stat(CAPTURE_NAME, dir_fd=self.directory_fd)
            self.assertTrue(stat.S_ISREG(metadata.st_mode))
            self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
            self.assertEqual(
                (metadata.st_dev, metadata.st_ino),
                (path_metadata.st_dev, path_metadata.st_ino),
            )
            with self.assertRaises(ProviderRequestCaptureError):
                self._open()
        finally:
            capture.close()

    def test_existing_symlink_fifo_and_directory_targets_are_refused_unchanged(
        self,
    ) -> None:
        for kind in ("file", "symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                root = self.root / kind
                root.mkdir()
                directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                target = root / CAPTURE_NAME
                original = b"SENTINEL_EXISTING_CONTENT"
                try:
                    if kind == "file":
                        target.write_bytes(original)
                    elif kind == "symlink":
                        backing = root / "SENTINEL_PRIVATE_TARGET"
                        backing.write_bytes(original)
                        target.symlink_to(backing.name)
                    elif kind == "fifo":
                        os.mkfifo(target)
                    else:
                        target.mkdir()
                    with self.assertRaises(ProviderRequestCaptureError) as raised:
                        ProviderRequestCapture.open_at(directory_fd)
                    self.assertEqual(str(raised.exception), FIXED_ERROR)
                    if kind == "file":
                        self.assertEqual(target.read_bytes(), original)
                    elif kind == "symlink":
                        self.assertTrue(target.is_symlink())
                        self.assertEqual(backing.read_bytes(), original)
                    elif kind == "fifo":
                        self.assertTrue(stat.S_ISFIFO(target.lstat().st_mode))
                    else:
                        self.assertTrue(target.is_dir())
                finally:
                    os.close(directory_fd)

    def test_child_fd_lifecycle_is_explicit_and_close_is_idempotent(self) -> None:
        capture = self._open()
        descriptor = capture.child_fd
        self.assertGreaterEqual(descriptor, 0)
        capture.close()
        capture.close()
        with self.assertRaises(ProviderRequestCaptureError):
            _ = capture.child_fd
        with self.assertRaises(OSError):
            os.fstat(descriptor)
        self._assert_invalid(capture, ())

    def test_all_shared_valid_fixtures_cross_validate_into_immutable_observations(
        self,
    ) -> None:
        capture = self._open()
        try:
            raws: list[bytes] = []
            safe_entries: list[dict[str, object]] = []
            fixtures = (_fixture("valid-simple.json"), _fixture("valid-tools.json"))
            for index, fixture in enumerate(fixtures, 1):
                raw, safe = _captured_pair(fixture, index)
                raws.append(raw)
                safe_entries.append(safe)
            self._write(capture, b"".join(raws))

            observations = capture.validate(tuple(safe_entries))

            self.assertIsInstance(observations, tuple)
            self.assertEqual(tuple(item.request_index for item in observations), (1, 2))
            self.assertTrue(
                all(type(item) is ProviderRequestObservation for item in observations)
            )
            self.assertEqual(
                observations[0].payload_sha256, safe_entries[0]["payload_sha256"]
            )
            self.assertEqual(observations[1].segments[1].role, "tool-result")
            self.assertEqual(
                observations[0].private_reference_sha256,
                hashlib.sha256(raws[0].removesuffix(b"\n")).hexdigest(),
            )
            with self.assertRaises(AttributeError):
                observations[0].payload_bytes = 0  # type: ignore[misc]
        finally:
            capture.close()

    def test_empty_capture_and_entries_validate_as_an_empty_batch(self) -> None:
        capture = self._open()
        try:
            self.assertEqual(capture.validate(()), ())
        finally:
            capture.close()

    def test_cross_language_lone_surrogate_uses_node_utf8_replacement_semantics(
        self,
    ) -> None:
        payload_json = r'{"messages":[{"role":"user","content":"\ud800"}]}'
        summary = {
            "payload_sha256": "a7eda26b80af7e7f57bdeb13b4a234a2b40782ed94064363c4139d0404c1ceb6",
            "payload_bytes": 49,
            "shape_sha256": "8a85c53224daa249d4820ebb3174e234f88d12a3f952ca14c5461cbea9c05319",
            "field_count": 3,
            "leaf_count": 2,
            "text_characters": 5,
            "segments": [
                {
                    "segment_index": 0,
                    "role": "user",
                    "structure_kind": "message",
                    "content_sha256": "83d544ccc223c057d2bf80d3f2a32982c32c3c0db8e2674820da5064783fb097",
                    "content_length": 1,
                    "source_call_sha256": None,
                    "missing_evidence": False,
                    "segment_sha256": "32d9054cedfaaa3b4e98b6e556898427c65a8c74bbe2e848d19ac2eed1d0a254",
                }
            ],
            "missing_evidence": [],
            "summary_sha256": "f7bfc3a32dec04f561740b3994fe9e5c1c8db8793711c944a917ad4d98e991a7",
        }
        record = {
            "schema": "dci.private-provider-request/v1",
            "request_index": 1,
            "captured_at": "2026-08-03T04:05:06.789Z",
            "payload_json": payload_json,
            "payload_sha256": summary["payload_sha256"],
            "payload_bytes": summary["payload_bytes"],
            "shape_sha256": summary["shape_sha256"],
            "summary_sha256": summary["summary_sha256"],
        }
        safe = {
            "schema": "dci.provider-request-observation/v1",
            "request_index": 1,
            "capture_status": "captured",
            **summary,
        }
        capture = self._open()
        try:
            self._write(capture, self._record_bytes(record))
            (observation,) = capture.validate((safe,))
            self.assertEqual(observation.segments[0].content_length, 1)
        finally:
            capture.close()

    def test_payload_json_must_be_an_ecmascript_number_round_trip(self) -> None:
        impossible_literals = (
            "9007199254740993",
            "1000000000000000000000",
            "-1000000000000000000000",
        )
        for case, literal in enumerate(impossible_literals, 1):
            with self.subTest(literal=literal):
                payload_json = (
                    '{"messages":[{"role":"user","content":' + literal + "}]}"
                )
                record = {
                    "schema": "dci.private-provider-request/v1",
                    "request_index": 1,
                    "captured_at": "2026-08-03T04:05:06.789Z",
                    "payload_json": payload_json,
                    "payload_sha256": hashlib.sha256(payload_json.encode()).hexdigest(),
                    "payload_bytes": len(payload_json.encode()),
                    "shape_sha256": "0" * 64,
                    "summary_sha256": "0" * 64,
                }
                _, safe = _captured_pair(_fixture("valid-simple.json"))
                capture = self._open_in_child(f"number-{case}")
                try:
                    self._write(capture, self._record_bytes(record))
                    self._assert_invalid(capture, (safe,))
                finally:
                    capture.close()

    def test_ecmascript_exponent_threshold_matches_node_summaries(self) -> None:
        cases = (
            (
                "1e+21",
                "b8f4084dca648b7f77a9b856af3ca00e8f6dd401fd934cfefc2f74e0d08414ac",
                46,
                "241c4643fa70b1dcde1205b71be4e3bebb17e9f880c8e1a33d0ead6c27271d3c",
                5,
                "39ed5c3d2ab4f2efaa702c9bf04b2ec26dcbe294f9e2847f5f135173e6722366",
                "68b84f7ca04d82727764c85bc4b403db22cdfa76543d8e9bd7eae24dc10fa79b",
            ),
            (
                "-1e+21",
                "59af270598b03066887c1e87665fa1daf450cc4cd309cacac1c9d7b47bf7f751",
                47,
                "d1b781c586a6becc3c6bba876b259268cbead2c6085737f4799c2fd0607f55a4",
                6,
                "af714d13c43ed917c6392653279b554829641bc589499f0b0af0c4f3e86bd376",
                "b3a005fe0015ef86a8bfbe1a666d33ecd93fb7fe18a3eb66ecfe9b08863cd736",
            ),
        )
        for case, values in enumerate(cases, 1):
            (
                literal,
                payload_digest,
                payload_bytes,
                content_digest,
                content_length,
                segment_digest,
                summary_digest,
            ) = values
            payload_json = '{"messages":[{"role":"user","content":' + literal + "}]}"
            summary = {
                "payload_sha256": payload_digest,
                "payload_bytes": payload_bytes,
                "shape_sha256": "9d25ae19e392436efe046d8faf014978a74002f9ad62d1b8610cbb698212d4e7",
                "field_count": 3,
                "leaf_count": 2,
                "text_characters": 4,
                "segments": [
                    {
                        "segment_index": 0,
                        "role": "user",
                        "structure_kind": "message",
                        "content_sha256": content_digest,
                        "content_length": content_length,
                        "source_call_sha256": None,
                        "missing_evidence": False,
                        "segment_sha256": segment_digest,
                    }
                ],
                "missing_evidence": [],
                "summary_sha256": summary_digest,
            }
            record = {
                "schema": "dci.private-provider-request/v1",
                "request_index": 1,
                "captured_at": "2026-08-03T04:05:06.789Z",
                "payload_json": payload_json,
                "payload_sha256": payload_digest,
                "payload_bytes": payload_bytes,
                "shape_sha256": summary["shape_sha256"],
                "summary_sha256": summary_digest,
            }
            safe = {
                "schema": "dci.provider-request-observation/v1",
                "request_index": 1,
                "capture_status": "captured",
                **summary,
            }
            capture = self._open_in_child(f"exponent-{case}")
            try:
                self._write(capture, self._record_bytes(record))
                (observation,) = capture.validate((safe,))
                self.assertEqual(observation.payload_sha256, payload_digest)
            finally:
                capture.close()

    def test_invalid_shared_fixture_and_safe_mismatches_fail_closed(self) -> None:
        valid = _fixture("valid-simple.json")
        raw, safe = _captured_pair(valid)
        invalid_fixture = _fixture("invalid-summary.json")
        invalid_summary = invalid_fixture["summary"]
        assert isinstance(invalid_summary, dict)
        mutations: dict[str, object] = {
            "fixture-invalid-summary": {
                "schema": "dci.provider-request-observation/v1",
                "request_index": 1,
                "capture_status": "captured",
                **invalid_summary,
            },
            "payload-digest": {**safe, "payload_sha256": "0" * 64},
            "payload-bytes": {**safe, "payload_bytes": safe["payload_bytes"] + 1},
            "shape": {**safe, "shape_sha256": "0" * 64},
            "field-count": {**safe, "field_count": safe["field_count"] + 1},
            "leaf-count": {**safe, "leaf_count": safe["leaf_count"] + 1},
            "text-count": {**safe, "text_characters": safe["text_characters"] + 1},
            "summary": {**safe, "summary_sha256": "0" * 64},
            "missing": {**safe, "missing_evidence": ["context-segment"]},
            "status": {**safe, "capture_status": "missing"},
            "extra-field": {**safe, "SENTINEL_PRIVATE_KEY": "secret"},
        }
        segments = json.loads(json.dumps(safe["segments"]))
        segments[0]["segment_index"] = 9
        mutations["segment-index"] = {**safe, "segments": segments}
        segments = json.loads(json.dumps(safe["segments"]))
        segments[0]["content_sha256"] = "0" * 64
        mutations["segment-content"] = {**safe, "segments": segments}
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                capture = self._open_in_child(name)
                try:
                    self._write(capture, raw)
                    self._assert_invalid(capture, (mutated,))
                finally:
                    capture.close()

    def _open_in_child(self, name: str) -> ProviderRequestCapture:
        root = self.root / name
        root.mkdir()
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return ProviderRequestCapture.open_at(descriptor)
        finally:
            os.close(descriptor)

    def test_raw_jsonl_schema_types_indexes_timestamp_and_recomputation_are_closed(
        self,
    ) -> None:
        fixture = _fixture("valid-simple.json")
        raw, safe = _captured_pair(fixture)
        record = json.loads(raw)
        mutations: dict[str, bytes] = {
            "invalid-utf8": b"\xff\n",
            "not-json": b"{\n",
            "blank-line": raw + b"\n",
            "missing-newline": raw.rstrip(b"\n"),
            "array-record": b"[]\n",
            "extra-field": self._record_bytes(
                {**record, "SENTINEL_PRIVATE_KEY": "secret"}
            ),
            "wrong-schema": self._record_bytes({**record, "schema": "wrong"}),
            "bool-index": self._record_bytes({**record, "request_index": True}),
            "bad-timestamp": self._record_bytes(
                {**record, "captured_at": "SENTINEL_TIME"}
            ),
            "payload-json-type": self._record_bytes({**record, "payload_json": {}}),
            "payload-invalid-json": self._record_bytes({**record, "payload_json": "{"}),
            "payload-digest": self._record_bytes(
                {**record, "payload_sha256": "0" * 64}
            ),
            "payload-bytes": self._record_bytes(
                {**record, "payload_bytes": record["payload_bytes"] + 1}
            ),
            "shape": self._record_bytes({**record, "shape_sha256": "0" * 64}),
            "summary": self._record_bytes({**record, "summary_sha256": "0" * 64}),
            "duplicate-index": raw + raw,
        }
        raw_two, safe_two = _captured_pair(fixture, 2)
        record_two = json.loads(raw_two)
        mutations["noncontiguous-index"] = raw + self._record_bytes(
            {**record_two, "request_index": 3}
        )
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                capture = self._open_in_child(f"raw-{name}")
                try:
                    self._write(capture, mutated)
                    entries = (
                        (safe, safe_two) if name == "noncontiguous-index" else (safe,)
                    )
                    self._assert_invalid(capture, entries)
                finally:
                    capture.close()

    @staticmethod
    def _record_bytes(record: dict[str, object]) -> bytes:
        return (
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode()

    def test_count_mismatch_and_wrong_container_types_fail_closed(self) -> None:
        raw, safe = _captured_pair(_fixture("valid-simple.json"))
        for name, entries in (
            ("missing", ()),
            ("extra", (safe, safe)),
            ("list", [safe]),
            ("mapping", safe),
        ):
            with self.subTest(name=name):
                capture = self._open_in_child(f"count-{name}")
                try:
                    self._write(capture, raw)
                    self._assert_invalid(capture, entries)
                finally:
                    capture.close()

    def test_read_is_fsynced_through_held_fd_and_bounded_before_allocation(
        self,
    ) -> None:
        capture = self._open()
        try:
            raw, safe = _captured_pair(_fixture("valid-simple.json"))
            self._write(capture, raw)
            real_fsync = os.fsync
            calls: list[int] = []

            def recording_fsync(descriptor: int) -> None:
                calls.append(descriptor)
                real_fsync(descriptor)

            with patch("os.fsync", side_effect=recording_fsync):
                self.assertEqual(len(capture.validate((safe,))), 1)
            self.assertEqual(calls, [capture.child_fd])

            oversized = os.stat_result(
                (stat.S_IFREG | 0o600, 0, 0, 1, 0, 0, 512 * 1024 * 1024 + 1, 0, 0, 0)
            )
            with (
                patch("os.fstat", return_value=oversized),
                patch("os.pread") as pread,
            ):
                self._assert_invalid(capture, (safe,))
            pread.assert_not_called()
        finally:
            capture.close()

    def test_per_record_limit_counts_the_jsonl_delimiter(self) -> None:
        capture = self._open()
        try:
            raw, safe = _captured_pair(_fixture("valid-simple.json"))
            self._write(capture, raw)
            module = __import__(
                "asterion.capabilities.dci.implementation.evaluation.provider_requests",
                fromlist=["_MAX_RECORD_BYTES"],
            )
            with patch.object(module, "_MAX_RECORD_BYTES", len(raw) - 1):
                self._assert_invalid(capture, (safe,))
            with patch.object(module, "_MAX_RECORD_BYTES", len(raw)):
                self.assertEqual(len(capture.validate((safe,))), 1)
        finally:
            capture.close()

    def test_every_failure_has_one_fixed_redacted_message_without_chaining(
        self,
    ) -> None:
        capture = self._open()
        try:
            sentinel = "SENTINEL_PRIVATE_PAYLOAD_KEY_PATH_INDEX_DIGEST"
            self._write(capture, (sentinel + "\n").encode())
            try:
                capture.validate(({sentinel: sentinel},))
            except Exception as error:
                raised = error
            else:
                self.fail("private sentinel was accepted")
            rendered = "".join(traceback.format_exception(raised))
            self.assertIsInstance(raised, ProviderRequestCaptureError)
            self.assertEqual(str(raised), FIXED_ERROR)
            self.assertIsNone(raised.__cause__)
            self.assertNotIn(sentinel, rendered)
            self.assertNotIn(str(self.root), rendered)
        finally:
            capture.close()


if __name__ == "__main__":
    unittest.main()
