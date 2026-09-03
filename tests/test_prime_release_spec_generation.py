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
def _python_wheel_capture(
    requirement: release_recipe.PythonWheelRequirement,
    index: int,
) -> generation.ParsedMetadataCapture:
    filename = f"{requirement.normalized_project.replace('-', '_')}-{requirement.version}-py3-none-any.whl"
    digest = f"{index:064x}"
    size = index + 100
    metadata = json.dumps(
        {
            "info": {"name": requirement.normalized_project, "version": requirement.version},
            "urls": [{
                "filename": filename,
                "packagetype": "bdist_wheel", "size": size,
                "digests": {"sha256": digest},
            }],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return generation.ParsedMetadataCapture(
        "python-wheel",
        f"python/{requirement.normalized_project}.whl",
        metadata,
        release_metadata.parse_pypi_json(
            metadata,
            release_metadata.PyPIFileSelector(
                requirement.normalized_project,
                requirement.version,
                filename,
                _METADATA_TARGET,
            ),
        ),
        generation.ObjectBlob(
            f"https://release.example.invalid/python/{requirement.normalized_project}.whl",
            size,
            digest,
        ),
    )


_NODE_CAPTURE = generation.ParsedMetadataCapture(
    "node-archive",
    "node/node.tar.xz",
    _NODE_METADATA,
    release_metadata.parse_node_shasums(
        _NODE_METADATA,
        release_metadata.NodeShasumsSelector("22.8.0", _METADATA_TARGET),
    ),
    generation.ObjectBlob("https://release.example.invalid/node.tar.xz", 10, "b" * 64),
)


def _recipe_shared_output_capture(
    artifact_kind: str,
    artifact_path: str,
    size: int,
    digest: str,
) -> generation.ParsedMetadataCapture:
    metadata = json.dumps(
        {
            "format": "asterion.prime-recipe-output-manifest/v1",
            "recipe_sha256": release_recipe.release_recipe_sha256(_RECIPE),
            "source": {
                "commit": _RECIPE.source.commit,
                "tree_sha256": _RECIPE.source.tree_sha256,
                "package_lock_sha256": _RECIPE.source.package_lock_sha256,
            },
            "scope": "recipe-shared",
            "target": None,
            "path": artifact_path,
            "size": size,
            "sha256": digest,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return generation.ParsedMetadataCapture(
        artifact_kind,
        artifact_path,
        metadata,
        release_metadata.parse_recipe_output_manifest(
            metadata,
            release_metadata.RecipeOutputSelector(
                _RECIPE, "recipe-shared", None, artifact_path
            ),
        ),
        generation.ObjectBlob(
            f"https://release.example.invalid/{artifact_path}", size, digest
        ),
    )


_RUNTIME_CAPTURE = _recipe_shared_output_capture(
    "python-wheel", "python/prime_agent_runtime-0.1.0-py3-none-any.whl", 15, "1" * 64
)
_FIXTURE_CAPTURE = _recipe_shared_output_capture(
    "fixture", "fixture/fixture-lock.json", 16, "2" * 64
)
_FRONTEND_CAPTURE = _recipe_shared_output_capture(
    "frontend", "build-frontend/launcher.mjs", 17, "3" * 64
)
_NODE_MODULES_PATH = "node/node-modules-linux-amd64.tar"
_NODE_MODULES_METADATA = json.dumps(
    {
        "format": "asterion.prime-recipe-output-manifest/v1",
        "recipe_sha256": release_recipe.release_recipe_sha256(_RECIPE),
        "source": {
            "commit": _RECIPE.source.commit,
            "tree_sha256": _RECIPE.source.tree_sha256,
            "package_lock_sha256": _RECIPE.source.package_lock_sha256,
        },
        "scope": "target-specific",
        "target": _METADATA_TARGET.as_dict(),
        "path": _NODE_MODULES_PATH,
        "size": 12,
        "sha256": "c" * 64,
    }, separators=(",", ":"), sort_keys=True,
).encode()
_NODE_MODULES_CAPTURE = generation.ParsedMetadataCapture(
    "node-modules", _NODE_MODULES_PATH, _NODE_MODULES_METADATA,
    release_metadata.parse_recipe_output_manifest(
        _NODE_MODULES_METADATA,
        release_metadata.RecipeOutputSelector(
            _RECIPE, "target-specific", _METADATA_TARGET, _NODE_MODULES_PATH,
        ),
    ),
    generation.ObjectBlob(
        "https://release.example.invalid/node/node-modules-linux-amd64.tar", 12, "c" * 64,
    ),
)
_OCI_MANIFEST_METADATA = json.dumps(
    {"schemaVersion": 2, "config": {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": "sha256:" + "d" * 64, "size": 13,
    }, "layers": [{
        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
        "digest": "sha256:" + "e" * 64, "size": 14,
    }]}, separators=(",", ":"), sort_keys=True,
).encode()
_OCI_MANIFEST_SHA256 = hashlib.sha256(_OCI_MANIFEST_METADATA).hexdigest()
_OCI_INDEX_METADATA = json.dumps({"schemaVersion": 2, "manifests": [{
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "digest": "sha256:" + _OCI_MANIFEST_SHA256, "size": len(_OCI_MANIFEST_METADATA),
    "platform": _METADATA_TARGET.as_dict(),
}]}, separators=(",", ":"), sort_keys=True).encode()
_OCI_MANIFEST_CAPTURE = generation.ParsedMetadataCapture(
    "oci-manifest", "oci/manifest.json", _OCI_INDEX_METADATA,
    release_metadata.parse_oci_index_descriptor(
        _OCI_INDEX_METADATA, release_metadata.OCIIndexSelector(_METADATA_TARGET),
    ),
    generation.ObjectBlob(
        "https://registry.example.invalid/oci/manifest.json",
        len(_OCI_MANIFEST_METADATA),
        _OCI_MANIFEST_SHA256,
    ),
)
_OCI_CONFIG_CAPTURE = generation.ParsedMetadataCapture(
    "oci-config", "oci/config.json", _OCI_MANIFEST_METADATA,
    release_metadata.parse_oci_manifest_descriptor(
        _OCI_MANIFEST_METADATA, release_metadata.OCIManifestSelector("config", None),
    ),
    generation.ObjectBlob("https://registry.example.invalid/oci/config.json", 13, "d" * 64),
)
_OCI_LAYER_CAPTURE = generation.ParsedMetadataCapture(
    "oci-layer", "oci/layer-0.tar.gz", _OCI_MANIFEST_METADATA,
    release_metadata.parse_oci_manifest_descriptor(
        _OCI_MANIFEST_METADATA, release_metadata.OCIManifestSelector("layer", 0),
    ),
    generation.ObjectBlob("https://registry.example.invalid/oci/layer-0.tar.gz", 14, "e" * 64),
)
_CAPTURES = tuple(sorted((
    _NODE_CAPTURE,
    _NODE_MODULES_CAPTURE,
    _RUNTIME_CAPTURE,
    _FIXTURE_CAPTURE,
    _FRONTEND_CAPTURE,
    _OCI_MANIFEST_CAPTURE,
    _OCI_CONFIG_CAPTURE,
    _OCI_LAYER_CAPTURE,
    *(
        _python_wheel_capture(requirement, index)
        for index, requirement in enumerate(
            release_recipe.prime_python_wheel_requirements(), 1
        )
    ),
), key=lambda capture: capture.artifact_path))


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
    def test_candidate_requires_every_non_python_target_artifact_slot(self) -> None:
        for missing in (
            _NODE_CAPTURE,
            _NODE_MODULES_CAPTURE,
            _OCI_MANIFEST_CAPTURE,
            _OCI_CONFIG_CAPTURE,
            _OCI_LAYER_CAPTURE,
            _RUNTIME_CAPTURE,
            _FIXTURE_CAPTURE,
            _FRONTEND_CAPTURE,
        ):
            with self.subTest(missing=missing.artifact_path):
                with self.assertRaises(generation.PrimeReleaseSpecGenerationError):
                    generation.generate_release_specification(
                        _request(
                            claims=tuple(
                                capture
                                for capture in _CAPTURES
                                if capture is not missing
                            )
                        )
                    )

    def test_candidate_rejects_a_target_artifact_graph_reused_for_arm64(self) -> None:
        with self.assertRaises(generation.PrimeReleaseSpecGenerationError):
            generation.generate_release_specification(
                _request(
                    target=generation.ExactTargetDescriptor("linux", "arm64", None)
                )
            )

    def test_candidate_requires_every_python_wheel_in_the_committed_closure(
        self,
    ) -> None:
        with self.assertRaises(generation.PrimeReleaseSpecGenerationError):
            generation.generate_release_specification(_request(claims=_CAPTURES[:2]))

    def test_candidate_rejects_a_wheel_substituted_at_an_expected_path(self) -> None:
        asttokens = next(
            capture
            for capture in _CAPTURES
            if capture.artifact_path == "python/asttokens.whl"
        )
        claims = tuple(
            replace(
                asttokens,
                artifact_path="python/ipykernel.whl",
                object=replace(
                    asttokens.object,
                    url="https://release.example.invalid/python/forged-ipykernel.whl",
                ),
            )
            if capture.artifact_path == "python/ipykernel.whl"
            else capture
            for capture in _CAPTURES
        )

        with self.assertRaises(generation.PrimeReleaseSpecGenerationError):
            generation.generate_release_specification(_request(claims=claims))

    def test_distinct_metadata_and_object_blobs_are_untrusted_candidate_claims(
        self,
    ) -> None:
        result = generation.generate_release_specification(_request())

        self.assertEqual(result.status, "candidate-native")
        node_claim = next(
            claim
            for claim in result.acquisition_lock.claims
            if claim.artifact_path == _NODE_CAPTURE.artifact_path
        )
        self.assertEqual(node_claim.metadata.size, len(_NODE_METADATA))
        self.assertEqual(node_claim.object.size, 10)
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
                    claims=tuple(
                        replace(
                            capture,
                            object=replace(capture.object, url=private_url),
                        )
                        if capture is _NODE_CAPTURE
                        else capture
                        for capture in _CAPTURES
                    )
                )
            )
        )

        self.assertEqual(
            encoded,
            json.dumps(json.loads(encoded), separators=(",", ":"), sort_keys=True),
        )
        value = json.loads(encoded)
        entry = next(
            claim
            for claim in value["acquisition_lock"]["claims"]
            if claim["artifact_path"] == _NODE_CAPTURE.artifact_path
        )
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
                claims=tuple(
                    replace(
                        capture,
                        object=replace(capture.object, url=private_url),
                    )
                    if capture is _NODE_CAPTURE
                    else capture
                    for capture in _CAPTURES
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
