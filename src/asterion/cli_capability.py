"""Provider-free capability package author commands."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TextIO

from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    IDENTIFIER,
    SEMANTIC_VERSION,
    CapabilitySourceDeclaration,
)
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
)
from asterion.capability_sdk import run_capability_conformance


_TEMPLATE_PACKAGE = "asterion.capability_sdk._template"
_LOCAL_SOURCE_ID = "example.local"
_LOCAL_FACTORY_MODULE = "example.provider"
_LOCAL_FACTORY_NAME = "create_provider"
_STAGED_BOUNDARY = "unsupported pending archive-form approval"


def add_capability_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the capability-package author command group."""

    capability = subparsers.add_parser(
        "capability",
        help="author and check portable capability packages",
        description=(
            "Author and check portable capability packages. "
            "pack and convert remain unavailable pending archive-form approval."
        ),
    )
    commands = capability.add_subparsers(
        dest="capability_command",
        required=True,
    )

    init = commands.add_parser(
        "init",
        help="copy the checked-in minimal author template",
    )
    init.add_argument("target", metavar="TARGET")

    validate = commands.add_parser(
        "validate",
        help="validate one portable payload",
    )
    validate.add_argument("payload", metavar="PAYLOAD")

    inspect = commands.add_parser(
        "inspect",
        help="print safe portable-payload identities",
    )
    inspect.add_argument("payload", metavar="PAYLOAD")

    test = commands.add_parser(
        "test",
        help="run public conformance for one canonical local author source",
    )
    test.add_argument("source", metavar="SOURCE")

    for name in ("pack", "convert"):
        staged = commands.add_parser(
            name,
            help=f"{_STAGED_BOUNDARY}",
            description=f"{name} is {_STAGED_BOUNDARY}.",
        )
        staged.add_argument(
            "target",
            metavar="PACKAGE@VERSION",
            type=_exact_package_selector,
        )


def run_capability_command(
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run one parsed capability author command."""

    command = args.capability_command
    if command == "init":
        target = _new_target(args.target)
        _copy_template(target)
        payload = open_portable_payload(target / "payload")
        _write_json(stdout, _payload_identity(payload))
        return 0
    if command == "validate":
        payload = open_portable_payload(Path(args.payload))
        _write_json(stdout, _payload_identity(payload))
        return 0
    if command == "inspect":
        payload = open_portable_payload(Path(args.payload))
        manifest = payload.manifest
        _write_json(
            stdout,
            {
                **_payload_identity(payload),
                "capabilities": [
                    capability.selector
                    for capability in manifest.capabilities
                ],
                "benchmark_suites": [
                    suite.selector for suite in manifest.benchmark_suites
                ],
                "resources": [
                    {
                        "resource_id": resource.resource_id,
                        "sha256": resource.sha256,
                    }
                    for resource in manifest.resources
                ],
            },
        )
        return 0
    if command == "test":
        root = Path(args.source).absolute()
        payload = open_portable_payload(root / "payload")
        declaration = CapabilitySourceDeclaration(
            source_id=_LOCAL_SOURCE_ID,
            kind="local-directory",
            package_ref=payload.manifest.package_ref,
            payload_sha256=payload.payload_sha256,
            locator={"root": str(root)},
            provider_factory={
                "module": _LOCAL_FACTORY_MODULE,
                "name": _LOCAL_FACTORY_NAME,
            },
        )
        source = LocalDirectoryCapabilityPackageSource(declaration)
        candidate = source.discover_metadata()[0]
        installed = source.load_provider(candidate)
        run_capability_conformance(installed)
        _write_json(
            stdout,
            {
                **_payload_identity(payload),
                "source_kind": installed.source_kind,
            },
        )
        return 0
    if command in {"pack", "convert"}:
        stderr.write(
            f"asterion: capability {command} is {_STAGED_BOUNDARY}\n"
        )
        return 2
    raise ValueError("capability command is invalid")


def _new_target(value: str) -> Path:
    requested = Path(value)
    parent = requested.parent.resolve(strict=True)
    target = parent / requested.name
    if (
        not requested.name
        or requested.name in {".", ".."}
        or target.exists()
        or target.is_symlink()
    ):
        raise ValueError("capability template target is invalid")
    return target


def _copy_template(target: Path) -> None:
    template = files(_TEMPLATE_PACKAGE)
    with tempfile.TemporaryDirectory(
        prefix=".asterion-capability-init-",
        dir=target.parent,
    ) as temporary:
        staged = Path(temporary) / "source"
        staged.mkdir()
        _copy_resources(template, staged)
        staged.replace(target)


def _copy_resources(source: Traversable, target: Path) -> None:
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        if child.name == "__pycache__":
            continue
        destination = target / child.name
        if child.is_dir():
            destination.mkdir()
            _copy_resources(child, destination)
        elif child.is_file():
            with (
                child.open("rb") as input_stream,
                destination.open("xb") as output_stream,
            ):
                shutil.copyfileobj(input_stream, output_stream)
        else:
            raise ValueError("capability template is invalid")


def _payload_identity(
    payload: PortableCapabilityPayload,
) -> dict[str, str]:
    manifest = payload.manifest
    return {
        "package_id": manifest.package_ref.package_id,
        "payload_sha256": payload.payload_sha256,
        "version": manifest.package_ref.version,
    }


def _write_json(stdout: TextIO, value: object) -> None:
    stdout.write(json.dumps(value, sort_keys=True) + "\n")


def _exact_package_selector(value: str) -> str:
    package_id, separator, version = value.partition("@")
    if (
        not separator
        or "@" in version
        or IDENTIFIER.fullmatch(package_id) is None
        or SEMANTIC_VERSION.fullmatch(version) is None
    ):
        raise argparse.ArgumentTypeError(
            "target must be an exact PACKAGE@VERSION selector"
        )
    return value
