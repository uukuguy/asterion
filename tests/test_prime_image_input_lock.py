"""Tests for the closed, offline Prime IPython image-input lock."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator import image_input_lock as lock


class TestPrimeImageInputLock(unittest.TestCase):
    def test_frozen_lock_is_canonical_and_binds_the_existing_prime_source(self) -> None:
        value = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK

        self.assertEqual(value.source_commit, "a18809e00ea30638584d87b3afea7285a9d7296c")
        self.assertEqual(value.source_tree_sha256, "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686")
        self.assertEqual(value.source_package_lock_sha256, "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8")
        self.assertEqual(value.platform, "linux/amd64")
        encoded = lock.canonical_image_input_lock_json(value)
        self.assertEqual(encoded, lock.canonical_image_input_lock_json(value))
        self.assertEqual(encoded, json.dumps(json.loads(encoded), separators=(",", ":"), sort_keys=True))
        self.assertEqual(lock.validate_image_input_lock(value), value)
        self.assertNotIsInstance(value, lock.VerifiedImageInputArtifactSet)

    def test_rejects_open_or_noncanonical_lock_shapes(self) -> None:
        value = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK
        lock_dict = value.as_dict()
        artifacts = cast(list[dict[str, object]], lock_dict["artifacts"])
        cases = (
            {**lock_dict, "url": "https://example.invalid/input"},
            {**lock_dict, "platform": "linux/arm64"},
            {**lock_dict, "source_commit": "a" * 40},
            {**lock_dict, "artifacts": list(reversed(artifacts))},
            {**lock_dict, "artifacts": artifacts[:-1]},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(lock.PrimeImageInputLockError):
                lock.image_input_lock_from_dict(case)

    def test_parser_rejects_nonexact_artifact_list_items(self) -> None:
        value = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK.as_dict()
        artifacts = cast(list[dict[str, object]], value["artifacts"])
        malformed_artifacts: tuple[object, ...] = (
            object(),
            {**artifacts[0], "url": "https://example.invalid/input"},
            {key: item for key, item in artifacts[0].items() if key != "sha256"},
        )

        for malformed_artifact in malformed_artifacts:
            with self.subTest(malformed_artifact=malformed_artifact), self.assertRaises(
                lock.PrimeImageInputLockError
            ):
                lock.image_input_lock_from_dict(
                    {**value, "artifacts": [*artifacts, malformed_artifact]}
                )

    def test_rejects_unsafe_artifact_records_and_duplicate_digests(self) -> None:
        value = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK.as_dict()
        artifacts = cast(list[dict[str, object]], value["artifacts"])
        for replacement in (
            {**artifacts[0], "path": "../escape"},
            {**artifacts[0], "path": "/absolute"},
            {**artifacts[0], "size": -1},
            {**artifacts[0], "sha256": "a" * 64},
            {**artifacts[0], "kind": "python-sdist"},
        ):
            mutated = {**value, "artifacts": [replacement, *artifacts[1:]]}
            with self.subTest(replacement=replacement), self.assertRaises(lock.PrimeImageInputLockError):
                lock.image_input_lock_from_dict(mutated)

        duplicate = [*artifacts]
        duplicate[1] = {**duplicate[1], "sha256": duplicate[0]["sha256"]}
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.image_input_lock_from_dict({**value, "artifacts": duplicate})

    def test_parser_rejects_non_scalar_artifact_fields_with_public_error(self) -> None:
        value = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK.as_dict()
        artifacts = cast(list[dict[str, object]], value["artifacts"])
        for field, malformed_value in (
            ("kind", []),
            ("path", []),
            ("sha256", []),
            ("size", True),
            ("size", "1"),
        ):
            replacement = {**artifacts[0], field: malformed_value}
            malformed = {**value, "artifacts": [replacement, *artifacts[1:]]}
            with self.subTest(field=field, malformed_value=malformed_value), self.assertRaises(
                lock.PrimeImageInputLockError
            ):
                lock.image_input_lock_from_dict(malformed)

    def test_rejects_a_caller_constructed_substitute_lock(self) -> None:
        canonical = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK
        substitute = lock.ImageInputLock(
            canonical.source_commit,
            canonical.source_tree_sha256,
            canonical.source_package_lock_sha256,
            canonical.platform,
            canonical.artifacts,
        )

        self.assertIsNot(substitute, canonical)
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.validate_image_input_lock(substitute)
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.verify_image_input_artifact_set(Path("/"), substitute)

    def test_only_full_set_verification_can_create_artifact_set_proof(self) -> None:
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.VerifiedImageInputArtifactSet(lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK, Path("/unverified"))

        payloads = {
            artifact.path: artifact.path.encode()
            for artifact in lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK.artifacts
        }
        verification_lock = replace(
            lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK,
            artifacts=tuple(
                lock.ImageArtifact(
                    artifact.kind,
                    artifact.path,
                    len(payloads[artifact.path]),
                    sha256(payloads[artifact.path]).hexdigest(),
                )
                for artifact in lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK.artifacts
            ),
        )
        with TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
            root = Path(temporary_directory)
            for path, payload in payloads.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
            with mock.patch.object(lock, "PRIME_IPYTHON_IMAGE_INPUT_LOCK", verification_lock):
                proof = lock.verify_image_input_artifact_set(root, verification_lock)

        self.assertEqual(proof.contract, verification_lock)
        self.assertEqual(proof.root, root)

    def test_malformed_artifact_objects_raise_the_public_lock_error(self) -> None:
        canonical = lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK
        malformed = lock.ImageInputLock(
            canonical.source_commit,
            canonical.source_tree_sha256,
            canonical.source_package_lock_sha256,
            canonical.platform,
            cast(tuple[lock.ImageArtifact, ...], (object(),)),
        )

        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.validate_image_input_lock(malformed)

    def test_static_validation_never_uses_effectful_tools_or_environment_files(self) -> None:
        forbidden = RuntimeError("effectful access")
        with (
            mock.patch("socket.create_connection", side_effect=forbidden),
            mock.patch("subprocess.run", side_effect=forbidden),
            mock.patch.object(Path, "read_text", side_effect=forbidden),
        ):
            self.assertEqual(
                lock.validate_image_input_lock(lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK),
                lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK,
            )
