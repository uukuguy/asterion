"""Exact host-resolved extension bindings and pinned process resources."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from asterion.immutable import RedactedImmutableMapping


_IDENTITY = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*")
_SOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.mjs")
_NODE_SPECIFIER = re.compile(r"node:[A-Za-z0-9][A-Za-z0-9_./-]*")
_SOURCE_FD = "ASTERION_PI_EXTENSION_SOURCE_FD"
_SOURCE_NAME_ENV = "ASTERION_PI_EXTENSION_SOURCE_NAME"
_SOURCE_SHA256 = "ASTERION_PI_EXTENSION_SOURCE_SHA256"
_RESERVED_ENVIRONMENT_PREFIX = "ASTERION_PI_EXTENSION_"
_LOADER_FILENAME = "asterion_pi_extension_loader.mjs"
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_BINDING_FINGERPRINT_DOMAIN = b"asterion.pi-extension-binding/v1\0"


@dataclass(frozen=True, slots=True)
class _JavaScriptToken:
    kind: str
    value: str


def pi_extension_loader_path() -> Path:
    """Return the installed Asterion-owned pinned-extension loader path."""

    return Path(__file__).resolve().parent / "resources" / _LOADER_FILENAME


@dataclass(frozen=True, repr=False, slots=True)
class PiExtensionBinding:
    extension_id: str
    path: Path
    capabilities: tuple[str, ...]
    inherited_fds: tuple[int, ...]
    environment: Mapping[str, str]
    _binding_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.extension_id) is not str
            or _IDENTITY.fullmatch(self.extension_id) is None
            or not isinstance(self.path, Path)
            or not self.path.is_absolute()
        ):
            raise ValueError("Pi extension binding is invalid")
        try:
            resolved = self.path.resolve(strict=True)
        except OSError:
            raise ValueError("Pi extension binding is invalid") from None
        if resolved != self.path or not self.path.is_file():
            raise ValueError("Pi extension binding is invalid")
        if (
            type(self.capabilities) is not tuple
            or not self.capabilities
            or any(
                type(capability) is not str
                or _IDENTITY.fullmatch(capability) is None
                for capability in self.capabilities
            )
            or tuple(sorted(set(self.capabilities))) != self.capabilities
        ):
            raise ValueError("Pi extension binding is invalid")
        if (
            type(self.inherited_fds) is not tuple
            or any(type(fd) is not int or fd < 3 for fd in self.inherited_fds)
            or tuple(sorted(set(self.inherited_fds))) != self.inherited_fds
        ):
            raise ValueError("Pi extension binding is invalid")
        if not isinstance(self.environment, Mapping):
            raise ValueError("Pi extension binding is invalid")
        environment = dict(self.environment)
        environment_prefix = (
            "ASTERION_" + re.sub(r"[.-]", "_", self.extension_id).upper() + "_"
        )
        if any(
            type(name) is not str
            or not name.startswith(environment_prefix)
            or name.startswith(_RESERVED_ENVIRONMENT_PREFIX)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None
            or type(value) is not str
            or "\x00" in value
            for name, value in environment.items()
        ):
            raise ValueError("Pi extension binding is invalid")
        declared_fds: list[int] = []
        for name, value in environment.items():
            if not name.endswith("_FD"):
                continue
            if re.fullmatch(r"[1-9][0-9]*", value) is None:
                raise ValueError("Pi extension binding is invalid")
            declared_fds.append(int(value))
        if tuple(sorted(declared_fds)) != self.inherited_fds:
            raise ValueError("Pi extension binding is invalid")
        object.__setattr__(self, "environment", RedactedImmutableMapping(environment))
        canonical = json.dumps(
            {
                "capabilities": list(self.capabilities),
                "environment": environment,
                "extension_id": self.extension_id,
                "inherited_fds": list(self.inherited_fds),
                "path": str(self.path),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        object.__setattr__(
            self,
            "_binding_fingerprint",
            hashlib.sha256(_BINDING_FINGERPRINT_DOMAIN + canonical).hexdigest(),
        )

    def __repr__(self) -> str:
        return "<PiExtensionBinding redacted>"

    @property
    def binding_fingerprint(self) -> str:
        """Return the opaque canonical identity copied into this binding's lease."""

        return self._binding_fingerprint

    def preflight(self, loader_path: Path | None = None) -> PiExtensionLease:
        """Pin validated source bytes, loader identity, and declared resources."""

        return PiExtensionLease.open(
            self,
            pi_extension_loader_path() if loader_path is None else loader_path,
        )


