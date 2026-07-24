"""Generic command line for explicitly selected installed applications."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Callable, TextIO

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
)
from asterion.applications.provider import ApplicationProviderError, InstalledApplication
from asterion.applications.product import (
    CapabilityProductDescription,
    VerificationRequest,
    VerificationResult,
    validate_verification_result,
)
from asterion.applications.selection import (
    parse_application_selector,
    select_installed_application,
)
from asterion.assembly.protocol import AssemblyError, resolve_assembly
from asterion.dci.config import resolve_dci_runtime_options
from asterion.packages.catalog import discover_packages
from asterion.packages.execution import (
    PackageExecutionError,
    validate_implementation_bindings,
)
from asterion.runner.application import ApplicationRunError
from asterion.runner.composed import run_composed_application
from asterion.dci.config import ConfigLayers, resolve_asterion_runtime
from asterion.runtime.factory import (
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeFactoryRegistry,
)
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.services.managed_controlled_executor import (
    ManagedControlledExecutor,
    OperatorExecutorConfig,
    load_operator_executor_config,
)


def main(
    argv: list[str] | None = None,
    *,
    entry_points: Iterable[object] | None = None,
    runtime_factories: RuntimeFactoryRegistry | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    managed_executor_factory: Callable[[OperatorExecutorConfig], object] | None = None,
) -> int:
    """Run the generic installed-application CLI."""

    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    registry = (
        default_runtime_factory_registry()
        if runtime_factories is None
        else runtime_factories
    )
    executor_factory = (
        ManagedControlledExecutor
        if managed_executor_factory is None
        else managed_executor_factory
    )
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "list":
            if args.provider is not None:
                provider = load_application_provider(
                    args.provider, entry_points=entry_points
                )
                payload = {
                    "provider_id": provider.provider_id,
                    "applications": [
                        {
                            "application_id": application.application_id,
                            "version": application.version,
                            "selector": (
                                f"{application.application_id}@{application.version}"
                            ),
                            "runtime_ids": list(application.runtime_ids),
                        }
                        for application in sorted(
                            provider.applications,
                            key=lambda item: (item.application_id, item.version),
                        )
                    ],
                }
                stdout.write(json.dumps(payload, sort_keys=True) + "\n")
                return 0
            payload = [
                {
                    "provider_id": item.provider_id,
                    "distribution_name": item.distribution_name,
                    "distribution_version": item.distribution_version,
                }
                for item in list_application_providers(entry_points=entry_points)
            ]
            stdout.write(json.dumps(payload, sort_keys=True) + "\n")
            return 0
        if args.command == "describe":
            provider = load_application_provider(
                args.provider, entry_points=entry_points
            )
            if provider.product is None:
                raise ApplicationProviderError("capability description is unavailable")
            if args.json:
                stdout.write(
                    json.dumps(
                        _description_payload(provider.product.description),
                        sort_keys=True,
                    )
                    + "\n"
                )
            else:
                _render_description(provider.product.description, stdout)
            return 0
        if args.command == "verify":
            provider = load_application_provider(
                args.provider, entry_points=entry_points
            )
            if provider.product is None:
                raise ApplicationProviderError("capability verification is unavailable")
            description = provider.product.description
            if args.level not in {profile.level for profile in description.profiles}:
                raise ApplicationProviderError("verification level is invalid")
            request = VerificationRequest(
                level=args.level,
                env_file=_optional_absolute_path(args.env_file),
                corpus_root=_optional_absolute_path(args.corpus_root),
                output_root=_optional_absolute_path(args.output_root),
                acceptance_root=_optional_absolute_path(args.acceptance_root),
            )
            result = validate_verification_result(
                provider.product.verifier(request), description
            )
            if args.json:
                stdout.write(json.dumps(_verification_payload(result), sort_keys=True) + "\n")
            else:
                _render_verification(result, stdout)
            return 0 if result.status == "PASS" else 1
        if sum(
            value is not None
            for value in (args.application, args.assembly, args.legacy_assembly)
        ) != 1:
            raise ApplicationProviderError("application selection mode is invalid")
        return asyncio.run(
            _run(
                args,
                entry_points=entry_points,
                registry=registry,
                managed_executor_factory=executor_factory,
                stdin=stdin,
                stdout=stdout,
            )
        )
    except (
        ApplicationProviderError,
        ApplicationRunError,
        AssemblyError,
        PackageExecutionError,
        RuntimeFactoryError,
        OSError,
        TypeError,
        ValueError,
    ):
        stderr.write("asterion: command failed\n")
        return 2


async def _run(
    args: argparse.Namespace,
    *,
    entry_points: Iterable[object] | None,
    registry: RuntimeFactoryRegistry,
    managed_executor_factory: Callable[[OperatorExecutorConfig], object],
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    provider = load_application_provider(
        args.provider, entry_points=entry_points
    )
    runtime = resolve_dci_runtime_options(
        {"runtime": _public_runtime_from_cli(args.runtime)}
    )
    runtime_id = _runtime_id_from_runtime(runtime.runtime)
    if args.application is not None:
        application = select_installed_application(
            provider, parse_application_selector(args.application)
        )
    else:
        requested = Path(args.assembly or args.legacy_assembly)
        if requested.is_symlink():
            raise ApplicationProviderError("application assembly is unsafe")
        assembly_path = requested.resolve(strict=True)
        matches = [
            candidate
            for candidate in provider.applications
            if assembly_path in candidate.assembly_paths
        ]
        if len(matches) != 1:
            raise ApplicationProviderError("application assembly selection is invalid")
        application = matches[0]
    layers = ConfigLayers.from_repo(Path.cwd())
    resolved_runtime = resolve_asterion_runtime(
        {"runtime": args.runtime} if args.runtime is not None else {},
        layers,
    )
    layers.materialize(os.environ)
    runtime_id = resolve_public_runtime_id(resolved_runtime.runtime)
    if runtime_id not in application.runtime_ids:
        raise ApplicationProviderError("application runtime selection is invalid")
    if args.application is not None:
        assembly_path = _select_application_assembly(application, runtime_id)
    runtime_binding = registry.select(runtime_id)
    assembly = json.loads(assembly_path.read_text())
    plan = resolve_assembly(
        assembly,
        catalog=discover_packages(application.catalog_roots),
        runtime_manifest=runtime_binding.manifest.to_mapping(),
    )
    validate_implementation_bindings(plan, application.implementations)
    operator_config = _operator_executor_config(args, plan.host_capabilities)
    context = RuntimeFactoryContext(
        provider_id=provider.provider_id,
        application_id=application.application_id,
        application_version=application.version,
        runtime_id=runtime_id,
        assembly_path=assembly_path,
        options={
            "provider": resolved_runtime.provider,
            "model": resolved_runtime.model,
            "tools": resolved_runtime.tools,
            "thinking_level": resolved_runtime.thinking_level,
            "context_profile": resolved_runtime.context_profile,
            "timeout_seconds": resolved_runtime.timeout_seconds,
            "authentication_mode": resolved_runtime.authentication_mode,
        },
    )
    runtime = runtime_binding.factory(context)
    input_text = args.input if args.input is not None else stdin.read()
    if operator_config is None:
        result = await run_composed_application(
            plan,
            implementations=application.implementations,
            runtime=runtime,
            run_id=args.run_id,
            input_text=input_text,
            host_services={},
        )
    else:
        async with managed_executor_factory(operator_config) as executor:
            result = await run_composed_application(
                plan,
                implementations=application.implementations,
                runtime=runtime,
                run_id=args.run_id,
                input_text=input_text,
                host_services={"executor.controlled": executor},
            )
    stdout.write(json.dumps(_thaw(result.__dict__), sort_keys=True) + "\n")
    return 0


def _public_runtime_from_cli(selection: str | None) -> str:
    """Normalize CLI runtime selection into config-runtime keys."""

    if selection is None:
        return resolve_dci_runtime_options().runtime
    normalized = _normalize_runtime_name(selection)
    if normalized is None:
        raise ValueError("application runtime selection is invalid")
    return normalized


def _runtime_id_from_runtime(runtime: str) -> str:
    if runtime == "pi":
        return "pi.reference"
    if runtime == "claude-code":
        return "claude-code.reference"
    raise ValueError("application runtime selection is invalid")


def _normalize_runtime_name(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"", "pi", "pi.reference", "pi-ref", "pi_reference"}:
        return "pi"
    if normalized in {
        "claude-code",
        "claude-code.reference",
        "claude_code",
        "claudecode",
    }:
        return "claude-code"
    return None


def _select_application_assembly(
    application: InstalledApplication, runtime_id: str
) -> Path:
    """Return the application's unique canonical assembly for one runtime."""

    matches = []
    for path in application.assembly_paths:
        try:
            assembly = json.loads(path.read_text())
        except (OSError, TypeError, ValueError):
            raise ApplicationProviderError("application assembly selection is invalid") from None
        if isinstance(assembly, dict) and assembly.get("runtime_id") == runtime_id:
            matches.append(path)
    if len(matches) != 1:
        raise ApplicationProviderError("application assembly selection is invalid")
    return matches[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asterion")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_command = subparsers.add_parser("list")
    list_command.add_argument("--provider")
    describe = subparsers.add_parser(
        "describe", help="show one provider's capability product"
    )
    describe.add_argument("--provider", required=True)
    describe.add_argument("--json", action="store_true")
    verify = subparsers.add_parser(
        "verify", help="verify one provider's capability product"
    )
    verify.add_argument("--provider", required=True)
    verify.add_argument("--level", required=True)
    verify.add_argument("--env-file")
    verify.add_argument("--corpus-root")
    verify.add_argument("--output-root")
    verify.add_argument("--acceptance-root")
    verify.add_argument("--json", action="store_true")
    run = subparsers.add_parser("run")
    run.add_argument("--provider", required=True)
    run.add_argument("--runtime")
    run.add_argument("--run-id", default="asterion-run")
    run.add_argument("--input")
    run.add_argument("--application")
    run.add_argument("--assembly")
    run.add_argument("--executor-binary", default=os.environ.get("ASTERION_EXECUTOR_BINARY"))
    run.add_argument("--executor-policy", default=os.environ.get("ASTERION_EXECUTOR_POLICY"))
    run.add_argument(
        "--executor-validation-config",
        default=os.environ.get("ASTERION_EXECUTOR_VALIDATION_CONFIG"),
    )
    run.add_argument("legacy_assembly", nargs="?")
    return parser


def resolve_public_runtime_id(value: str) -> str:
    """Map a public runtime name to an exact installed runtime identity."""

    try:
        return {
            "pi": "pi.reference",
            "claude-code": "claude-code.reference",
            "pi.reference": "pi.reference",
            "claude-code.reference": "claude-code.reference",
        }[value]
    except KeyError:
        raise ValueError("application runtime selection is invalid") from None


def _description_payload(description: CapabilityProductDescription) -> dict[str, object]:
    return {
        "product_id": description.product_id,
        "version": description.version,
        "summary": description.summary,
        "functions": [
            {
                "function_id": function.function_id,
                "summary": function.summary,
                "argv": list(function.argv),
            }
            for function in description.functions
        ],
        "configuration": [
            {
                "name": requirement.name,
                "purpose": requirement.purpose,
                "required_for": list(requirement.required_for),
                "secret": requirement.secret,
                "default": None if requirement.secret else requirement.default,
                "hint": requirement.hint,
            }
            for requirement in description.configuration
        ],
        "profiles": [
            {
                "level": profile.level,
                "summary": profile.summary,
                "cost_class": profile.cost_class,
                "provider_backed_operation_count": profile.provider_backed_operation_count,
                "full_dataset": profile.full_dataset,
            }
            for profile in description.profiles
        ],
    }


def _verification_payload(result: VerificationResult) -> dict[str, object]:
    return {
        "product_id": result.product_id,
        "level": result.level,
        "status": result.status,
        "checks": [
            {
                "check_id": check.check_id,
                "summary": check.summary,
                "status": check.status,
                "artifact_refs": list(check.artifact_refs),
                "counts": dict(check.counts),
            }
            for check in result.checks
        ],
        "provider_backed_operation_count": result.provider_backed_operation_count,
        "full_dataset_ran": result.full_dataset_ran,
    }


def _render_description(
    description: CapabilityProductDescription, stdout: TextIO
) -> None:
    stdout.write(f"{description.product_id} {description.version}\n")
    stdout.write(f"{description.summary}\n\nFunctions:\n")
    for function in description.functions:
        stdout.write(f"  {function.function_id}: {function.summary}\n")
        stdout.write(f"    command: {' '.join(function.argv)}\n")
    stdout.write("\nConfiguration:\n")
    for requirement in description.configuration:
        suffix = " (secret)" if requirement.secret else ""
        stdout.write(f"  {requirement.name}{suffix}: {requirement.purpose}\n")
        stdout.write(f"    {requirement.hint}\n")
    stdout.write("\nVerification levels:\n")
    for profile in description.profiles:
        stdout.write(f"  {profile.level}: {profile.summary}\n")
        stdout.write(
            f"    provider-backed operations: {profile.provider_backed_operation_count}; "
            f"full dataset: {'yes' if profile.full_dataset else 'no'}\n"
        )


def _render_verification(result: VerificationResult, stdout: TextIO) -> None:
    stdout.write(f"{result.product_id} verification: {result.level}\n")
    for check in result.checks:
        stdout.write(f"[{check.status}] {check.check_id}: {check.summary}\n")
        if check.counts:
            stdout.write(
                "  counts: "
                + ", ".join(f"{key}={value}" for key, value in check.counts)
                + "\n"
            )
        if check.artifact_refs:
            stdout.write("  artifacts: " + ", ".join(check.artifact_refs) + "\n")
    stdout.write(f"Overall: {result.status}\n")
    stdout.write(
        f"Provider-backed operations: {result.provider_backed_operation_count}\n"
    )
    stdout.write(f"Full dataset ran: {'yes' if result.full_dataset_ran else 'no'}\n")


def _optional_absolute_path(value: str | None) -> Path | None:
    return None if value is None else Path(value).expanduser().resolve()


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_thaw(item) for item in value]
    return value


def _operator_executor_config(
    args: argparse.Namespace, host_capabilities: tuple[str, ...]
) -> OperatorExecutorConfig | None:
    values = (
        args.executor_binary,
        args.executor_policy,
        args.executor_validation_config,
    )
    requires_executor = "executor.controlled" in host_capabilities
    if requires_executor:
        if not all(values):
            raise ApplicationProviderError("controlled executor configuration is required")
        return load_operator_executor_config(*values)
    if any(values):
        raise ApplicationProviderError("controlled executor configuration is invalid")
    return None
