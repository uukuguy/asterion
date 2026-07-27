"""Transitional explicit-local installed provider for the DCI package."""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

from asterion.capabilities.dci_research.complete import complete_dci_bindings
from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.protocol import CapabilityPackageRef


PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SOURCE_ID = "local-directory:dci@1.0.0"


def create_provider() -> InstalledCapabilityPackage:
    """Return the installed DCI package for an explicitly injected local source."""

    root = (
        Path(str(resources.files("asterion"))).resolve() / "capabilities/dci_research"
    )
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=_content_sha256(root),
        source_id=SOURCE_ID,
        source_kind="local-directory",
        catalog_roots=((root / "manifests").resolve(strict=True),),
        benchmark_suite_paths=(),
        implementations=complete_dci_bindings(),
        benchmark_bindings=(),
    )


def _content_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    paths = (
        root / "capability-package.json",
        *sorted((root / "manifests").glob("*.json")),
    )
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
