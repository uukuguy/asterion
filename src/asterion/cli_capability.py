"""Author-facing capability package commands."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from importlib import resources
from pathlib import Path
from typing import TextIO

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.protocol import CAPABILITY_ID, SEMANTIC_VERSION
from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
)
from asterion.capability_packages.resolution import resolve_capability_source
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
)
from asterion.capability_sdk.conformance import run_capability_conformance


ARCHIVE_UNSUPPORTED = "asterion: capability archive forms are not supported yet\n"
_ERROR = "asterion: command failed\n"
_LOCAL_SOURCE_KIND = "local-directory"
_DEFAULT_VERSION = "0.1.0"
_ARCHIVE_SOURCE_KIND = "archive"
_PACK_SOURCE_KINDS = frozenset({_LOCAL_SOURCE_KIND})
_CONVERT_SOURCE_KINDS = frozenset({_LOCAL_SOURCE_KIND, _ARCHIVE_SOURCE_KIND})
_TEMPLATE_DIRECTORIES = frozenset(
    {
        Path("."),
        Path("payload"),
        Path("payload/benchmark-suites"),
        Path("payload/capabilities"),
        Path("payload/conformance"),
        Path("payload/resources"),
    }
)
_TEMPLATE_FILES = frozenset(
    {
        Path("provider.py"),
        Path("payload/benchmark-suites/suite.json"),
        Path("payload/capabilities/research.json"),
        Path("payload/capability-package.json"),
        Path("payload/conformance/externalization.json"),
        Path("payload/resources/example.conformance"),
    }
)


class CapabilityCliError(ValueError):
    """Raised for stable, body-free capability CLI failures."""


class CapabilityArchiveUnsupported(RuntimeError):
    """Raised after staged archive arguments validate successfully."""


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run ``asterion capability`` author tooling."""

    parser = _parser()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = parser.parse_args(list(argv or ()))
        if args.capability_command == "init":
            return _init(args, stdout)
        if args.capability_command == "validate":
            return _validate(args, stdout)
        if args.capability_command == "inspect":
            return _inspect(args, stdout)
        if args.capability_command == "test":
            return _test(args, stdout)
        if args.capability_command == "pack":
            _validate_pack(args)
        if args.capability_command == "convert":
            _validate_convert(args)
        raise CapabilityCliError("capability command is invalid")
    except CapabilityArchiveUnsupported:
        stderr.write(ARCHIVE_UNSUPPORTED)
        return 2
    except (
        CapabilityCliError,
        OSError,
        TypeError,
        ValueError,
    ):
        stderr.write(_ERROR)
        return 2


