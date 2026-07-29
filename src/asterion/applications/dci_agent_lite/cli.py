"""Thin DCI application adapter over Asterion's public host commands."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from asterion.benchmarks.cli import BenchmarkCommandHost
from asterion.applications.dci_agent_lite.operator_config import (
    DciOperatorConfig,
    load_operator_config,
)


DCI_PROVIDER_ID = "dci-agent-lite"
DCI_APPLICATION_SELECTOR = "dci.complete-application@1.0.0"
DCI_BENCHMARK_SUITE_SELECTOR = "dci.all@1.0.0"
_RUNTIME_ALIASES = {
    "claude-code": "claude-code.reference",
    "claude-code.reference": "claude-code.reference",
    "pi": "pi.reference",
    "pi.reference": "pi.reference",
}
_ApplicationMain = Callable[..., int]
_BenchmarkMain = Callable[..., int]
_BenchmarkHostFactory = Callable[[DciOperatorConfig], BenchmarkCommandHost]


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
) -> int:
    """Apply exact DCI defaults and delegate to generic Asterion hosts."""

    from asterion.benchmarks.cli import main as default_benchmark_main
    from asterion.cli import main as default_application_main

    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    assert stdin is not None
    assert stdout is not None
    assert stderr is not None
    application_host = (
        default_application_main
        if application_main is None
        else application_main
    )
    benchmark_host_main = (
        default_benchmark_main if benchmark_main is None else benchmark_main
    )
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments == ["--help"]:
        stdout.write(
            "usage: asterion-dci "
            "{list,describe,preflight,basic,complete,run,benchmark}\n"
        )
        return 0
    command, *remainder = arguments
    if command == "benchmark":
        if _has_option(remainder, "--application") or _has_option(
            remainder, "--suite"
        ):
            stderr.write("asterion-dci: command failed\n")
            return 2
        selected_benchmark_host = benchmark_host
        if (
            selected_benchmark_host is None
            and benchmark_host_factory is not None
            and _execution_host_ready(remainder)
        ):
            try:
                selected_benchmark_host = benchmark_host_factory(
                    load_operator_config(
                        Path.cwd() if repo_root is None else repo_root,
                        env_file=env_file,
                        environment=environment,
                        amount=amount,
                    )
                )
            except Exception:
                stderr.write("asterion-dci: command failed\n")
                return 2
        return benchmark_host_main(
            [
                *remainder[:1],
                "--application",
                DCI_APPLICATION_SELECTOR,
                "--suite",
                DCI_BENCHMARK_SUITE_SELECTOR,
                *remainder[1:],
            ],
            host=selected_benchmark_host,
            stdout=stdout,
            stderr=stderr,
        )
    if command == "list":
        delegated = ["list", "--provider", DCI_PROVIDER_ID, *remainder]
    elif command == "describe":
        delegated = ["describe", "--provider", DCI_PROVIDER_ID, *remainder]
    elif command in {"preflight", "basic", "complete"}:
        delegated = [
            "verify",
            "--provider",
            DCI_PROVIDER_ID,
            "--level",
            command,
            *remainder,
        ]
    elif command == "run":
        runtime, forwarded = _runtime(remainder)
        if runtime is None:
            stderr.write("asterion-dci: command failed\n")
            return 2
        delegated = [
            "run",
            "--provider",
            DCI_PROVIDER_ID,
            "--application",
            DCI_APPLICATION_SELECTOR,
            "--runtime",
            runtime,
            *forwarded,
        ]
    else:
        stderr.write("asterion-dci: command failed\n")
        return 2
    return application_host(
        delegated,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


def _runtime(arguments: list[str]) -> tuple[str | None, list[str]]:
    try:
        index = arguments.index("--runtime")
        value = arguments[index + 1]
    except (ValueError, IndexError):
        return None, arguments
    if arguments.count("--runtime") != 1:
        return None, arguments
    runtime = _RUNTIME_ALIASES.get(value)
    if runtime is None:
        return None, arguments
    return runtime, [*arguments[:index], *arguments[index + 2 :]]


def _has_option(arguments: Sequence[str], option: str) -> bool:
    return any(value == option or value.startswith(option + "=") for value in arguments)


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
    "DCI_APPLICATION_SELECTOR",
    "DCI_BENCHMARK_SUITE_SELECTOR",
    "DCI_PROVIDER_ID",
    "main",
)
