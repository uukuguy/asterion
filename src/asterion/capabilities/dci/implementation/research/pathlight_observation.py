"""Integrity-checked access to Asterion's packaged Pathlight Pi extension."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterator


_MANIFEST_SCHEMA = "dci.pathlight-observation-extension-manifest/v1"
_RESOURCE_NAME = "dci-pathlight-observation.ts"
_MANIFEST_NAME = "pathlight-observation-manifest.json"
_EXTENSION_VERSION = "0.3.0"
_CONTRACT_VERSION = "dci.pathlight-provider-request-capture/v1"
_EXPECTED_SHA256 = "56631fc678af4a18218680fb44005379e842fa21e56633fa38c9eccb760c268f"
_PRIVATE_RECORD_SCHEMA = "dci.private-provider-request/v1"
_SAFE_OBSERVATION_SCHEMA = "dci.provider-request-observation/v1"
_MANIFEST_KEYS = {
    "schema",
    "extension_version",
    "contract_version",
    "resource",
    "byte_length",
    "sha256",
}
_MAX_MANIFEST_BYTES = 16 * 1024
_MAX_RESOURCE_BYTES = 1024 * 1024
_IMPORT_STATEMENT = re.compile(
    r"(?m)^\s*import\s+[^\r\n]+?\s+from\s+[\"']([^\"']+)[\"']\s*;\s*$"
)
_ALLOWED_IMPORTS = frozenset(("node:buffer", "node:crypto", "node:fs"))
_RUNTIME_IMPORT = re.compile(r"(?m)^\s*import\b|\bimport\s*\(|\brequire\s*\(")
_HOOK = re.compile(r"\bpi\s*\.\s*on\s*\(\s*[\"']before_provider_request[\"']")
_ANY_HOOK = re.compile(r"\bpi\s*\.\s*on\s*\(")
_REGISTRATION = re.compile(r"\bregister(?:Provider|Tool|Command)\b")


class PathlightObservationExtensionError(RuntimeError):
    """Safe failure raised when the packaged extension cannot be trusted."""


@dataclass(frozen=True)
class ResolvedPathlightObservationExtension:
    """One verified observation extension whose path is valid in its context."""

    path: Path
    version: str
    sha256: str
    contract_version: str


def _invalid() -> PathlightObservationExtensionError:
    return PathlightObservationExtensionError(
        "DCI Pathlight observation extension is invalid"
    )


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & stat.S_IWOTH
            or metadata.st_size > maximum_bytes
        ):
            raise _invalid()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_mode & stat.S_IWOTH
                or opened.st_size > maximum_bytes
                or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            ):
                raise _invalid()
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                value = stream.read(maximum_bytes + 1)
            closed = os.fstat(descriptor)
            if len(value) > maximum_bytes or (
                closed.st_dev,
                closed.st_ino,
                closed.st_size,
                closed.st_mtime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ):
                raise _invalid()
            return value
        finally:
            os.close(descriptor)
    except PathlightObservationExtensionError:
        raise
    except (OSError, ValueError):
        raise _invalid() from None


def _parse_manifest(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise _invalid() from None
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise _invalid()
    if (
        value.get("schema") != _MANIFEST_SCHEMA
        or value.get("extension_version") != _EXTENSION_VERSION
        or value.get("contract_version") != _CONTRACT_VERSION
        or value.get("resource") != _RESOURCE_NAME
        or isinstance(value.get("byte_length"), bool)
        or not isinstance(value.get("byte_length"), int)
        or not 0 < value["byte_length"] <= _MAX_RESOURCE_BYTES
        or not isinstance(value.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
        or value["sha256"] != _EXPECTED_SHA256
    ):
        raise _invalid()
    return value


def _has_exact_source_identity(text: str) -> bool:
    identities = (
        ("CAPTURE_CONTRACT_VERSION", _CONTRACT_VERSION),
        ("PRIVATE_RECORD_SCHEMA", _PRIVATE_RECORD_SCHEMA),
        ("SAFE_OBSERVATION_SCHEMA", _SAFE_OBSERVATION_SCHEMA),
    )
    return all(
        len(
            re.findall(
                rf"\b{re.escape(name)}\s*=\s*[\"']{re.escape(value)}[\"']\s*;",
                text,
            )
        )
        == 1
        for name, value in identities
    )


def _validate_source(source: bytes, manifest: dict[str, object]) -> str:
    digest = hashlib.sha256(source).hexdigest()
    if (
        len(source) != manifest["byte_length"]
        or digest != manifest["sha256"]
        or digest != _EXPECTED_SHA256
    ):
        raise _invalid()
    try:
        text = source.decode("utf-8")
    except UnicodeError:
        raise _invalid() from None

    import_matches = tuple(_IMPORT_STATEMENT.finditer(text))
    without_allowed_imports = list(text)
    for match in import_matches:
        without_allowed_imports[match.start() : match.end()] = " " * (
            match.end() - match.start()
        )
    remaining = "".join(without_allowed_imports)
    if (
        {match.group(1) for match in import_matches} != _ALLOWED_IMPORTS
        or len(import_matches) != len(_ALLOWED_IMPORTS)
        or _RUNTIME_IMPORT.search(remaining)
        or not _has_exact_source_identity(text)
        or len(_HOOK.findall(text)) != 1
        or len(_ANY_HOOK.findall(text)) != 1
        or _REGISTRATION.search(text)
        or text.count("export default function") != 1
    ):
        raise _invalid()
    return digest


@contextmanager
def resolve_pathlight_observation_extension() -> Iterator[
    ResolvedPathlightObservationExtension
]:
    """Yield the verified package resource without accepting path overrides."""

    try:
        package = resources.files("asterion.capabilities.dci.resources.pi")
        manifest_resource = package.joinpath(_MANIFEST_NAME)
        source_resource = package.joinpath(_RESOURCE_NAME)
        with resources.as_file(manifest_resource) as manifest_path:
            manifest = _parse_manifest(
                _read_regular_file(
                    manifest_path,
                    maximum_bytes=_MAX_MANIFEST_BYTES,
                )
            )
        with resources.as_file(source_resource) as source_path:
            source = _read_regular_file(
                source_path,
                maximum_bytes=_MAX_RESOURCE_BYTES,
            )
            digest = _validate_source(source, manifest)
            yield ResolvedPathlightObservationExtension(
                path=source_path,
                version=_EXTENSION_VERSION,
                sha256=digest,
                contract_version=_CONTRACT_VERSION,
            )
    except PathlightObservationExtensionError:
        raise
    except Exception:
        raise _invalid() from None


__all__ = (
    "PathlightObservationExtensionError",
    "ResolvedPathlightObservationExtension",
    "resolve_pathlight_observation_extension",
)
