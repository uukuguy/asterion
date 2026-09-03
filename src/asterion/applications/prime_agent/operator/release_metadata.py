"""Pure offline parsers for exact Prime candidate-release metadata."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Final, Literal

from .image_input_lock import ImagePlatformDescriptor, validate_image_platform_descriptor
from . import release_recipe


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_DECLARATION_TOKEN: Final = object()


class PrimeReleaseMetadataError(ValueError):
    """Raised when offline release metadata does not make an exact declaration."""


@dataclass(frozen=True)
class NodeShasumsSelector:
    node_version: str
    target: ImagePlatformDescriptor


@dataclass(frozen=True)
class PyPIFileSelector:
    normalized_project: str
    version: str
    filename: str
    target: ImagePlatformDescriptor


@dataclass(frozen=True)
class OCIIndexSelector:
    target: ImagePlatformDescriptor


@dataclass(frozen=True)
class OCIManifestSelector:
    role: Literal["config", "layer"]
    ordinal: int | None


@dataclass(frozen=True)
class RecipeOutputSelector:
    recipe: release_recipe.ReleaseRecipe
    scope: Literal["target-specific", "recipe-shared"]
    target: ImagePlatformDescriptor | None
    path: str


@dataclass(frozen=True, init=False)
class ParsedMetadataDeclaration:
    """A declaration that only one of this module's parsers can create."""

    parser_kind: str
    parser_revision: str
    metadata_size: int
    metadata_sha256: str
    object_name: str
    declared_sha256: str
    declared_size: int | None
    media_type: str | None

    def __init__(
        self,
        parser_kind: str,
        parser_revision: str,
        metadata_size: int,
        metadata_sha256: str,
        object_name: str,
        declared_sha256: str,
        declared_size: int | None,
        media_type: str | None,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _DECLARATION_TOKEN:
            raise PrimeReleaseMetadataError("Prime release metadata is invalid")
        object.__setattr__(self, "parser_kind", parser_kind)
        object.__setattr__(self, "parser_revision", parser_revision)
        object.__setattr__(self, "metadata_size", metadata_size)
        object.__setattr__(self, "metadata_sha256", metadata_sha256)
        object.__setattr__(self, "object_name", object_name)
        object.__setattr__(self, "declared_sha256", declared_sha256)
        object.__setattr__(self, "declared_size", declared_size)
        object.__setattr__(self, "media_type", media_type)


def _invalid() -> PrimeReleaseMetadataError:
    return PrimeReleaseMetadataError("Prime release metadata is invalid")


def _metadata_identity(data: object) -> tuple[int, str]:
    if type(data) is not bytes:
        raise _invalid()
    return len(data), sha256(data).hexdigest()


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _invalid()
    return value


def _size(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _invalid()
    return value


def _target(value: object) -> ImagePlatformDescriptor:
    try:
        target = validate_image_platform_descriptor(value)
        return release_recipe.resolve_candidate_target(target)
    except (ValueError, release_recipe.PrimeReleaseRecipeError):
        raise _invalid() from None


def _declaration(
    parser_kind: str,
    parser_revision: str,
    data: bytes,
    object_name: str,
    digest: str,
    size: int | None,
    media_type: str | None,
) -> ParsedMetadataDeclaration:
    metadata_size, metadata_sha256 = _metadata_identity(data)
    if type(object_name) is not str or not object_name or type(parser_kind) is not str:
        raise _invalid()
    return ParsedMetadataDeclaration(
        parser_kind,
        _digest(parser_revision),
        metadata_size,
        metadata_sha256,
        object_name,
        _digest(digest),
        None if size is None else _size(size),
        media_type,
        _token=_DECLARATION_TOKEN,
    )


def validate_parsed_metadata_declaration(
    value: object,
) -> ParsedMetadataDeclaration:
    """Accept only a well-formed declaration minted by an offline parser.

    This validates the public structural evidence at the hand-off boundary.  The
    constructor remains token-guarded, so callers cannot make a declaration by
    copying fields from a JSON response.
    """

    if type(value) is not ParsedMetadataDeclaration:
        raise _invalid()
    expected_revisions = {
        "node-shasums": release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.node_shasums,
        "oci-index": release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.oci_index,
        "oci-manifest": release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.oci_manifest,
        "pypi-json": release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.pypi_json,
        "recipe-output-manifest": release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.recipe_output_manifest,
    }
    if (
        type(value.parser_kind) is not str
        or value.parser_kind not in expected_revisions
        or value.parser_revision != expected_revisions[value.parser_kind]
        or type(value.metadata_size) is not int
        or value.metadata_size < 0
        or _SHA256.fullmatch(value.metadata_sha256) is None
        or type(value.object_name) is not str
        or not value.object_name
        or _SHA256.fullmatch(value.declared_sha256) is None
        or (value.declared_size is not None and (type(value.declared_size) is not int or value.declared_size < 0))
        or (value.media_type is not None and type(value.media_type) is not str)
    ):
        raise _invalid()
    return value


def validate_declaration_metadata_bytes(
    declaration: object, data: object
) -> ParsedMetadataDeclaration:
    """Bind a parser declaration to the exact bytes it was parsed from."""

    value = validate_parsed_metadata_declaration(declaration)
    size, digest = _metadata_identity(data)
    if size != value.metadata_size or digest != value.metadata_sha256:
        raise _invalid()
    return value


def parse_node_shasums(data: bytes, selector: object) -> ParsedMetadataDeclaration:
    """Select the one target-derived Node archive from SHASUMS256 bytes."""

    if type(selector) is not NodeShasumsSelector or selector.node_version != "22.8.0":
        raise _invalid()
    target = _target(selector.target)
    suffix = "arm64" if target.architecture == "arm64" else "x64"
    name = f"node-v{selector.node_version}-linux-{suffix}.tar.xz"
    try:
        text = data.decode("ascii")
    except (AttributeError, UnicodeDecodeError):
        raise _invalid() from None
    entries = [
        (match.group(1), match.group(2))
        for line in text.splitlines()
        if (match := re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line))
    ]
    matches = [digest for digest, filename in entries if filename == name]
    if len(matches) != 1 or len([filename for _, filename in entries if filename == name]) != 1:
        raise _invalid()
    return _declaration(
        "node-shasums",
        release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.node_shasums,
        data,
        name,
        matches[0],
        None,
        None,
    )


def _wheel_matches_target(filename: str, target: ImagePlatformDescriptor) -> bool:
    if not filename.endswith(".whl") or "-cp312" in filename or "musllinux" in filename:
        return False
    if filename.endswith("-py3-none-any.whl"):
        return True
    expected = "aarch64" if target.architecture == "arm64" else "x86_64"
    other = "x86_64" if expected == "aarch64" else "aarch64"
    return "cp311" in filename and "manylinux" in filename and expected in filename and other not in filename


def parse_pypi_json(data: bytes, selector: object) -> ParsedMetadataDeclaration:
    """Select one Python 3.11 wheel from exact PyPI JSON bytes."""

    if type(selector) is not PyPIFileSelector:
        raise _invalid()
    target = _target(selector.target)
    try:
        value = json.loads(data.decode("utf-8"))
        info = value["info"]
        urls = value["urls"]
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise _invalid() from None
    normalized = selector.normalized_project.replace("_", "-").lower()
    if (
        type(info) is not dict
        or type(info.get("name")) is not str
        or info["name"].replace("_", "-").lower() != normalized
        or info.get("version") != selector.version
        or type(urls) is not list
    ):
        raise _invalid()
    matches = [item for item in urls if type(item) is dict and item.get("filename") == selector.filename]
    if len(matches) != 1:
        raise _invalid()
    selected = matches[0]
    try:
        if selected["packagetype"] != "bdist_wheel" or not _wheel_matches_target(selector.filename, target):
            raise ValueError
        digest = _digest(selected["digests"]["sha256"])
        size = _size(selected["size"])
    except (KeyError, TypeError, ValueError, PrimeReleaseMetadataError):
        raise _invalid() from None
    return _declaration(
        "pypi-json",
        release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.pypi_json,
        data,
        selector.filename,
        digest,
        size,
        None,
    )


def _oci_digest(value: object) -> str:
    if type(value) is not str or not value.startswith("sha256:"):
        raise _invalid()
    return _digest(value.removeprefix("sha256:"))


def _same_platform(value: object, target: ImagePlatformDescriptor) -> bool:
    if type(value) is not dict or set(value) - {"os", "architecture", "variant"}:
        return False
    return value.get("os") == target.os and value.get("architecture") == target.architecture and value.get("variant") == target.variant


def parse_oci_index_descriptor(data: bytes, selector: object) -> ParsedMetadataDeclaration:
    """Select one exact target child manifest from an OCI index."""

    if type(selector) is not OCIIndexSelector:
        raise _invalid()
    target = _target(selector.target)
    try:
        value = json.loads(data.decode("utf-8"))
        manifests = value["manifests"]
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise _invalid() from None
    if type(value) is not dict or value.get("schemaVersion") != 2 or type(manifests) is not list:
        raise _invalid()
    matches = [item for item in manifests if type(item) is dict and _same_platform(item.get("platform"), target)]
    if len(matches) != 1:
        raise _invalid()
    selected = matches[0]
    try:
        digest = _oci_digest(selected["digest"])
        size = _size(selected["size"])
        media_type = selected["mediaType"]
        if type(media_type) is not str or "manifest" not in media_type:
            raise ValueError
    except (KeyError, ValueError, PrimeReleaseMetadataError):
        raise _invalid() from None
    return _declaration(
        "oci-index",
        release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.oci_index,
        data,
        "child-manifest",
        digest,
        size,
        media_type,
    )


def parse_oci_manifest_descriptor(data: bytes, selector: object) -> ParsedMetadataDeclaration:
    """Select one config or ordered layer descriptor from an OCI manifest."""

    if type(selector) is not OCIManifestSelector or selector.role not in {"config", "layer"}:
        raise _invalid()
    try:
        value = json.loads(data.decode("utf-8"))
        config = value["config"]
        layers = value["layers"]
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise _invalid() from None
    if type(value) is not dict or value.get("schemaVersion") != 2 or type(config) is not dict or type(layers) is not list or not layers:
        raise _invalid()
    if selector.role == "config":
        if selector.ordinal is not None:
            raise _invalid()
        selected, object_name = config, "config"
    else:
        if type(selector.ordinal) is not int or selector.ordinal < 0 or selector.ordinal >= len(layers):
            raise _invalid()
        selected, object_name = layers[selector.ordinal], f"layer/{selector.ordinal}"
    if type(selected) is not dict:
        raise _invalid()
    try:
        digest = _oci_digest(selected["digest"])
        size = _size(selected["size"])
        media_type = selected["mediaType"]
        if type(media_type) is not str:
            raise ValueError
    except (KeyError, ValueError, PrimeReleaseMetadataError):
        raise _invalid() from None
    return _declaration(
        "oci-manifest",
        release_recipe.PRIME_IPYTHON_RELEASE_RECIPE.metadata_parsers.oci_manifest,
        data,
        object_name,
        digest,
        size,
        media_type,
    )


def parse_recipe_output_manifest(data: bytes, selector: object) -> ParsedMetadataDeclaration:
    """Validate a locally reproduced output manifest against its exact recipe."""

    if type(selector) is not RecipeOutputSelector or type(selector.path) is not str:
        raise _invalid()
    try:
        recipe = release_recipe.validate_release_recipe(selector.recipe)
        value = json.loads(data.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, release_recipe.PrimeReleaseRecipeError):
        raise _invalid() from None
    if type(value) is not dict or set(value) != {"format", "recipe_sha256", "source", "scope", "target", "path", "size", "sha256"}:
        raise _invalid()
    if value["format"] != "asterion.prime-recipe-output-manifest/v1" or value["recipe_sha256"] != release_recipe.release_recipe_sha256(recipe):
        raise _invalid()
    source = value["source"]
    if type(source) is not dict or source != {
        "commit": recipe.source.commit,
        "tree_sha256": recipe.source.tree_sha256,
        "package_lock_sha256": recipe.source.package_lock_sha256,
    } or value["scope"] != selector.scope or value["path"] != selector.path:
        raise _invalid()
    if selector.scope == "target-specific":
        if selector.target is None:
            raise _invalid()
        target = _target(selector.target)
        if not _same_platform(value["target"], target):
            raise _invalid()
    elif selector.target is not None or value["target"] is not None:
        raise _invalid()
    else:
        raise _invalid()
    return _declaration(
        "recipe-output-manifest",
        recipe.metadata_parsers.recipe_output_manifest,
        data,
        selector.path,
        _digest(value["sha256"]),
        _size(value["size"]),
        None,
    )
