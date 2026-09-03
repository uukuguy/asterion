"""Deterministic complete Prime candidate fixtures for offline staging tests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal

from asterion.applications.prime_agent.operator import release_metadata
from asterion.applications.prime_agent.operator import release_recipe
from asterion.applications.prime_agent.operator import (
    release_spec_generation as generation,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)


_TARGET = generation.ExactTargetDescriptor("linux", "amd64", None)
_METADATA_TARGET = ImagePlatformDescriptor("linux", "amd64", None)
_RECIPE = release_recipe.PRIME_IPYTHON_RELEASE_RECIPE


@dataclass(frozen=True)
class CompleteCandidateFixture:
    request: generation.ReleaseSpecGenerationRequest
    bodies_by_url: dict[str, bytes]


def _body(path: str) -> bytes:
    return f"prime-release-test-object:{path}".encode("ascii")


def _digest(body: bytes) -> str:
    return sha256(body).hexdigest()


def _object(path: str, body: bytes) -> generation.ObjectBlob:
    return generation.ObjectBlob(
        f"https://release.example.invalid/{path}", len(body), _digest(body)
    )


def _recipe_output_capture(
    kind: str,
    path: str,
    body: bytes,
    *,
    scope: Literal["target-specific", "recipe-shared"],
) -> generation.ParsedMetadataCapture:
    target = _METADATA_TARGET.as_dict() if scope == "target-specific" else None
    metadata = json.dumps(
        {
            "format": "asterion.prime-recipe-output-manifest/v1",
            "path": path,
            "recipe_sha256": release_recipe.release_recipe_sha256(_RECIPE),
            "scope": scope,
            "sha256": _digest(body),
            "size": len(body),
            "source": {
                "commit": _RECIPE.source.commit,
                "package_lock_sha256": _RECIPE.source.package_lock_sha256,
                "tree_sha256": _RECIPE.source.tree_sha256,
            },
            "target": target,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return generation.ParsedMetadataCapture(
        kind,
        path,
        metadata,
        release_metadata.parse_recipe_output_manifest(
            metadata,
            release_metadata.RecipeOutputSelector(
                _RECIPE,
                scope,
                _METADATA_TARGET if scope == "target-specific" else None,
                path,
            ),
        ),
        _object(path, body),
    )


def complete_amd64_candidate_fixture() -> CompleteCandidateFixture:
    """Build one fully parsed, byte-verifiable amd64 candidate without I/O."""

    bodies: dict[str, bytes] = {}
    captures: list[generation.ParsedMetadataCapture] = []

    node_path = "node/node.tar.xz"
    node_body = _body(node_path)
    bodies[_object(node_path, node_body).url] = node_body
    node_name = "node-v22.8.0-linux-x64.tar.xz"
    node_metadata = f"{_digest(node_body)}  {node_name}\n".encode("ascii")
    captures.append(
        generation.ParsedMetadataCapture(
            "node-archive",
            node_path,
            node_metadata,
            release_metadata.parse_node_shasums(
                node_metadata,
                release_metadata.NodeShasumsSelector("22.8.0", _METADATA_TARGET),
            ),
            _object(node_path, node_body),
        )
    )

    recipe_outputs: tuple[tuple[str, str, Literal["target-specific", "recipe-shared"]], ...] = (
        ("node-modules", "node/node-modules-linux-amd64.tar", "target-specific"),
        (
            "python-wheel",
            "python/prime_agent_runtime-0.1.0-py3-none-any.whl",
            "recipe-shared",
        ),
        ("fixture", "fixture/fixture-lock.json", "recipe-shared"),
        ("frontend", "build-frontend/launcher.mjs", "recipe-shared"),
    )
    for kind, path, scope in recipe_outputs:
        body = _body(path)
        capture = _recipe_output_capture(kind, path, body, scope=scope)
        bodies[capture.object.url] = body
        captures.append(capture)

    config_path, layer_path, manifest_path = (
        "oci/config.json",
        "oci/layer-0.tar.gz",
        "oci/manifest.json",
    )
    config_body, layer_body = _body(config_path), _body(layer_path)
    manifest_body = json.dumps(
        {
            "config": {
                "digest": "sha256:" + _digest(config_body),
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(config_body),
            },
            "layers": [
                {
                    "digest": "sha256:" + _digest(layer_body),
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(layer_body),
                }
            ],
            "schemaVersion": 2,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    index_metadata = json.dumps(
        {
            "manifests": [
                {
                    "digest": "sha256:" + _digest(manifest_body),
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "platform": _METADATA_TARGET.as_dict(),
                    "size": len(manifest_body),
                }
            ],
            "schemaVersion": 2,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    captures.extend(
        (
            generation.ParsedMetadataCapture(
                "oci-manifest",
                manifest_path,
                index_metadata,
                release_metadata.parse_oci_index_descriptor(
                    index_metadata, release_metadata.OCIIndexSelector(_METADATA_TARGET)
                ),
                _object(manifest_path, manifest_body),
            ),
            generation.ParsedMetadataCapture(
                "oci-config",
                config_path,
                manifest_body,
                release_metadata.parse_oci_manifest_descriptor(
                    manifest_body, release_metadata.OCIManifestSelector("config", None)
                ),
                _object(config_path, config_body),
            ),
            generation.ParsedMetadataCapture(
                "oci-layer",
                layer_path,
                manifest_body,
                release_metadata.parse_oci_manifest_descriptor(
                    manifest_body, release_metadata.OCIManifestSelector("layer", 0)
                ),
                _object(layer_path, layer_body),
            ),
        )
    )
    for path, body in (
        (config_path, config_body),
        (layer_path, layer_body),
        (manifest_path, manifest_body),
    ):
        bodies[_object(path, body).url] = body

    for requirement in release_recipe.prime_python_wheel_requirements():
        path = f"python/{requirement.normalized_project}.whl"
        body = _body(path)
        filename = (
            f"{requirement.normalized_project.replace('-', '_')}-"
            f"{requirement.version}-py3-none-any.whl"
        )
        metadata = json.dumps(
            {
                "info": {
                    "name": requirement.normalized_project,
                    "version": requirement.version,
                },
                "urls": [
                    {
                        "digests": {"sha256": _digest(body)},
                        "filename": filename,
                        "packagetype": "bdist_wheel",
                        "size": len(body),
                    }
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        capture = generation.ParsedMetadataCapture(
            "python-wheel",
            path,
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
            _object(path, body),
        )
        bodies[capture.object.url] = body
        captures.append(capture)

    request = generation.ReleaseSpecGenerationRequest(
        _TARGET,
        generation.PRIME_IPYTHON_SOURCE,
        generation.SubstrateObservation(_TARGET, "native-linux", False),
        _RECIPE,
        tuple(sorted(captures, key=lambda capture: capture.artifact_path)),
        "prime-release-spec-generator/v1",
    )
    return CompleteCandidateFixture(request, bodies)
