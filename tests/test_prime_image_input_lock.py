"""Tests for explicit, offline Prime IPython image-input locks."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
import unittest

from asterion.applications.prime_agent.operator import image_input_lock as lock
from tools import materialize_prime_ipython_inputs as materializer


def _synthetic_lock() -> lock.ImageInputLock:
    artifacts = tuple(
        lock.ImageArtifact(
            kind, path, 1, sha256((kind + "\\0" + path).encode()).hexdigest()
        )
        for kind, path in (
            ("frontend", "build-frontend/launcher.mjs"),
            ("fixture", "fixture/fixture-lock.json"),
            ("node-archive", "node/node-v22.8.0-linux-x64.tar.xz"),
            ("node-modules", "node/node_modules-linux-amd64.tar"),
            ("oci-config", "oci/config.json"),
            ("oci-layer", "oci/layer-000.tar"),
            ("oci-manifest", "oci/manifest.json"),
            ("python-wheel", "python/comm-0.2.2-py3-none-any.whl"),
            (
                "python-wheel",
                "python/debugpy-1.8.5-cp312-cp312-manylinux_2_17_x86_64.whl",
            ),
            ("python-wheel", "python/ipykernel-6.29.5-py3-none-any.whl"),
            ("python-wheel", "python/jupyter_client-8.6.2-py3-none-any.whl"),
            ("python-wheel", "python/prime_agent_runtime-0-py3-none-any.whl"),
            (
                "python-wheel",
                "python/pyzmq-26.1.0-cp312-cp312-manylinux_2_17_x86_64.whl",
            ),
            (
                "python-wheel",
                "python/tornado-6.4.1-cp38-abi3-manylinux_2_17_x86_64.whl",
            ),
            ("python-wheel", "python/traitlets-5.14.3-py3-none-any.whl"),
        )
    )
    return lock.ImageInputLock(
        "a18809e00ea30638584d87b3afea7285a9d7296c",
        "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
        "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
        lock.ImagePlatformDescriptor("linux", "amd64", None),
        artifacts,
    )


class TestPrimeImageInputLock(unittest.TestCase):
    def test_default_promoted_catalog_is_empty_and_cannot_resolve_arm64(self) -> None:
        self.assertEqual(lock.PRIME_IPYTHON_IMAGE_INPUT_CATALOG.locks, ())
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.resolve_promoted_image_input_lock(
                lock.ImagePlatformDescriptor("linux", "arm64", None)
            )

    def test_promoted_resolution_rejects_caller_supplied_catalog(self) -> None:
        synthetic = _synthetic_lock()
        caller_catalog = lock.PromotedImageInputCatalog((synthetic,))

        with self.assertRaises(TypeError):
            lock.resolve_promoted_image_input_lock(
                synthetic.platform, caller_catalog  # type: ignore[call-arg]
            )

    def test_explicit_lock_is_required_for_hashing_and_verification(self) -> None:
        with self.assertRaises(TypeError):
            lock.image_input_lock_sha256()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            lock.verify_image_input_artifact_set(Path("/"))  # type: ignore[call-arg]

    def test_explicit_synthetic_lock_is_canonical_and_structurally_valid(self) -> None:
        value = _synthetic_lock()
        encoded = lock.canonical_image_input_lock_json(value)
        self.assertEqual(
            encoded,
            json.dumps(json.loads(encoded), separators=(",", ":"), sort_keys=True),
        )
        self.assertEqual(lock.validate_image_input_lock(value), value)
        self.assertEqual(lock.image_input_lock_from_dict(value.as_dict()), value)

    def test_rejects_open_or_noncanonical_lock_shapes(self) -> None:
        value = _synthetic_lock()
        lock_dict = value.as_dict()
        artifacts = cast(list[dict[str, object]], lock_dict["artifacts"])
        for case in (
            {**lock_dict, "url": "https://example.invalid/input"},
            {**lock_dict, "artifacts": list(reversed(artifacts))},
        ):
            with (
                self.subTest(case=case),
                self.assertRaises(lock.PrimeImageInputLockError),
            ):
                lock.image_input_lock_from_dict(case)

    def test_only_full_set_verification_can_create_artifact_set_proof(self) -> None:
        verification_lock = _synthetic_lock()
        payloads = {
            artifact.path: artifact.path.encode()
            for artifact in verification_lock.artifacts
        }
        verification_lock = replace(
            verification_lock,
            artifacts=tuple(
                lock.ImageArtifact(
                    artifact.kind,
                    artifact.path,
                    len(payloads[artifact.path]),
                    sha256(payloads[artifact.path]).hexdigest(),
                )
                for artifact in verification_lock.artifacts
            ),
        )
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.VerifiedImageInputArtifactSet(verification_lock, Path("/unverified"))
        with TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
            root = Path(temporary_directory)
            for path, payload in payloads.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
            (root / "unexpected").mkdir()
            with self.assertRaises(lock.PrimeImageInputLockError):
                lock.verify_image_input_artifact_set(root, verification_lock)
            (root / "unexpected").rmdir()
            proof = lock.verify_image_input_artifact_set(root, verification_lock)
            with self.assertRaises(TypeError):
                materializer.verify_external_materialization(root)  # type: ignore[call-arg]
            wrapped_proof = materializer.verify_external_materialization(
                root, verification_lock
            )
        self.assertEqual(proof.contract, verification_lock)
        self.assertEqual(proof.root, root)
        self.assertEqual(wrapped_proof, proof)

    def test_descriptor_rejects_noncanonical_values(self) -> None:
        for value in (
            lock.ImagePlatformDescriptor("linux", "amd64", ""),
            lock.ImagePlatformDescriptor("Linux", "amd64", None),
            {"os": "linux", "architecture": "amd64", "variant": None},
        ):
            with (
                self.subTest(value=value),
                self.assertRaises(lock.PrimeImageInputLockError),
            ):
                lock.validate_image_platform_descriptor(value)

    def test_candidate_evidence_cannot_be_constructed_as_promoted_input(self) -> None:
        candidate = lock.ReleaseLockProposal(
            "a" * 40,
            "b" * 64,
            "c" * 64,
            lock.ImagePlatformDescriptor("linux", "arm64", None),
            (),
        )
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.VerifiedCandidateArtifactSet(candidate, Path("/candidate"))
        with self.assertRaises(lock.PrimeImageInputLockError):
            lock.PromotedImageInput(_synthetic_lock())
