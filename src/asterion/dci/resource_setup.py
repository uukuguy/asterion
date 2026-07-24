"""Provider-free setup and validation of external Asterion DCI resources."""

from __future__ import annotations

import os
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath

from asterion.dci.export import export_bcplus


class ResourceSetupError(RuntimeError):
    """A body-free resource setup failure."""


@dataclass(frozen=True)
class ResourceSpec:
    resource_id: str
    source_repo: str
    source_path: str
    destination: str
    conversion: str


@dataclass(frozen=True)
class ResourceSetupResult:
    profile: str
    status: str
    prepared: tuple[str, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()


BASIC_RESOURCES = (
    ResourceSpec(
        resource_id="corpus.bc-plus",
        source_repo="DCI-Agent/corpus",
        source_path="browsecomp_plus",
        destination="corpus/bc_plus_docs",
        conversion="bcplus",
    ),
    ResourceSpec(
        resource_id="corpus.wiki",
        source_repo="DCI-Agent/corpus",
        source_path="wiki",
        destination="corpus/wiki_corpus",
        conversion="copy",
    ),
)


def _benchmark_source(destination: str) -> tuple[str, str, str]:
    if destination.startswith("data/dci-bench/"):
        return (
            "DCI-Agent/dci-bench",
            destination.removeprefix("data/dci-bench/"),
            "copy",
        )
    if destination == "data/bcplus_qa.jsonl":
        return ("DCI-Agent/corpus", "browsecomp_plus", "manual")
    if destination.startswith("corpus/bright_corpus/"):
        subset = destination.rsplit("/", 1)[-1]
        source_subset = {
            "biology": "bright_biology",
            "earth_science": "bright_earth_science",
            "economics": "bright_economics",
            "robotics": "bright_robotics",
        }[subset]
        return ("DCI-Agent/corpus", source_subset, "manual")
    if destination.startswith("corpus/beir/") or destination.startswith(
        "paper-full/"
    ):
        return ("manual/external", destination, "manual")
    basic = {spec.destination: spec for spec in BASIC_RESOURCES}.get(destination)
    if basic is not None:
        return (basic.source_repo, basic.source_path, basic.conversion)
    return ("manual/external", destination, "manual")


def _benchmark_resources() -> tuple[ResourceSpec, ...]:
    raw = resources.files("asterion.dci").joinpath(
        "resources/paper-benchmarks.json"
    )
    inventory = json.loads(raw.read_text(encoding="utf-8"))
    destinations = {
        row[field]
        for row in inventory["datasets"]
        for field in ("dataset_path", "corpus_path")
    }
    project_root = Path(__file__).resolve().parents[3]
    launcher_root = project_root / "scripts"
    if launcher_root.is_dir():
        destinations.update(
            match
            for launcher in launcher_root.rglob("*.sh")
            for match in re.findall(
                r'\$RESOURCE_ROOT/([^";]+)',
                launcher.read_text(encoding="utf-8"),
            )
        )
    specs = []
    for destination in sorted(destinations):
        source_repo, source_path, conversion = _benchmark_source(destination)
        category = (
            "dataset"
            if destination.startswith(("data/", "paper-full/"))
            else "corpus"
        )
        specs.append(
            ResourceSpec(
                resource_id=f"{category}.{destination}",
                source_repo=source_repo,
                source_path=source_path,
                destination=destination,
                conversion=conversion,
            )
        )
    return tuple(specs)


def resource_specs(profile: str) -> tuple[ResourceSpec, ...]:
    """Return the immutable resource requirements for one profile."""

    if profile == "basic":
        return BASIC_RESOURCES
    if profile == "benchmark":
        return _benchmark_resources()
    raise ResourceSetupError(f"unknown resource profile: {profile}")


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _reject_symlink(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ResourceSetupError(f"{label} must not be a symlink")


def _destination(root: Path, relative: str) -> Path:
    logical = PurePosixPath(relative)
    if logical.is_absolute() or ".." in logical.parts or not logical.parts:
        raise ResourceSetupError("resource destination is unsafe")
    destination = root.joinpath(*logical.parts)
    current = root
    for part in logical.parts:
        current = current / part
        _reject_symlink(current, label="resource destination")
    try:
        destination.relative_to(root)
    except ValueError as error:  # pragma: no cover - guarded by PurePosixPath
        raise ResourceSetupError("resource destination escapes resource root") from error
    return destination


def _complete_path(path: Path) -> bool:
    if path.is_symlink():
        return False
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        found_file = False
        for item in path.rglob("*"):
            if item.is_symlink():
                return False
            if item.is_file():
                found_file = True
        return found_file
    return False


def _reject_source_tree_symlinks(path: Path) -> None:
    if path.is_symlink() or (
        path.is_dir() and any(item.is_symlink() for item in path.rglob("*"))
    ):
        raise ResourceSetupError("resource source must not contain a symlink")


def _local_source(source_root: Path, spec: ResourceSpec) -> Path:
    _reject_symlink(source_root, label="resource source root")
    mirrored = source_root.joinpath(*PurePosixPath(spec.destination).parts)
    if not mirrored.is_symlink() and (mirrored.is_file() or mirrored.is_dir()):
        _reject_source_tree_symlinks(mirrored)
        return mirrored
    source = source_root.joinpath(*PurePosixPath(spec.source_path).parts)
    if source.is_symlink() or not (source.is_file() or source.is_dir()):
        raise ResourceSetupError(
            f"{spec.resource_id} source {spec.source_path} is unavailable"
        )
    _reject_source_tree_symlinks(source)
    return source


def _network_source(spec: ResourceSpec, staging_root: Path) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise ResourceSetupError(
            "resource download support is missing; run uv sync --extra setup"
        ) from error
    try:
        snapshot_download(
            repo_id=spec.source_repo,
            repo_type="dataset",
            local_dir=staging_root,
            allow_patterns=[spec.source_path, f"{spec.source_path}/**"],
        )
    except Exception as error:
        raise ResourceSetupError(
            f"{spec.resource_id} could not be fetched from {spec.source_repo}; "
            "authenticate with Hugging Face and retry"
        ) from error
    source = staging_root.joinpath(*PurePosixPath(spec.source_path).parts)
    if not (source.is_file() or source.is_dir()):
        raise ResourceSetupError(
            f"{spec.resource_id} path {spec.source_path} is absent from "
            f"{spec.source_repo}"
        )
    _reject_source_tree_symlinks(source)
    return source


def _materialize(spec: ResourceSpec, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=".asterion-resource-",
            dir=destination.parent,
        )
    )
    try:
        staged = staging_root
        if source.is_file():
            staged = staging_root / destination.name
            shutil.copy2(source, staged)
        elif spec.conversion == "copy":
            shutil.copytree(source, staging_root, dirs_exist_ok=True)
        elif spec.conversion == "bcplus":
            export_bcplus(source, staging_root)
        else:
            raise ResourceSetupError(
                f"{spec.resource_id} requires manual/external preparation at "
                f"{spec.destination}"
            )
        if not _complete_path(staged):
            raise ResourceSetupError(
                f"{spec.resource_id} produced no files for {spec.destination}"
            )
        if destination.exists():
            raise ResourceSetupError(
                f"{spec.resource_id} destination {spec.destination} is incomplete; "
                "move it aside and retry"
            )
        os.replace(staged, destination)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _diagnostic(spec: ResourceSpec) -> str:
    action = (
        "provide this manual/external resource"
        if spec.source_repo == "manual/external" or spec.conversion == "manual"
        else "authenticate with Hugging Face and run setup-resources-benchmark"
    )
    return (
        f"{spec.resource_id}: missing {spec.destination}; "
        f"source {spec.source_repo}; {action}"
    )


def prepare_resources(
    *,
    profile: str,
    resource_root: Path,
    source_root: Path | None = None,
    check_only: bool = False,
) -> ResourceSetupResult:
    """Prepare or check one external resource profile."""

    specs = resource_specs(profile)
    root = _absolute_without_resolving(resource_root)
    _reject_symlink(root, label="resource root")
    destinations = tuple(
        (spec, _destination(root, spec.destination)) for spec in specs
    )
    present = tuple(
        spec.resource_id
        for spec, destination in destinations
        if _complete_path(destination)
    )
    missing_specs = tuple(
        (spec, destination)
        for spec, destination in destinations
        if spec.resource_id not in present
    )
    if check_only:
        missing = tuple(spec.resource_id for spec, _ in missing_specs)
        return ResourceSetupResult(
            profile=profile,
            status="PASS" if not missing else "FAIL",
            prepared=(),
            present=present,
            missing=missing,
            diagnostics=tuple(_diagnostic(spec) for spec, _ in missing_specs),
        )

    prepared: list[str] = []
    unresolved: list[ResourceSpec] = []
    local_root = (
        None if source_root is None else _absolute_without_resolving(source_root)
    )
    for spec, destination in missing_specs:
        if local_root is None and (
            spec.source_repo == "manual/external" or spec.conversion == "manual"
        ):
            unresolved.append(spec)
            continue
        try:
            with tempfile.TemporaryDirectory(
                prefix=".asterion-resource-download-"
            ) as temporary:
                source = (
                    _local_source(local_root, spec)
                    if local_root is not None
                    else _network_source(spec, Path(temporary))
                )
                _materialize(spec, source, destination)
            prepared.append(spec.resource_id)
        except ResourceSetupError:
            if profile == "basic":
                raise
            unresolved.append(spec)
    return ResourceSetupResult(
        profile=profile,
        status="PASS" if not unresolved else "FAIL",
        prepared=tuple(prepared),
        present=present,
        missing=tuple(spec.resource_id for spec in unresolved),
        diagnostics=tuple(_diagnostic(spec) for spec in unresolved),
    )
