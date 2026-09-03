"""Offline parser tests for Prime candidate-release metadata."""

from __future__ import annotations

import json
import unittest

from asterion.applications.prime_agent.operator import release_metadata as metadata
from asterion.applications.prime_agent.operator.image_input_lock import ImagePlatformDescriptor
from asterion.applications.prime_agent.operator import release_recipe


_ARM64 = ImagePlatformDescriptor("linux", "arm64", None)
_AMD64 = ImagePlatformDescriptor("linux", "amd64", None)


class TestPrimeReleaseMetadata(unittest.TestCase):
    def test_node_shasums_selects_exact_target_name_and_honestly_omits_size(self) -> None:
        data = (
            "a" * 64 + "  node-v22.8.0-linux-arm64.tar.xz\n"
            + "b" * 64 + "  node-v22.8.0-linux-x64.tar.xz\n"
        ).encode()
        arm = metadata.parse_node_shasums(
            data, metadata.NodeShasumsSelector("22.8.0", _ARM64)
        )
        amd = metadata.parse_node_shasums(
            data, metadata.NodeShasumsSelector("22.8.0", _AMD64)
        )
        self.assertEqual(arm.object_name, "node-v22.8.0-linux-arm64.tar.xz")
        self.assertEqual(arm.declared_sha256, "a" * 64)
        self.assertIsNone(arm.declared_size)
        self.assertEqual(amd.object_name, "node-v22.8.0-linux-x64.tar.xz")
        self.assertIs(metadata.validate_parsed_metadata_declaration(arm), arm)
        self.assertIs(
            metadata.validate_declaration_metadata_bytes(arm, data), arm
        )
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.validate_declaration_metadata_bytes(arm, data + b"#")
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.ParsedMetadataDeclaration(
                arm.parser_kind,
                arm.parser_revision,
                arm.metadata_size,
                arm.metadata_sha256,
                arm.object_name,
                arm.declared_sha256,
                arm.declared_size,
                arm.media_type,
            )
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.parse_node_shasums(
                (data + ("c" * 64 + "  node-v22.8.0-linux-arm64.tar.xz\n").encode()),
                metadata.NodeShasumsSelector("22.8.0", _ARM64),
            )
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.parse_node_shasums(
                data + b"malformed-shasums-line\n",
                metadata.NodeShasumsSelector("22.8.0", _ARM64),
            )

    def test_pypi_json_requires_exact_python311_target_wheel(self) -> None:
        data = json.dumps(
            {
                "info": {"name": "pyzmq", "version": "26.1.0"},
                "urls": [
                    {
                        "filename": "pyzmq-26.1.0-cp311-cp311-manylinux_2_17_aarch64.whl",
                        "packagetype": "bdist_wheel",
                        "size": 123,
                        "digests": {"sha256": "d" * 64},
                    }
                ],
            }
        ).encode()
        selected = metadata.parse_pypi_json(
            data,
            metadata.PyPIFileSelector(
                "pyzmq",
                "26.1.0",
                "pyzmq-26.1.0-cp311-cp311-manylinux_2_17_aarch64.whl",
                _ARM64,
            ),
        )
        self.assertEqual(selected.declared_size, 123)
        self.assertEqual(selected.declared_sha256, "d" * 64)
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.parse_pypi_json(
                data.replace(b"cp311", b"cp312"),
                metadata.PyPIFileSelector(
                    "pyzmq",
                    "26.1.0",
                    "pyzmq-26.1.0-cp312-cp312-manylinux_2_17_aarch64.whl",
                    _ARM64,
                ),
            )

    def test_oci_index_and_manifest_require_exact_target_descriptors(self) -> None:
        index = json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "digest": "sha256:" + "e" * 64,
                        "size": 456,
                        "platform": {"os": "linux", "architecture": "arm64"},
                    }
                ],
            }
        ).encode()
        child = metadata.parse_oci_index_descriptor(
            index, metadata.OCIIndexSelector(_ARM64)
        )
        self.assertEqual(child.declared_sha256, "e" * 64)
        self.assertEqual(child.declared_size, 456)
        manifest = json.dumps(
            {
                "schemaVersion": 2,
                "config": {
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": "sha256:" + "f" * 64,
                    "size": 10,
                },
                "layers": [
                    {
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                        "digest": "sha256:" + "1" * 64,
                        "size": 11,
                    }
                ],
            }
        ).encode()
        config = metadata.parse_oci_manifest_descriptor(
            manifest, metadata.OCIManifestSelector("config", None)
        )
        layer = metadata.parse_oci_manifest_descriptor(
            manifest, metadata.OCIManifestSelector("layer", 0)
        )
        self.assertEqual(config.declared_sha256, "f" * 64)
        self.assertEqual(layer.declared_sha256, "1" * 64)
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.parse_oci_index_descriptor(index, metadata.OCIIndexSelector(_AMD64))

    def test_recipe_output_manifest_binds_recipe_source_scope_and_target(self) -> None:
        recipe = release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
        data = json.dumps(
            {
                "format": "asterion.prime-recipe-output-manifest/v1",
                "recipe_sha256": release_recipe.release_recipe_sha256(recipe),
                "source": {
                    "commit": recipe.source.commit,
                    "tree_sha256": recipe.source.tree_sha256,
                    "package_lock_sha256": recipe.source.package_lock_sha256,
                },
                "scope": "target-specific",
                "target": {"os": "linux", "architecture": "arm64", "variant": None},
                "path": "node/node_modules-linux-arm64.tar",
                "size": 12,
                "sha256": "2" * 64,
            }
        ).encode()
        selected = metadata.parse_recipe_output_manifest(
            data,
            metadata.RecipeOutputSelector(
                recipe, "target-specific", _ARM64, "node/node_modules-linux-arm64.tar"
            ),
        )
        self.assertEqual(selected.declared_sha256, "2" * 64)
        with self.assertRaises(metadata.PrimeReleaseMetadataError):
            metadata.parse_recipe_output_manifest(
                data,
                metadata.RecipeOutputSelector(
                    recipe, "target-specific", _AMD64, "node/node_modules-linux-arm64.tar"
                ),
            )

    def test_recipe_output_manifest_accepts_recipe_shared_output_without_target(
        self,
    ) -> None:
        recipe = release_recipe.PRIME_IPYTHON_RELEASE_RECIPE
        data = json.dumps(
            {
                "format": "asterion.prime-recipe-output-manifest/v1",
                "recipe_sha256": release_recipe.release_recipe_sha256(recipe),
                "source": {
                    "commit": recipe.source.commit,
                    "tree_sha256": recipe.source.tree_sha256,
                    "package_lock_sha256": recipe.source.package_lock_sha256,
                },
                "scope": "recipe-shared",
                "target": None,
                "path": "fixture/fixture-lock.json",
                "size": 12,
                "sha256": "2" * 64,
            }
        ).encode()

        selected = metadata.parse_recipe_output_manifest(
            data,
            metadata.RecipeOutputSelector(
                recipe, "recipe-shared", None, "fixture/fixture-lock.json"
            ),
        )

        self.assertEqual(selected.object_name, "fixture/fixture-lock.json")
        self.assertEqual(selected.declared_sha256, "2" * 64)


if __name__ == "__main__":
    unittest.main()
