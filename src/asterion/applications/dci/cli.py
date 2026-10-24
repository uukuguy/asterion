"""Thin DCI application adapter over Asterion's public host commands."""

from __future__ import annotations

import sys
import json
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import TextIO

from asterion.benchmarks.cli import BenchmarkCommandHost, InstalledBenchmarkCommandHost
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)
from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.applications.dci.operator_config import (
    DciOperatorConfig,
    load_operator_config,
)
from asterion.applications.dci.benchmark_instances import (
    DciBenchmarkInstance,
    DciBenchmarkInstanceError,
    benchmark_instances,
    public_instance_dict,
    resolve_case_limit,
    select_benchmark_instance,
)
from asterion.applications.dci.benchmark_source_lock import (
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)


DCI_BENCHMARK_SUITE_SELECTOR = "dci.all@1.0.0"
_PRODUCT_LEVELS = frozenset({"acceptance", "basic", "complete", "preflight"})
_PRODUCT_PATH_OPTIONS = (
    "--acceptance-root",
    "--corpus-root",
    "--env-file",
    "--output-root",
)
_ApplicationMain = Callable[..., int]
_BenchmarkMain = Callable[..., int]
_BenchmarkHostFactory = Callable[[DciOperatorConfig], BenchmarkCommandHost]
_ExperimentHostFactory = Callable[..., BenchmarkCommandHost]


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    application_main: _ApplicationMain | None = None,
    benchmark_main: _BenchmarkMain | None = None,
    benchmark_host: BenchmarkCommandHost | None = None,
    benchmark_host_factory: _BenchmarkHostFactory | None = None,
    repo_root: Path | None = None,
    env_file: Path | None = None,
    environment: Mapping[str, str] | None = None,
    amount: Decimal | None = None,
    benchmark_package_sources: Sequence[CapabilityPackageSource] | None = None,
    experiment_host_factory: _ExperimentHostFactory | None = None,
) -> int:
    """Apply exact DCI defaults and delegate to generic Asterion hosts."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    assert stdin is not None
    assert stdout is not None
    assert stderr is not None
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "pathlight":
        from asterion.applications.dci.pathlight_cli import main as pathlight_main

        return pathlight_main(
            arguments[1:],
            stdout=stdout,
            stderr=stderr,
            repo_root=repo_root,
            env_file=env_file,
            environment=environment,
            package_sources=benchmark_package_sources,
            experiment_host_factory=experiment_host_factory,
        )

    del application_main
    from asterion.benchmarks.cli import main as default_benchmark_main

    benchmark_host_main = (
        default_benchmark_main if benchmark_main is None else benchmark_main
    )
    if not arguments or arguments == ["--help"]:
        stdout.write(
            "usage: asterion-dci "
            "{describe,preflight,basic,complete,acceptance,benchmark}\n"
        )
        return 0
    command, *remainder = arguments
    if command == "benchmark":
        benchmark_amount = amount
        if remainder and remainder[0] == "instances":
            return _list_benchmark_instances(
                remainder[1:],
                stdout=stdout,
                stderr=stderr,
            )
        if remainder and remainder[0] == "lock":
            return _create_benchmark_source_lock(
                remainder,
                package_sources=benchmark_package_sources,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            budget_value, remainder = _take_option(remainder, "--max-cost-usd")
            native_attempts_value, remainder = _take_option(
                remainder,
                "--max-native-attempts",
            )
            benchmark_amount = amount if budget_value is None else Decimal(budget_value)
            if benchmark_amount is not None and (
                type(benchmark_amount) is not Decimal
                or not benchmark_amount.is_finite()
                or benchmark_amount <= 0
            ):
                raise ValueError
            max_native_attempts = (
                None
                if native_attempts_value is None
                else int(native_attempts_value, 10)
            )
            if max_native_attempts not in {None, 1}:
                raise ValueError
            instance, delegated_arguments = _benchmark_selection(remainder)
            if (
                max_native_attempts is not None
                and not _execution_host_ready(delegated_arguments)
            ):
                raise ValueError
        except (DciBenchmarkInstanceError, DecimalException, ValueError):
            stderr.write("asterion-dci: command failed\n")
            return 2
        selected_benchmark_host = benchmark_host
        if selected_benchmark_host is None and delegated_arguments[:1] == ["plan"]:
            try:
                selected_benchmark_host = InstalledBenchmarkCommandHost(
                    package_sources=_benchmark_package_sources(
                        benchmark_package_sources
                    ),
                )
            except Exception:
                stderr.write("asterion-dci: command failed\n")
                return 2
        elif selected_benchmark_host is None and _execution_host_ready(
            delegated_arguments
        ):
            try:
                if benchmark_host_factory is not None:
                    selected_benchmark_host = benchmark_host_factory(
                        load_operator_config(
                            Path.cwd() if repo_root is None else repo_root,
                            env_file=env_file,
                            environment=environment,
                            amount=benchmark_amount,
                            max_native_attempts=max_native_attempts,
                        )
                    )
                else:
                    from asterion.applications.dci.benchmark_host import (
                        DciBenchmarkHost,
                    )

                    config = (
                        None
                        if instance.executor_profile == "local-fixture"
                        else load_operator_config(
                            Path.cwd() if repo_root is None else repo_root,
                            env_file=env_file,
                            environment=environment,
                            amount=benchmark_amount,
                            max_native_attempts=max_native_attempts,
                        )
                    )
                    selected_benchmark_host = DciBenchmarkHost(
                        instance=instance,
                        operator_config=config,
                        package_sources=benchmark_package_sources,
                    )
            except Exception:
                stderr.write("asterion-dci: command failed\n")
                return 2
        return benchmark_host_main(
            [
                *delegated_arguments[:1],
                "--application",
                instance.application_ref.selector,
                "--suite",
                f"{instance.suite_ref.suite_id}@{instance.suite_ref.version}",
                *delegated_arguments[1:],
            ],
            host=selected_benchmark_host,
            stdout=stdout,
            stderr=stderr,
        )
    if command == "describe":
        return _describe_product(
            remainder, stdout=stdout, stderr=stderr, repo_root=repo_root
        )
    if command in _PRODUCT_LEVELS:
        return _verify_product(
            command, remainder, stdout=stdout, stderr=stderr, repo_root=repo_root
        )
    stderr.write("asterion-dci: command failed\n")
    return 2


def _describe_product(
    remainder: list[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    repo_root: Path | None,
) -> int:
    if tuple(remainder) not in {(), ("--json",)}:
        stderr.write("asterion-dci: command failed\n")
        return 2
    from asterion.cli import _description_payload, _render_description

    try:
        description = _dci_product(repo_root).description
    except Exception:
        stderr.write("asterion-dci: command failed\n")
        return 2
    if remainder == ["--json"]:
        stdout.write(
            json.dumps(_description_payload(description), sort_keys=True) + "\n"
        )
    else:
        _render_description(description, stdout)
    return 0


def _verify_product(
    level: str,
    remainder: list[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    repo_root: Path | None,
) -> int:
    parsed = _product_options(remainder)
    if parsed is None:
        stderr.write("asterion-dci: command failed\n")
        return 2
    json_output, options = parsed
    from asterion.applications.product import (
        VerificationRequest,
        validate_verification_result,
    )
    from asterion.cli import (
        _optional_absolute_path,
        _render_verification,
        _verification_payload,
    )

    try:
        product = _dci_product(repo_root)
        if level not in {profile.level for profile in product.description.profiles}:
            raise ValueError
        result = validate_verification_result(
            product.verifier(
                VerificationRequest(
                    level=level,
                    env_file=_optional_absolute_path(options["--env-file"]),
                    corpus_root=_optional_absolute_path(options["--corpus-root"]),
                    output_root=_optional_absolute_path(options["--output-root"]),
                    acceptance_root=_optional_absolute_path(
                        options["--acceptance-root"]
                    ),
                )
            ),
            product.description,
        )
    except Exception:
        stderr.write("asterion-dci: command failed\n")
        return 2
    if json_output:
        stdout.write(json.dumps(_verification_payload(result), sort_keys=True) + "\n")
    else:
        _render_verification(result, stdout)
    return 0 if result.status == "PASS" else 1


def _dci_product(repo_root: Path | None):
    from asterion.applications.dci.acceptance import installed_acceptance_checks
    from asterion.capabilities.dci.implementation.reproduction.verification import (
        create_dci_product,
    )

    return create_dci_product(
        repo_root=Path.cwd() if repo_root is None else repo_root,
        acceptance_checks=installed_acceptance_checks,
    )


def _product_options(
    arguments: list[str],
) -> tuple[bool, dict[str, str | None]] | None:
    json_output = False
    values = {option: None for option in _PRODUCT_PATH_OPTIONS}
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == "--json":
            if json_output:
                return None
            json_output = True
            index += 1
            continue
        option = item.split("=", 1)[0]
        if option not in values:
            return None
        if item.startswith(option + "="):
            raw = item.removeprefix(option + "=")
            index += 1
        else:
            if index + 1 >= len(arguments):
                return None
            raw = arguments[index + 1]
            index += 2
        if not raw or raw.startswith("--") or values[option] is not None:
            return None
        values[option] = raw
    return json_output, values


def _has_option(arguments: Sequence[str], option: str) -> bool:
    return any(value == option or value.startswith(option + "=") for value in arguments)


def _list_benchmark_instances(
    arguments: Sequence[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if tuple(arguments) not in {(), ("--json",)}:
        stderr.write("asterion-dci: command failed\n")
        return 2
    values = tuple(public_instance_dict(instance) for instance in benchmark_instances())
    if arguments:
        stdout.write(
            json.dumps(
                values,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    else:
        for value in values:
            stdout.write(
                f"{value['instance']}\t{value['implementation_state']}\t"
                f"{value['cost_class']}\n"
            )
    return 0


def _benchmark_package_sources(
    values: Sequence[CapabilityPackageSource] | None,
) -> tuple[CapabilityPackageSource, ...]:
    if values is not None:
        return tuple(values)
    return (
        BuiltinCapabilitySource(builtin_capability_registrations()),
        DistributionCapabilityPackageSource(),
    )


def _create_benchmark_source_lock(
    arguments: Sequence[str],
    *,
    package_sources: Sequence[CapabilityPackageSource] | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        selector, values = _take_option(list(arguments), "--instance")
        output_value, values = _take_option(values, "--output")
        if (
            selector is None
            or output_value is None
            or values != ["lock"]
            or "\x00" in output_value
        ):
            raise DciBenchmarkInstanceError("DCI benchmark lock is invalid")
        instance = select_benchmark_instance(selector)
        if instance.implementation_state != "implemented":
            raise DciBenchmarkInstanceError("DCI benchmark instance is unavailable")
        lock = resolve_benchmark_source_lock(
            instance,
            package_sources=package_sources,
        )
        write_benchmark_source_lock(lock, Path(output_value).expanduser())
        stdout.write(
            json.dumps(
                {"instance": instance.selector, "locked": True},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0
    except Exception:
        stderr.write("asterion-dci: command failed\n")
        return 2


def _benchmark_selection(
    arguments: Sequence[str],
) -> tuple[DciBenchmarkInstance, list[str]]:
    values = list(arguments)
    if (
        not values
        or values[0] not in {"plan", "run", "resume"}
        or _has_option(values, "--application")
        or _has_option(values, "--suite")
    ):
        raise DciBenchmarkInstanceError("DCI benchmark command is invalid")
    selector, values = _take_option(values, "--instance")
    if selector is None:
        raise DciBenchmarkInstanceError("DCI benchmark instance is required")
    instance = select_benchmark_instance(selector)
    if instance.implementation_state != "implemented":
        raise DciBenchmarkInstanceError("DCI benchmark instance is unavailable")
    case_limit_value, values = _take_option(values, "--case-limit")
    all_cases = values.count("--all-cases")
    if all_cases > 1:
        raise DciBenchmarkInstanceError("DCI benchmark case range is invalid")
    values = [value for value in values if value != "--all-cases"]
    try:
        case_limit = (
            None if case_limit_value is None else int(case_limit_value, 10)
        )
    except ValueError:
        raise DciBenchmarkInstanceError(
            "DCI benchmark case range is invalid"
        ) from None
    resolved_limit = resolve_case_limit(
        instance,
        case_limit=case_limit,
        all_cases=all_cases == 1,
    )
    return instance, [values[0], "--case-limit", str(resolved_limit), *values[1:]]


def _take_option(
    arguments: list[str],
    option: str,
) -> tuple[str | None, list[str]]:
    matches = [
        index
        for index, value in enumerate(arguments)
        if value == option or value.startswith(option + "=")
    ]
    if len(matches) > 1:
        raise DciBenchmarkInstanceError("DCI benchmark arguments are invalid")
    if not matches:
        return None, arguments
    index = matches[0]
    value = arguments[index]
    if value.startswith(option + "="):
        selected = value.removeprefix(option + "=")
        remainder = [*arguments[:index], *arguments[index + 1 :]]
    else:
        if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
            raise DciBenchmarkInstanceError("DCI benchmark arguments are invalid")
        selected = arguments[index + 1]
        remainder = [*arguments[:index], *arguments[index + 2 :]]
    if not selected:
        raise DciBenchmarkInstanceError("DCI benchmark arguments are invalid")
    return selected, remainder


def _execution_host_ready(arguments: Sequence[str]) -> bool:
    if not arguments or arguments[0] not in {"run", "resume"}:
        return False
    if not _has_option(arguments, "--execute"):
        return False
    required = ("--capability-source-lock", "--evidence-root")
    if arguments[0] == "resume":
        required = (*required, "--run-id")
    return all(_has_option_value(arguments, option) for option in required)


def _has_option_value(arguments: Sequence[str], option: str) -> bool:
    for index, value in enumerate(arguments):
        if value.startswith(option + "="):
            return bool(value.removeprefix(option + "="))
        if value == option:
            return (
                index + 1 < len(arguments)
                and bool(arguments[index + 1])
                and not arguments[index + 1].startswith("--")
            )
    return False


__all__ = (
    "DCI_BENCHMARK_SUITE_SELECTOR",
    "main",
)
