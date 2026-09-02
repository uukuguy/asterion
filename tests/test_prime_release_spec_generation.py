"""Tests for the proposal-only Prime IPython release specification boundary."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import unittest
from unittest import mock

from asterion.applications.prime_agent.operator import image_input_lock
from asterion.applications.prime_agent.operator import release_recipe
from asterion.applications.prime_agent.operator import (
    release_spec_generation as generation,
)


_TARGET = generation.ExactTargetDescriptor("linux", "amd64", None)
_SOURCE = generation.PRIME_IPYTHON_SOURCE
_OBSERVATION = generation.SubstrateObservation(_TARGET, "native-linux", False)
_RECIPE = release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
_CLAIMS = (
    generation.MetadataObjectClaim(
        "node-archive",
        "node/node.tar.xz",
        generation.MetadataBlob("prime-release-metadata-parser/v1", 130, "a" * 64),
        generation.ObjectBlob(
            "https://release.example.invalid/node.tar.xz", 10, "b" * 64
        ),
        10,
        "b" * 64,
    ),
    generation.MetadataObjectClaim(
        "python-wheel",
        "python/ipykernel.whl",
        generation.MetadataBlob("prime-release-metadata-parser/v1", 131, "c" * 64),
        generation.ObjectBlob(
            "https://release.example.invalid/ipykernel.whl", 11, "d" * 64
        ),
        11,
        "d" * 64,
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
            _CLAIMS,
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
        self.assertEqual(result.acquisition_lock.claims[0].metadata.size, 130)
        self.assertEqual(result.artifact_inventory.artifacts[0].object.size, 10)
        self.assertTrue(result.release_proposal.untrusted)

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
            tuple(reversed(_CLAIMS)),
            (_CLAIMS[0], _CLAIMS[0]),
            (replace(_CLAIMS[0], metadata=None), _CLAIMS[1]),
            (
                replace(
                    _CLAIMS[0],
                    metadata=replace(_CLAIMS[0].metadata, parser_revision="other/v1"),
                ),
                _CLAIMS[1],
            ),
            (replace(_CLAIMS[0], declared_object_size=9), _CLAIMS[1]),
            (replace(_CLAIMS[0], declared_object_sha256="e" * 64), _CLAIMS[1]),
            (
                replace(
                    _CLAIMS[0],
                    object=replace(_CLAIMS[0].object, url=_CLAIMS[1].object.url),
                ),
                _CLAIMS[1],
            ),
            (
                replace(
                    _CLAIMS[0],
                    object=replace(
                        _CLAIMS[0].object,
                        url="http://release.example.invalid/node.tar.xz",
                    ),
                ),
                _CLAIMS[1],
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
                            _CLAIMS[0],
                            object=replace(_CLAIMS[0].object, url=private_url),
                        ),
                        _CLAIMS[1],
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
                "parser_revision": "prime-release-metadata-parser/v1",
                "sha256": "a" * 64,
                "size": 130,
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

    def test_exact_parser_boundary_rejects_extra_missing_and_wrong_claim_shapes(
        self,
    ) -> None:
        value = {
            "target": {"os": "linux", "architecture": "amd64", "variant": None},
            "source": {
                "commit": _SOURCE.commit,
                "tree_sha256": _SOURCE.tree_sha256,
                "package_lock_sha256": _SOURCE.package_lock_sha256,
            },
            "observation": {
                "target": {"os": "linux", "architecture": "amd64", "variant": None},
                "substrate": "native-linux",
                "emulated": False,
            },
            "recipe": {
                "source": {
                    "commit": _SOURCE.commit,
                    "tree_sha256": _SOURCE.tree_sha256,
                    "package_lock_sha256": _SOURCE.package_lock_sha256,
                },
                "recipe_revision": _RECIPE.recipe_revision,
                "python_major_minor": _RECIPE.python_major_minor,
                "node_version": _RECIPE.node_version,
                "base_distribution": _RECIPE.base_distribution,
                "libc": _RECIPE.libc,
                "python_dependency_lock_sha256": _RECIPE.python_dependency_lock_sha256,
                "frontend_recipe_sha256": _RECIPE.frontend_recipe_sha256,
            },
            "claims": [
                {
                    "artifact_kind": claim.artifact_kind,
                    "artifact_path": claim.artifact_path,
                    "metadata": {
                        "parser_revision": claim.metadata.parser_revision,
                        "size": claim.metadata.size,
                        "sha256": claim.metadata.sha256,
                    },
                    "object": {
                        "url": claim.object.url,
                        "size": claim.object.size,
                        "sha256": claim.object.sha256,
                    },
                    "declared_object_size": claim.declared_object_size,
                    "declared_object_sha256": claim.declared_object_sha256,
                }
                for claim in _CLAIMS
            ],
            "generator_revision": "prime-release-spec-generator/v1",
        }
        self.assertEqual(
            generation.release_spec_generation_request_from_dict(value), _request()
        )
        for mutate in (
            lambda item: item.update({"extra": True}),
            lambda item: item.pop("metadata"),
            lambda item: item.update({"metadata": {"size": 130, "sha256": "a" * 64}}),
        ):
            invalid = json.loads(json.dumps(value, default=lambda item: item.__dict__))
            mutate(invalid["claims"][0])
            with (
                self.subTest(mutate=mutate),
                self.assertRaises(generation.PrimeReleaseSpecGenerationError),
            ):
                generation.release_spec_generation_request_from_dict(invalid)

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