def add_capability_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the top-level help entry for author commands."""

    capability = subparsers.add_parser(
        "capability",
        help="author capability packages; pack and convert are staged",
        description=(
            "Author capability packages. pack and convert are staged until the "
            "archive-form plan is approved."
        ),
    )
    capability.add_argument("capability_args", nargs=argparse.REMAINDER)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asterion capability",
        description=(
            "Author capability packages. pack and convert are staged until the "
            "archive-form plan is approved."
        ),
    )
    subparsers = parser.add_subparsers(dest="capability_command", required=True)

    init = subparsers.add_parser(
        "init",
        help="copy the closed local package template",
    )
    init.add_argument("target")
    init.add_argument("--package-id", required=True)
    init.add_argument("--version", default=_DEFAULT_VERSION)

    validate = subparsers.add_parser(
        "validate",
        help="validate a portable payload closure",
    )
    validate.add_argument("payload_root")

    inspect = subparsers.add_parser(
        "inspect",
        help="inspect explicit local source metadata without importing providers",
    )
    _add_local_source_arguments(inspect)

    test = subparsers.add_parser(
        "test",
        help="run provider-free public conformance for an explicit local source",
    )
    _add_local_source_arguments(test)

    pack = subparsers.add_parser(
        "pack",
        help="validate staged archive-pack arguments",
    )
    pack.add_argument("--package", required=True)
    pack.add_argument("--source", required=True)
    pack.add_argument("--output", required=True)

    convert = subparsers.add_parser(
        "convert",
        help="validate staged form-conversion arguments",
    )
    convert.add_argument("--package", required=True)
    convert.add_argument("--from", dest="from_kind", required=True)
    convert.add_argument("--to", dest="to_kind", required=True)
    convert.add_argument("--output", required=True)
    return parser


def _add_local_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--payload-root", required=True)
    parser.add_argument("--module-path", required=True)
    parser.add_argument("--factory-name", required=True)
    parser.add_argument("--payload-sha256", required=True)


def _init(args: argparse.Namespace, stdout: TextIO) -> int:
    package_ref = _package_ref_from_parts(args.package_id, args.version)
    target = _new_target_directory(args.target)
    template_root = _template_root()
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent))
    )
    try:
        _copy_template_closed(template_root, temporary)
        _customize_template(temporary, package_ref)
        open_portable_payload(temporary / "payload")
        os.replace(temporary, target)
    except BaseException:
        _remove_tree(temporary)
        raise
    stdout.write(json.dumps({"created": _package_selector(package_ref)}, sort_keys=True) + "\n")
    return 0


def _validate(args: argparse.Namespace, stdout: TextIO) -> int:
    payload = open_portable_payload(_canonical_existing_directory(Path(args.payload_root)))
    stdout.write(json.dumps(_payload_summary(payload), sort_keys=True) + "\n")
    return 0


def _inspect(args: argparse.Namespace, stdout: TextIO) -> int:
    package_ref, source, candidate = _selected_local_source(args)
    payload = source.open_payload(candidate)
    source.validate_source_identity(candidate, payload)
    summary = _payload_summary(payload)
    summary.update(
        {
            "package": _package_selector(package_ref),
            "source_id": candidate.source_id,
            "source_kind": candidate.source_kind,
            "capabilities": [
                _capability_selector(ref) for ref in payload.manifest.capabilities
            ],
            "benchmark_suites": [
                f"{ref.suite_id}@{ref.version}"
                for ref in payload.manifest.benchmark_suites
            ],
            "metadata": dict(candidate.metadata),
        }
    )
    stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


def _test(args: argparse.Namespace, stdout: TextIO) -> int:
    _, source, candidate = _selected_local_source(args)
    payload = source.open_payload(candidate)
    source.validate_source_identity(candidate, payload)
    installed = source.load_provider(candidate)
    result = run_capability_conformance(installed)
    stdout.write(
        json.dumps(
            {"passed": result.passed, "errors": list(result.errors)},
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if result.passed else 1


def _validate_pack(args: argparse.Namespace) -> None:
    _parse_package_selector(args.package)
    _validate_source_kind(args.source, allowed=_PACK_SOURCE_KINDS)
    _validate_future_output(args.output)
    raise CapabilityArchiveUnsupported()


def _validate_convert(args: argparse.Namespace) -> None:
    _parse_package_selector(args.package)
    from_kind = _validate_source_kind(args.from_kind, allowed=_CONVERT_SOURCE_KINDS)
    to_kind = _validate_source_kind(args.to_kind, allowed=_CONVERT_SOURCE_KINDS)
    if from_kind == to_kind:
        raise CapabilityCliError("capability conversion source and target are invalid")
    _validate_future_output(args.output)
    raise CapabilityArchiveUnsupported()


def _selected_local_source(
    args: argparse.Namespace,
) -> tuple[
    CapabilityPackageRef,
    LocalDirectoryCapabilityPackageSource,
    CapabilityPackageCandidate,
]:
    package_ref = _parse_package_selector(args.package)
    root = _local_root(args.root)
    declaration = CapabilitySourceDeclaration(
        source_id=_source_id(args.source_id),
        kind=_LOCAL_SOURCE_KIND,
        package_ref=package_ref,
        payload_sha256=_digest(args.payload_sha256),
        private_locator={
            "root": root,
            "payload_root": args.payload_root,
            "module_path": args.module_path,
            "factory_name": _factory_name(args.factory_name),
        },
    )
    source = LocalDirectoryCapabilityPackageSource((declaration,))
    candidate = resolve_capability_source(
        package_ref,
        source.discover_metadata(),
        None,
    )
    return package_ref, source, candidate


def _payload_summary(payload: PortableCapabilityPayload) -> dict[str, object]:
    manifest = payload.manifest
    return {
        "package_id": manifest.package_ref.package_id,
        "version": manifest.package_ref.version,
        "payload_sha256": payload.payload_sha256,
        "capability_count": len(manifest.capabilities),
        "benchmark_suite_count": len(manifest.benchmark_suites),
        "resource_count": len(manifest.resources),
        "conformance_count": len(manifest.conformance),
    }


def _template_root() -> Path:
    return Path(str(resources.files("asterion.capability_sdk"))) / "templates/minimal"


def _copy_template_closed(source: Path, target: Path) -> None:
    root = _canonical_existing_directory(source)
    seen_directories: set[Path] = set()
    seen_files: set[Path] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise CapabilityCliError("capability template is invalid")
        if path.is_dir():
            if relative not in _TEMPLATE_DIRECTORIES:
                raise CapabilityCliError("capability template is invalid")
            seen_directories.add(relative)
            continue
        if path.is_file():
            if relative not in _TEMPLATE_FILES:
                raise CapabilityCliError("capability template is invalid")
            seen_files.add(relative)
            continue
        raise CapabilityCliError("capability template is invalid")
    if seen_directories != _TEMPLATE_DIRECTORIES - {Path(".")} or seen_files != _TEMPLATE_FILES:
        raise CapabilityCliError("capability template is invalid")
    for directory in sorted(_TEMPLATE_DIRECTORIES):
        if directory == Path("."):
            continue
        (target / directory).mkdir()
    for relative in sorted(_TEMPLATE_FILES):
        source_path = root / relative
        target_path = target / relative
        target_path.write_bytes(source_path.read_bytes())


def _remove_tree(root: Path) -> None:
    if not root.exists() and not root.is_symlink():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
    root.rmdir()


def _customize_template(root: Path, package_ref: CapabilityPackageRef) -> None:
    payload_root = root / "payload"
    capability_ref = CapabilityRef(f"{package_ref.package_id}.research", package_ref.version)
    suite_id = f"{package_ref.package_id}.suite"
    binding_id = f"{package_ref.package_id}.task"
    task_id = binding_id

    _write_json(
        payload_root / "capability-package.json",
        {
            "protocol": "asterion.capability-package/v1",
            "package_id": package_ref.package_id,
            "version": package_ref.version,
            "capabilities": [
                {
                    "capability_id": capability_ref.capability_id,
                    "version": capability_ref.version,
                }
            ],
            "benchmark_suites": [{"suite_id": suite_id, "version": package_ref.version}],
            "resources": [
                {
                    "resource_id": "example.conformance",
                    "media_type": "application/json",
                    "sha256": "0977396ff554935ae109aad975aa8d857b65a7fa55f0c52f2a579ffe8d1523f3",
                }
            ],
            "conformance": [
                {
                    "resource_id": "externalization.json",
                    "media_type": "application/json",
                    "sha256": "516f209e7d4076b2897f2e5c282f709d7c31c7be334e2a80e2a7a6b82e3aecab",
                }
            ],
        },
    )
    _write_json(
        payload_root / "capabilities" / "research.json",
        {
            "protocol": "asterion.capability/v1",
            "capability_id": capability_ref.capability_id,
            "version": capability_ref.version,
            "kind": "research",
            "provides_capabilities": ["research.local"],
            "requires_capabilities": [],
            "requires_policies": [],
            "emits_events": ["research.completed"],
            "consumes_events": [],
            "produces_artifacts": ["application/vnd.example.research+json"],
            "consumes_artifacts": [],
        },
    )
    _write_json(
        payload_root / "benchmark-suites" / "suite.json",
        {
            "protocol": "asterion.benchmark-suite/v1",
            "suite_id": suite_id,
            "version": package_ref.version,
            "owner_package": {
                "package_id": package_ref.package_id,
                "version": package_ref.version,
            },
            "tasks": [
                {
                    "task_id": task_id,
                    "capability": {
                        "capability_id": capability_ref.capability_id,
                        "version": capability_ref.version,
                    },
                    "binding_id": binding_id,
                    "metric_contract_id": "example.metric/v1",
                    "result_contract_id": "example.result/v1",
                    "note": "",
                }
            ],
            "artifact_media_types": ["application/json"],
            "default_case_limit": 1,
            "default_concurrency": 1,
        },
    )
    payload_sha256 = open_portable_payload(payload_root).payload_sha256
    (root / "provider.py").write_text(
        _provider_template(package_ref, capability_ref, binding_id, payload_sha256),
        encoding="utf-8",
    )


def _provider_template(
    package_ref: CapabilityPackageRef,
    capability_ref: CapabilityRef,
    binding_id: str,
    payload_sha256: str,
) -> str:
    return f'''\
"""Asterion capability package provider template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
)