class PiExtensionLease:
    """One single-run ownership lease for pinned extension resources."""

    __slots__ = (
        "environment",
        "inherited_fds",
        "loader_path",
        "sensitive_values",
        "_binding_fingerprint",
        "_closed",
        "_fd_identities",
        "_initialized",
        "_loader_digest",
        "_loader_fd",
    )

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        inherited_fds: tuple[int, ...],
        loader_path: Path,
        sensitive_values: tuple[str | int, ...],
        binding_fingerprint: str,
        fd_identities: Mapping[int, tuple[int, int, int, int]],
        loader_digest: str,
        loader_fd: int,
    ) -> None:
        self.environment = RedactedImmutableMapping(environment)
        self.inherited_fds = inherited_fds
        self.loader_path = loader_path
        self.sensitive_values = sensitive_values
        self._binding_fingerprint = binding_fingerprint
        self._fd_identities = dict(fd_identities)
        self._loader_digest = loader_digest
        self._loader_fd = loader_fd
        self._closed = False
        self._initialized = True

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, "_initialized"):
            raise AttributeError("Pi extension lease is immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Pi extension lease is immutable")

    @classmethod
    def open(
        cls, binding: PiExtensionBinding, loader_path: Path
    ) -> PiExtensionLease:
        owned: list[int] = []
        try:
            source = _read_exact_source(binding.path)
            _validate_source(binding.path.name, source)
            source_fd = _snapshot_source(source)
            owned.append(source_fd)
            replacements: dict[int, int] = {}
            for descriptor in binding.inherited_fds:
                before = _fd_identity(descriptor)
                duplicate = os.dup(descriptor)
                owned.append(duplicate)
                os.set_inheritable(duplicate, False)
                if (
                    _fd_identity(duplicate) != before
                    or _fd_identity(descriptor) != before
                ):
                    raise OSError
                replacements[descriptor] = duplicate

            exact_loader = loader_path.resolve(strict=True)
            if exact_loader != loader_path or loader_path.name != _LOADER_FILENAME:
                raise OSError
            loader_fd = _open_regular(loader_path)
            owned.append(loader_fd)
            loader = _read_fd(loader_fd, _MAX_SOURCE_BYTES)
            os.lseek(loader_fd, 0, os.SEEK_SET)
            loader_digest = hashlib.sha256(loader).hexdigest()

            environment = {
                name: str(replacements[int(value)]) if name.endswith("_FD") else value
                for name, value in binding.environment.items()
            }
            source_digest = hashlib.sha256(source).hexdigest()
            environment.update(
                {
                    _SOURCE_FD: str(source_fd),
                    _SOURCE_NAME_ENV: binding.path.name,
                    _SOURCE_SHA256: source_digest,
                }
            )
            process_fds = tuple(sorted((source_fd, *replacements.values())))
            identities = {fd: _fd_identity(fd) for fd in process_fds}
            sensitive = tuple(
                sorted(
                    {
                        str(binding.path),
                        str(loader_path),
                        *binding.environment.keys(),
                        *binding.environment.values(),
                        *environment.keys(),
                        *environment.values(),
                    },
                    key=len,
                    reverse=True,
                )
            )
            owned.remove(loader_fd)
            for descriptor in process_fds:
                owned.remove(descriptor)
            return cls(
                environment=environment,
                inherited_fds=process_fds,
                loader_path=loader_path,
                sensitive_values=(
                    *sensitive,
                    *binding.inherited_fds,
                    *process_fds,
                ),
                binding_fingerprint=binding.binding_fingerprint,
                fd_identities=identities,
                loader_digest=loader_digest,
                loader_fd=loader_fd,
            )
        except (OSError, TypeError, ValueError, UnicodeError):
            for descriptor in reversed(owned):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise ValueError("Pi extension binding is unavailable") from None

    def __repr__(self) -> str:
        return "<PiExtensionLease redacted>"

    @property
    def binding_fingerprint(self) -> str:
        """Return the immutable identity of the binding that created this lease."""

        return self._binding_fingerprint

    @property
    def closed(self) -> bool:
        return self._closed

    def command_args(self) -> tuple[str, str]:
        return ("--extension", str(self.loader_path))

    def validate_launch(self) -> None:
        if self._closed:
            raise ValueError("Pi extension lease is closed")
        try:
            path_details = os.stat(self.loader_path, follow_symlinks=False)
            held_details = os.fstat(self._loader_fd)
            if _stat_identity(path_details) != _stat_identity(held_details):
                raise OSError
            loader = _read_fd(self._loader_fd, _MAX_SOURCE_BYTES)
            os.lseek(self._loader_fd, 0, os.SEEK_SET)
            if hashlib.sha256(loader).hexdigest() != self._loader_digest:
                raise OSError
            for descriptor, identity in self._fd_identities.items():
                if _fd_identity(descriptor) != identity:
                    raise OSError
            source_fd = int(self.environment[_SOURCE_FD])
            os.lseek(source_fd, 0, os.SEEK_SET)
        except OSError:
            raise ValueError("Pi extension lease is unavailable") from None

    def close(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        for descriptor in (*self.inherited_fds, self._loader_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _open_regular(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        details = os.fstat(descriptor)
        path_details = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(details.st_mode)
            or _stat_identity(details) != _stat_identity(path_details)
        ):
            raise OSError
    except (OSError, TypeError, ValueError):
        os.close(descriptor)
        raise
    return descriptor


def _read_exact_source(path: Path) -> bytes:
    descriptor = _open_regular(path)
    try:
        if path.resolve(strict=True) != path:
            raise OSError
        return _read_fd(descriptor, _MAX_SOURCE_BYTES)
    finally:
        os.close(descriptor)


def _read_fd(descriptor: int, limit: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, min(64 * 1024, limit + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise OSError
    return b"".join(chunks)


def _snapshot_source(source: bytes) -> int:
    with tempfile.TemporaryFile() as snapshot:
        snapshot.write(source)
        snapshot.flush()
        snapshot.seek(0)
        descriptor = os.dup(snapshot.fileno())
    try:
        os.set_inheritable(descriptor, False)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _validate_source(name: str, source: bytes) -> None:
    if _SOURCE_NAME.fullmatch(name) is None or not source:
        raise ValueError
    text = source.decode("utf-8")
    if "\x00" in text:
        raise ValueError
    tokens = _javascript_tokens(text)
    _validate_javascript_dependencies(tokens)
    if not any(
        token.kind == "identifier"
        and token.value == "export"
        and index + 1 < len(tokens)
        and tokens[index + 1].kind == "identifier"
        and tokens[index + 1].value == "default"
        for index, token in enumerate(tokens)
    ):
        raise ValueError


def _javascript_tokens(source: str) -> tuple[_JavaScriptToken, ...]:
    tokens: list[_JavaScriptToken] = []
    index = 0
    while index < len(source):
        character = source[index]
        if character.isspace():
            index += 1
            continue
        if character in {'"', "'"}:
            value, index = _quoted_javascript_value(source, index, character)
            tokens.append(_JavaScriptToken("string", value))
            continue
        if character == "`":
            value, index = _template_javascript_value(source, index)
            tokens.append(_JavaScriptToken("template", value))
            continue
        if character == "/" and index + 1 < len(source):
            if source[index + 1] in {"/", "*"}:
                raise ValueError
        if character.isalpha() or character in {"_", "$"}:
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] in {"_", "$"}
            ):
                end += 1
            tokens.append(_JavaScriptToken("identifier", source[index:end]))
            index = end
            continue
        tokens.append(_JavaScriptToken("punctuator", character))
        index += 1
    return tuple(tokens)


def _quoted_javascript_value(
    source: str, start: int, quote: str
) -> tuple[str, int]:
    value: list[str] = []
    index = start + 1
    while index < len(source):
        character = source[index]
        if character == quote:
            return "".join(value), index + 1
        if character in {"\r", "\n"}:
            raise ValueError
        if character == "\\":
            if index + 1 >= len(source):
                raise ValueError
            value.extend((character, source[index + 1]))
            index += 2
            continue
        value.append(character)
        index += 1
    raise ValueError


def _template_javascript_value(source: str, start: int) -> tuple[str, int]:
    value: list[str] = []
    index = start + 1
    while index < len(source):
        character = source[index]
        if character == "`":
            return "".join(value), index + 1
        if character == "\\":
            if index + 1 >= len(source):
                raise ValueError
            value.extend((character, source[index + 1]))
            index += 2
            continue
        if character == "$" and index + 1 < len(source) and source[index + 1] == "{":
            raise ValueError
        value.append(character)
        index += 1
    raise ValueError


def _validate_javascript_dependencies(
    tokens: tuple[_JavaScriptToken, ...],
) -> None:
    for index, token in enumerate(tokens):
        if token.kind != "identifier" or (
            index > 0 and tokens[index - 1].value == "."
        ):
            continue
        if token.value == "import":
            _validate_javascript_import(tokens, index)
        elif token.value == "export":
            _validate_javascript_export(tokens, index)


def _validate_javascript_import(
    tokens: tuple[_JavaScriptToken, ...], index: int
) -> None:
    cursor = index + 1
    if cursor >= len(tokens):
        raise ValueError
    following = tokens[cursor]
    if following.value == "(":
        raise ValueError
    if following.value == ".":
        if (
            cursor + 1 < len(tokens)
            and tokens[cursor + 1].kind == "identifier"
            and tokens[cursor + 1].value == "meta"
        ):
            return
        raise ValueError
    if following.kind == "string":
        _validate_node_specifier(following.value)
        return

    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.value in depths:
            depths[token.value] += 1
        elif token.value in closing:
            opener = closing[token.value]
            depths[opener] -= 1
            if depths[opener] < 0:
                raise ValueError
        elif token.value == ";" and not any(depths.values()):
            raise ValueError
        elif (
            token.kind == "identifier"
            and token.value == "from"
            and not any(depths.values())
        ):
            if cursor + 1 >= len(tokens) or tokens[cursor + 1].kind != "string":
                raise ValueError
            _validate_node_specifier(tokens[cursor + 1].value)
            return
        cursor += 1
    raise ValueError


def _validate_javascript_export(
    tokens: tuple[_JavaScriptToken, ...], index: int
) -> None:
    cursor = index + 1
    if cursor >= len(tokens):
        raise ValueError
    following = tokens[cursor]
    if following.kind == "identifier" and following.value in {
        "default",
        "var",
        "let",
        "const",
        "function",
        "class",
    }:
        return
    if following.kind == "identifier" and following.value == "async":
        if (
            cursor + 1 < len(tokens)
            and tokens[cursor + 1].kind == "identifier"
            and tokens[cursor + 1].value == "function"
        ):
            return
        raise ValueError
    if following.value == "*":
        raise ValueError
    if following.value != "{":
        raise ValueError
    closing = _matching_javascript_brace(tokens, cursor)
    if (
        closing + 1 < len(tokens)
        and tokens[closing + 1].kind == "identifier"
        and tokens[closing + 1].value == "from"
    ):
        raise ValueError


def _matching_javascript_brace(
    tokens: tuple[_JavaScriptToken, ...], start: int
) -> int:
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].value == "{":
            depth += 1
        elif tokens[index].value == "}":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                break
    raise ValueError


def _validate_node_specifier(specifier: str) -> None:
    if _NODE_SPECIFIER.fullmatch(specifier) is None:
        raise ValueError


def _fd_identity(descriptor: int) -> tuple[int, int, int, int]:
    return _stat_identity(os.fstat(descriptor))


def _stat_identity(details: os.stat_result) -> tuple[int, int, int, int]:
    return (details.st_dev, details.st_ino, details.st_mode, details.st_rdev)
