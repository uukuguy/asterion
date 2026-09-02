"""Tests for the proposal-only Prime IPython release specification boundary."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator import release_spec_generation as generation
from asterion.applications.prime_agent.operator import image_input_lock


_TARGET = generation.ExactTargetDescriptor("linux", "amd64", None)
_SOURCE = generation.PRIME_IPYTHON_SOURCE
_OBSERVATION = generation.SubstrateObservation(_TARGET, "native-linux", False)
_CAPTURES = (
    generation.AcquisitionCapture(
        "node-archive", "https://release.example.invalid/node.tar.xz", "node/node.tar.xz",
        10, "a" * 64, 10, "a" * 64,
    ),
    generation.AcquisitionCapture(
        "python-wheel", "https://release.example.invalid/ipykernel.whl", "python/ipykernel.whl",
        11, "b" * 64, 11, "b" * 64,
    ),
)


def _request(**changes: object) -> generation.ReleaseSpecGenerationRequest:
    return replace(
        generation.ReleaseSpecGenerationRequest(
            _TARGET, _SOURCE, _OBSERVATION, _CAPTURES, "prime-release-spec-generator/v1"
        ),
        **changes,
    )


class TestPrimeReleaseSpecGeneration(unittest.TestCase):
    def test_exact_native_nonemulated_target_is_only_candidate_native(self) -> None:
        result = generation.generate_release_specification(_request())

        self.assertEqual(result.status, "candidate-native")
        self.assertEqual(result.acquisition_lock.target, _TARGET)
        self.assertEqual(result.artifact_inventory.artifacts[0].url, _CAPTURES[0].url)
        self.assertTrue(result.release_proposal.untrusted)
        self.assertEqual(result.provenance.generator_revision, "prime-release-spec-generator/v1")
        self.assertNotIn("PASS", generation.canonical_release_spec_generation_json(result))

    def test_desktop_emulated_and_mismatched_observations_are_external_limited(self) -> None:
        cases = (
            generation.SubstrateObservation(_TARGET, "desktop-vm", False),
            generation.SubstrateObservation(_TARGET, "emulated", True),
            generation.SubstrateObservation(
                generation.ExactTargetDescriptor("linux", "arm64", None), "native-linux", False
            ),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                result = generation.generate_release_specification(_request(observation=observation))
                self.assertEqual(result.status, "External-limited")

    def test_rejects_noncanonical_captures_and_unpinned_source(self) -> None:
        cases: tuple[object, ...] = (
            tuple(reversed(_CAPTURES)),
            (_CAPTURES[0], _CAPTURES[0]),
            (replace(_CAPTURES[0], metadata_sha256=""), _CAPTURES[1]),
            (replace(_CAPTURES[0], object_size=9), _CAPTURES[1]),
            (replace(_CAPTURES[0], object_sha256="c" * 64), _CAPTURES[1]),
            (replace(_CAPTURES[0], url="http://release.example.invalid/node.tar.xz"), _CAPTURES[1]),
            generation.PrimeSourceTriple("c" * 40, _SOURCE.tree_sha256, _SOURCE.package_lock_sha256),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(generation.PrimeReleaseSpecGenerationError):
                if type(value) is generation.PrimeSourceTriple:
                    generation.generate_release_specification(_request(source=value))
                else:
                    generation.generate_release_specification(_request(captures=value))

    def test_public_output_is_canonical_untrusted_and_not_promotion_evidence(self) -> None:
        result = generation.generate_release_specification(_request())
        encoded = generation.canonical_release_spec_generation_json(result)

        self.assertEqual(encoded, json.dumps(json.loads(encoded), separators=(",", ":"), sort_keys=True))
        value = json.loads(encoded)
        self.assertEqual(value["format"], "asterion.prime-ipython-release-spec-generation/v1")
        self.assertTrue(value["release_proposal"]["untrusted"])
        with self.assertRaises(image_input_lock.PrimeImageInputLockError):
            image_input_lock.image_input_lock_from_dict(value)
        with self.assertRaises(image_input_lock.PrimeImageInputLockError):
            image_input_lock.validate_image_input_lock(result)  # type: ignore[arg-type]
        with self.assertRaises(image_input_lock.PrimeImageInputLockError):
            image_input_lock.VerifiedImageInputArtifactSet(image_input_lock.PRIME_IPYTHON_IMAGE_INPUT_LOCK, object())  # type: ignore[arg-type]

    def test_public_review_json_redacts_capture_urls_to_digests(self) -> None:
        private_url = "https://private-release-sentinel.invalid/secret-path/node.tar.xz"
        request = _request(captures=(
            replace(_CAPTURES[0], url=private_url),
            _CAPTURES[1],
        ))

        encoded = generation.canonical_release_spec_generation_json(
            generation.generate_release_specification(request)
        )
        value = json.loads(encoded)
        expected_digest = hashlib.sha256(private_url.encode("utf-8")).hexdigest()

        self.assertNotIn(private_url, encoded)
        self.assertNotIn("private-release-sentinel.invalid", encoded)
        self.assertNotIn("secret-path", encoded)
        for document_name, entries_key in (
            ("acquisition_lock", "captures"),
            ("artifact_inventory", "artifacts"),
            ("release_proposal", "artifacts"),
        ):
            entry = value[document_name][entries_key][0]
            self.assertNotIn("url", entry)
            self.assertEqual(entry["url_sha256"], expected_digest)

    def test_generation_never_uses_host_or_effectful_services(self) -> None:
        forbidden = RuntimeError("effectful access")
        with (
            mock.patch("socket.create_connection", side_effect=forbidden),
            mock.patch("subprocess.run", side_effect=forbidden),
            mock.patch("platform.machine", side_effect=forbidden),
        ):
            self.assertEqual(generation.generate_release_specification(_request()).status, "candidate-native")