PAYLOAD_SHA256 = "{payload_sha256}"


class ResearchImplementation:
    async def execute(self, invocation):
        raise NotImplementedError("replace the template implementation")


def create_package():
    payload_root = Path(__file__).resolve().parent / "payload"
    package_ref = CapabilityPackageRef("{package_ref.package_id}", "{package_ref.version}")
    implementation = ResearchImplementation()
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256=PAYLOAD_SHA256,
        source_id="{package_ref.package_id}.local-directory",
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=cast(
            Any,
            (
                (CapabilityRef("{capability_ref.capability_id}", "{capability_ref.version}"), implementation),
            ),
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=package_ref,
                binding_id="{binding_id}",
                implementation=implementation,
            ),
        ),
    )
'''


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _new_target_directory(value: object) -> Path:
    raw = _future_path(value, error_message="capability template target is invalid")
    if raw.exists() or raw.is_symlink():
        raise CapabilityCliError("capability template target is invalid")
    parent = _canonical_existing_directory(raw.parent)
    return parent / raw.name


def _canonical_existing_directory(path: Path) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise CapabilityCliError("capability directory is invalid")
    resolved = _resolve_without_symlinks(raw)
    if not resolved.is_dir() or raw.is_symlink():
        raise CapabilityCliError("capability directory is invalid")
    return resolved


def _validate_future_output(value: object) -> Path:
    raw = _future_path(value, error_message="capability output is invalid")
    if raw.exists() or raw.is_symlink():
        raise CapabilityCliError("capability output is invalid")
    parent = _canonical_existing_directory(raw.parent)
    return parent / raw.name


def _future_path(value: object, *, error_message: str) -> Path:
    text = _path_text(value, error_message=error_message)
    _reject_dot_components(text, error_message=error_message)
    path = Path(text).expanduser()
    if path.name in {"", ".", ".."}:
        raise CapabilityCliError(error_message)
    return path


def _local_root(value: object) -> Path:
    text = _path_text(value, error_message="capability directory is invalid")
    _reject_dot_components(text, error_message="capability directory is invalid")
    path = Path(text)
    if not path.is_absolute():
        raise CapabilityCliError("capability directory is invalid")
    return path


def _path_text(value: object, *, error_message: str) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise CapabilityCliError(error_message)
    text = os.fspath(value)
    if not isinstance(text, str) or text == "":
        raise CapabilityCliError(error_message)
    return text


def _reject_dot_components(text: str, *, error_message: str) -> None:
    if any(component in {".", ".."} for component in text.split(os.sep)):
        raise CapabilityCliError(error_message)


def _resolve_without_symlinks(path: Path) -> Path:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    failed = False
    for part in absolute.parts[1:]:
        if part in {"", "."}:
            continue
        if part == "..":
            raise CapabilityCliError("capability directory is invalid")
        current = current / part
        try:
            if current.is_symlink():
                failed = True
                break
            current.lstat()
        except OSError:
            failed = True
            break
    if failed:
        raise CapabilityCliError("capability directory is invalid")
    try:
        return absolute.resolve(strict=True)
    except OSError:
        raise CapabilityCliError("capability directory is invalid") from None


def _parse_package_selector(value: object) -> CapabilityPackageRef:
    if not isinstance(value, str):
        raise CapabilityCliError("capability package selector is invalid")
    package_id, separator, version = value.partition("@")
    if not separator or "@" in version:
        raise CapabilityCliError("capability package selector is invalid")
    return _package_ref_from_parts(package_id, version)


def _package_ref_from_parts(package_id: object, version: object) -> CapabilityPackageRef:
    if (
        not isinstance(package_id, str)
        or CAPABILITY_ID.fullmatch(package_id) is None
        or not isinstance(version, str)
        or SEMANTIC_VERSION.fullmatch(version) is None
    ):
        raise CapabilityCliError("capability package selector is invalid")
    return CapabilityPackageRef(package_id, version)


def _validate_source_kind(value: object, *, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise CapabilityCliError("capability source kind is invalid")
    return value


def _source_id(value: object) -> str:
    if not isinstance(value, str) or CAPABILITY_ID.fullmatch(value) is None:
        raise CapabilityCliError("capability source id is invalid")
    return value


def _factory_name(value: object) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise CapabilityCliError("capability factory name is invalid")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise CapabilityCliError("capability payload digest is invalid")
    return value


def _package_selector(package_ref: CapabilityPackageRef) -> str:
    return f"{package_ref.package_id}@{package_ref.version}"


def _capability_selector(capability_ref: CapabilityRef) -> str:
    return f"{capability_ref.capability_id}@{capability_ref.version}"


__all__ = (
    "ARCHIVE_UNSUPPORTED",
    "CapabilityArchiveUnsupported",
    "CapabilityCliError",
    "add_capability_parser",
    "main",
)
