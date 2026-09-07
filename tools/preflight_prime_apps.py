"""Prepare and provider-free preflight every public Prime development preset."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol, TextIO

from asterion.applications.discovery import load_application_provider
from asterion.applications.prime_agent.operator.development_preparation import (
    PrimeDevelopmentPreparationError,
    prepare_prime_development,
)
from asterion.applications.provider import InstalledApplication, InstalledApplicationProvider
from asterion.assembly.protocol import AssemblyError, validate_assembly_manifest
from asterion.services.progress import TextHostProgressReporter
from asterion.services.registry import HostServiceFactoryRegistry


_ROWS = (
    ("prime-p1", "p1", "prime.ipython-coding", "prime.ipython-production"),
    ("prime-p2", "p2", "prime.programmatic-long-context", "prime.programmatic-long-context-development"),
    ("prime-p3", "p3", "prime.recursive-workflow", "prime.recursive-workflow-development"),
    ("prime-p4", "p4", "prime.long-session-continuity", "prime.long-session-continuity-development"),
    ("prime-p5", "p5", "prime.bounded-autonomy", "prime.bounded-autonomy-development"),
    ("prime-p6", "p6", "prime.continual-improvement", "prime.continual-improvement-development"),
    ("prime-p7", "p7", "prime.arc-agi-3", "prime.arc-agi-3-development"),
    ("prime-p7-solve", "p7-solving", "prime.arc-agi-3-solving", "prime.arc-agi-3-solving"),
)
_VERSION = "1.0.0"
_RUNTIME_ID = "prime.agent"


class _Preparation(Protocol):
    def __call__(
        self, repo_root: Path, scenarios: tuple[str, ...]
    ) -> Mapping[str, object]: ...


class _ProviderLoader(Protocol):
    def __call__(self, provider_id: str) -> InstalledApplicationProvider: ...


def preflight_prime_apps(
    repo_root: Path,
    *,
    stdout: TextIO,
    stderr: TextIO,
    prepare: _Preparation = prepare_prime_development,
    load_provider: _ProviderLoader = load_application_provider,
    registry: HostServiceFactoryRegistry | None = None,
) -> int:
    """Prepare then open/close the seven exact host contexts without execution."""

    prepared = _prepare_rows(repo_root, prepare)
    prepared = _publish_union_receipt(repo_root, prepared, prepare)
    try:
        provider = load_provider("prime-agent")
    except Exception:
        provider = None
    effective_registry = HostServiceFactoryRegistry() if registry is None else registry
    results = asyncio.run(
        _open_prepared_rows(
            provider,
            prepared,
            effective_registry,
            TextHostProgressReporter(stderr),
        )
    )
    for display_name, passed in results:
        stdout.write(f"{display_name} {'PASS' if passed else 'FAIL'}\n")
    return 0 if all(passed for _, passed in results) else 1


def _prepare_rows(repo_root: Path, prepare: _Preparation) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for _, scenario, _, _ in _ROWS:
        try:
            prepare(repo_root, (scenario,))
        except (PrimeDevelopmentPreparationError, OSError, TypeError, ValueError):
            results[scenario] = False
        except Exception:
            results[scenario] = False
        else:
            results[scenario] = True
    return results


def _publish_union_receipt(
    repo_root: Path, prepared: dict[str, bool], prepare: _Preparation
) -> dict[str, bool]:
    """Publish one receipt covering every successful per-scenario preparation."""

    successful = tuple(
        scenario for _, scenario, _, _ in _ROWS if prepared.get(scenario, False)
    )
    if not successful:
        return prepared
    try:
        prepare(repo_root, successful)
    except Exception:
        for scenario in successful:
            prepared[scenario] = False
    return prepared


async def _open_prepared_rows(
    provider: InstalledApplicationProvider | None,
    prepared: Mapping[str, bool],
    registry: HostServiceFactoryRegistry,
    progress: TextHostProgressReporter,
) -> tuple[tuple[str, bool], ...]:
    results: list[tuple[str, bool]] = []
    for display_name, scenario, application_id, capability_id in _ROWS:
        passed = prepared.get(scenario, False) and await _open_one(
            provider, application_id, capability_id, registry, progress
        )
        results.append((display_name, passed))
    return tuple(results)


async def _open_one(
    provider: InstalledApplicationProvider | None,
    application_id: str,
    capability_id: str,
    registry: HostServiceFactoryRegistry,
    progress: TextHostProgressReporter,
) -> bool:
    try:
        application = _exact_application(provider, application_id)
        _exact_assembly(application, capability_id)
        async with registry.open(
            provider_id="prime-agent",
            application_id=application.application_id,
            application_version=application.version,
            capability_ids=(capability_id,),
            options={},
            progress=progress,
        ):
            pass
    except Exception:
        return False
    return True


def _exact_application(
    provider: InstalledApplicationProvider | None, application_id: str
) -> InstalledApplication:
    if (
        not isinstance(provider, InstalledApplicationProvider)
        or provider.provider_id != "prime-agent"
    ):
        raise ValueError("provider is invalid")
    matches = tuple(
        item
        for item in provider.applications
        if item.application_id == application_id and item.version == _VERSION
    )
    if len(matches) != 1:
        raise ValueError("application is invalid")
    return matches[0]


def _exact_assembly(application: InstalledApplication, capability_id: str) -> None:
    if len(application.assembly_paths) != 1 or application.runtime_ids != (_RUNTIME_ID,):
        raise ValueError("application assembly is invalid")
    try:
        raw = json.loads(application.assembly_paths[0].read_text(encoding="utf-8"))
        assembly = validate_assembly_manifest(raw)
    except (AssemblyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("application assembly is invalid") from None
    if (
        assembly["application_id"] != application.application_id
        or assembly["version"] != application.version
        or assembly["runtime_id"] != _RUNTIME_ID
        or assembly["host_capabilities"] != (capability_id,)
    ):
        raise ValueError("application assembly is invalid")


def main(argv: Iterable[str] | None = None) -> int:
    del argv
    return preflight_prime_apps(
        Path(__file__).resolve().parents[1], stdout=sys.stdout, stderr=sys.stderr
    )


if __name__ == "__main__":
    raise SystemExit(main())
