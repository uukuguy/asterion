"""Integrity-checked access to Asterion's packaged DCI Pi extension."""

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


_MANIFEST_SCHEMA = "dci.context-extension-manifest/v1"
_RESOURCE_NAME = "dci-context-extension.ts"
_MANIFEST_NAME = "context-extension-manifest.json"
_MANIFEST_KEYS = {
    "schema",
    "extension_version",
    "contract_version",
    "resource",
    "byte_length",
    "sha256",
}
_RUNTIME_IMPORT = re.compile(r"(?m)^\s*(?:import(?:\s|\()|.*\brequire\s*\()")


class ContextExtensionError(RuntimeError):
    """Safe failure raised when the packaged extension cannot be trusted."""


@dataclass(frozen=True)
class ResolvedContextExtension:
    """One verified extension resource whose path is valid in its context."""

    path: Path
    version: str
    sha256: str
    contract_version: str


def _read_regular_file(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & stat.S_IWOTH
        ):
            raise ContextExtensionError("DCI context extension is invalid")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_mode & stat.S_IWOTH:
                raise ContextExtensionError("DCI context extension is invalid")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)
    except ContextExtensionError:
        raise
    except (OSError, ValueError) as error:
        raise ContextExtensionError("DCI context extension is invalid") from error


def _parse_manifest(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContextExtensionError("DCI context extension is invalid") from error
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise ContextExtensionError("DCI context extension is invalid")
    if (
        value.get("schema") != _MANIFEST_SCHEMA
        or value.get("resource") != _RESOURCE_NAME
        or not isinstance(value.get("extension_version"), str)
        or not value["extension_version"]
        or not isinstance(value.get("contract_version"), str)
        or not value["contract_version"]
        or isinstance(value.get("byte_length"), bool)
        or not isinstance(value.get("byte_length"), int)
        or value["byte_length"] <= 0
        or not isinstance(value.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ContextExtensionError("DCI context extension is invalid")
    return value


def _validate_source(source: bytes, manifest: dict[str, object]) -> str:
    digest = hashlib.sha256(source).hexdigest()
    if len(source) != manifest["byte_length"] or digest != manifest["sha256"]:
        raise ContextExtensionError("DCI context extension is invalid")
    try:
        text = source.decode("utf-8")
    except UnicodeError as error:
        raise ContextExtensionError("DCI context extension is invalid") from error
    if _RUNTIME_IMPORT.search(text) or "export default function" not in text:
        raise ContextExtensionError("DCI context extension is invalid")
    return digest


@contextmanager
def resolve_context_extension() -> Iterator[ResolvedContextExtension]:
    """Yield the verified package resource without accepting path overrides."""

    try:
        package = resources.files("asterion.dci.resources.pi")
        manifest_resource = package.joinpath(_MANIFEST_NAME)
        source_resource = package.joinpath(_RESOURCE_NAME)
        with resources.as_file(manifest_resource) as manifest_path:
            manifest = _parse_manifest(_read_regular_file(manifest_path))
        with resources.as_file(source_resource) as source_path:
            source = _read_regular_file(source_path)
            digest = _validate_source(source, manifest)
            yield ResolvedContextExtension(
                path=source_path,
                version=str(manifest["extension_version"]),
                sha256=digest,
                contract_version=str(manifest["contract_version"]),
            )
    except ContextExtensionError:
        raise
    except (FileNotFoundError, ModuleNotFoundError, OSError, TypeError, ValueError) as error:
        raise ContextExtensionError("DCI context extension is invalid") from error
