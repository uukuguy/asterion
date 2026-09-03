"""Tests for the proposal-only Prime IPython release specification boundary."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator import image_input_lock
from asterion.applications.prime_agent.operator import release_metadata
from asterion.applications.prime_agent.operator import release_recipe
from asterion.applications.prime_agent.operator import (
    release_spec_generation as generation,
)


_TARGET = generation.ExactTargetDescriptor("linux", "amd64", None)
_METADATA_TARGET = image_input_lock.ImagePlatformDescriptor("linux", "amd64", None)
_SOURCE = generation.PRIME_IPYTHON_SOURCE
_OBSERVATION = generation.SubstrateObservation(_TARGET, "native-linux", False)
_RECIPE = release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
_NODE_METADATA = (
    "a" * 64 + "  node-v22.8.0-linux-arm64.tar.xz\n"
    + "b" * 64 + "  node-v22.8.0-linux-x64.tar.xz\n"
).encode()
_PYPI_METADATA = json.dumps(
    {
        "info": {"name": "ipykernel", "version": "6.29.0"},
        "urls": [{
            "filename": "ipykernel-6.29.0-py3-none-any.whl",
            "packagetype": "bdist_wheel", "size": 11,
            "digests": {"sha256": "d" * 64},
        }],
    }
).encode()
_CAPTURES = (
    generation.ParsedMetadataCapture(
        "node-archive",
        "node/node.tar.xz",
        _NODE_METADATA,
        release_metadata.parse_node_shasums(
            _NODE_METADATA,
            release_metadata.NodeShasumsSelector("22.8.0", _METADATA_TARGET),
        ),
        generation.ObjectBlob(
            "https://release.example.invalid/node.tar.xz", 10, "b" * 64
        ),
    ),
    generation.ParsedMetadataCapture(
        "python-wheel",
        "python/ipykernel.whl",
        _PYPI_METADATA,
        release_metadata.parse_pypi_json(
            _PYPI_METADATA,
            release_metadata.PyPIFileSelector(
                "ipykernel", "6.29.0", "ipykernel-6.29.0-py3-none-any.whl", _METADATA_TARGET
            ),
        ),
        generation.ObjectBlob(
            "https://release.example.invalid/ipykernel.whl", 11, "d" * 64
        ),
    ),
)


def _local_structural_image_lock() -> image_input_lock.ImageInputLock:
    artifacts = tuple(
        image_input_lock.ImageArtifact(kind, path, 0, f"{index:064x}")
        for index, (kind, path) in enumerate(
            (
                ("frontend", "build-frontend/launcher.mjs"),
                ("fixture", "fixture/fixture-lock.json"),
                ("node-modules", "node/node-modules.tar"),
                ("node-archive", "node/node.tar.xz"),
                ("oci-config", "oci/config.json"),
                ("oci-layer", "oci/layer.tar"),
                ("oci-manifest", "oci/manifest.json"),
                ("python-wheel", "python/prime_agent_runtime-0-py3-none-any.whl"),
            )
        )
    )
    return image_input_lock.ImageInputLock(
        "a" * 40,
        "b" * 64,
        "c" * 64,
        image_input_lock.ImagePlatformDescriptor("linux", "amd64", None),
        artifacts,
    )


def _request(**changes: object) -> generation.ReleaseSpecGenerationRequest:
    return replace(
        generation.ReleaseSpecGenerationRequest(
            _TARGET,
            _SOURCE,
            _OBSERVATION,
            _RECIPE,
            _CAPTURES,
            "prime-release-spec-generator/v1",
        ),
        **changes,
    )


class TestPrimeReleaseSpecGeneration(unittest.TestCase):
    def test_distinct_metadata_and_object_blobs_are_untrusted_candidate_claims(
        self,
    ) -> None:
        result = generation.generate_release_specification(_request())

        self.assertEqual(result.status, "candidate-native")
        self.assertEqual(
            result.acquisition_lock.claims[0].metadata.size, len(_NODE_METADATA)
        )
        self.assertEqual(result.artifact_inventory.artifacts[0].object.size, 10)
        self.assertTrue(result.release_proposal.untrusted)
        self.assertEqual(
            result.release_proposal.recipe.sha256,
            release_recipe.release_recipe_sha256(_RECIPE),
        )

    def test_desktop_emulated_and_mismatched_observations_are_external_limited(
        self,
    ) -> None:
        cases = (
            generation.SubstrateObservation(_TARGET, "desktop-vm", False),
            generation.SubstrateObservation(_TARGET, "emulated", True),
            generation.SubstrateObservation(
                generation.ExactTargetDescriptor("linux", "arm64", None),
                "native-linux",
                False,
            ),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                self.assertEqual(
                    generation.generate_release_specification(
                        _request(observation=observation)
                    ).status,
                    "External-limited",
                )

    def test_rejects_claim_and_recipe_policy_admission_failures(self) -> None:
        cases: tuple[object, ...] = (
            tuple(reversed(_CAPTURES)),
            (_CAPTURES[0], _CAPTURES[0]),
            (replace(_CAPTURES[0], metadata_bytes=b"wrong"), _CAPTURES[1]),
            (replace(_CAPTURES[0], declaration=None), _CAPTURES[1]),
            (
                replace(
                    _CAPTURES[0],
                    object=replace(_CAPTURES[0].object, sha256="e" * 64),
                ),
                _CAPTURES[1],
            ),
            (
                replace(
                    _CAPTURES[0],
                    object=replace(_CAPTURES[0].object, url=_CAPTURES[1].object.url),
                ),
                _CAPTURES[1],
            ),
            (
                replace(
                    _CAPTURES[0],
                    object=replace(
                        _CAPTURES[0].object,
                        url="http://release.example.invalid/node.tar.xz",
                    ),
                ),
                _CAPTURES[1],
            ),
        )
        for claims in cases:
            with (
                self.subTest(claims=claims),
                self.assertRaises(generation.PrimeReleaseSpecGenerationError),
            ):
                generation.generate_release_specification(_request(claims=claims))
        for changes in (
            {
                "source": generation.PrimeSourceTriple(
                    "c" * 40, _SOURCE.tree_sha256, _SOURCE.package_lock_sha256
                )
            },
            {"recipe": replace(_RECIPE)},
            {"target": generation.ExactTargetDescriptor("linux", "s390x", None)},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(generation.PrimeReleaseSpecGenerationError),
            ):
                generation.generate_release_specification(_request(**changes))

    def test_public_output_uses_separate_records_redacts_urls_and_cannot_be_proof(
        self,
    ) -> None:
        private_url = "https://private-release-sentinel.invalid/secret-path/node.tar.xz"
        encoded = generation.canonical_release_spec_generation_json(
            generation.generate_release_specification(
                _request(
                    claims=(
                        replace(
                            _CAPTURES[0],
                            object=replace(_CAPTURES[0].object, url=private_url),
                        ),
                        _CAPTURES[1],
                    )
                )
            )
        )

        self.assertEqual(
            encoded,
            json.dumps(json.loads(encoded), separators=(",", ":"), sort_keys=True),
        )
        value = json.loads(encoded)
        entry = value["acquisition_lock"]["claims"][0]
        self.assertEqual(
            entry["metadata"],
            {
                "parser_revision": _RECIPE.metadata_parsers.node_shasums,
                "sha256": hashlib.sha256(_NODE_METADATA).hexdigest(),
                "size": len(_NODE_METADATA),
            },
        )
        self.assertEqual(
            entry["object"]["url_sha256"],
            hashlib.sha256(private_url.encode()).hexdigest(),
        )
        self.assertNotIn("url", entry["object"])
        self.assertNotIn(private_url, encoded)
        self.assertNotIn("private-release-sentinel.invalid", encoded)
        self.assertTrue(value["release_proposal"]["untrusted"])
        self.assertEqual(
            value["release_proposal"]["recipe"],
            {
                "revision": _RECIPE.recipe_revision,
                "sha256": release_recipe.release_recipe_sha256(_RECIPE),
            },
        )
        with self.assertRaises(image_input_lock.PrimeImageInputLockError):
            image_input_lock.image_input_lock_from_dict(value)
        with self.assertRaises(image_input_lock.PrimeImageInputLockError):
            image_input_lock.validate_image_input_lock(
                generation.generate_release_specification(_request())  # type: ignore[arg-type]
            )
        structural_lock = _local_structural_image_lock()
        self.assertEqual(
            image_input_lock.validate_image_input_lock(structural_lock), structural_lock
        )

    def test_result_representation_never_exposes_private_capture_locator(self) -> None:
        private_url = "https://private-release-sentinel.invalid/secret-path/node.tar.xz"
        result = generation.generate_release_specification(
            _request(
                claims=(
                    replace(
                        _CAPTURES[0],
                        object=replace(_CAPTURES[0].object, url=private_url),
                    ),
                    _CAPTURES[1],
                )
            )
        )

        self.assertNotIn(private_url, repr(result))
        self.assertNotIn("private-release-sentinel.invalid", repr(result))
        self.assertNotIn("secret-path", str(result))

    def test_returned_public_claim_has_no_private_locator_attribute(self) -> None:
        result = generation.generate_release_specification(_request())
        public_object = result.release_proposal.artifacts[0].object

        self.assertFalse(hasattr(public_object, "url"))
        self.assertEqual(
            set(public_object.__dataclass_fields__), {"sha256", "size", "url_sha256"}
        )

    def test_public_result_canonicalization_rejects_mismatched_projections(self) -> None:
        result = generation.generate_release_specification(_request())
        tampered = replace(
            result,
            release_proposal=replace(
                result.release_proposal,
                artifacts=tuple(reversed(result.release_proposal.artifacts)),
            ),
        )

        with self.assertRaises(generation.PrimeReleaseSpecGenerationError):
            generation.canonical_release_spec_generation_json(tampered)

    def test_generation_never_uses_host_or_effectful_services(self) -> None:
        forbidden = RuntimeError("effectful access")
        with (
            mock.patch("socket.create_connection", side_effect=forbidden),
            mock.patch("subprocess.run", side_effect=forbidden),
            mock.patch("platform.machine", side_effect=forbidden),
        ):
            self.assertEqual(
                generation.generate_release_specification(_request()).status,
                "candidate-native",
            )
