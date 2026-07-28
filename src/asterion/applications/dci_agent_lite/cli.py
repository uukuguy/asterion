"""Thin DCI application CLI adapter over the generic Asterion hosts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from asterion.cli import main as asterion_main

from asterion.applications.dci_agent_lite.operator_config import (
    create_capability_package_source,
    load_operator_inputs,
    preflight_host_services,
    render_preflight,
)


APPLICATION_PROVIDER_ID = "dci-agent-lite"
DEFAULT_APPLICATION = "dci.complete-application@1.0.0"
SUITE_ALIASES = {
    "all": "dci.all@1.0.0",
    "github": "dci.github@1.0.0",
    "paper-main": "dci.paper-main@1.0.0",
}


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Translate DCI defaults and delegate to public generic hosts."""

    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr
    try:
        args = _parser().parse_args(argv)
        if args.command == "list":
            return asterion_main(
                ["list", "--provider", APPLICATION_PROVIDER_ID],
                stdout=output_stream,
                stderr=error_stream,
            )
        if args.command == "describe":
            forwarded = ["describe", "--provider", APPLICATION_PROVIDER_ID]
            if args.json:
                forwarded.append("--json")
            return asterion_main(
                forwarded,
                stdout=output_stream,
                stderr=error_stream,
            )
        if args.command == "preflight":
            inputs = load_operator_inputs(
                operator_root=Path.cwd(),
                env_file=args.env_file,
                dataset_roots=_roots(args.dataset_root),
                corpus_roots=_roots(args.corpus_root),
                amount=args.amount,
            )
            output_stream.write(render_preflight(preflight_host_services(inputs)))
            return 0
        if args.command == "benchmark":
            return _benchmark(args, stdout=output_stream, stderr=error_stream)
    except (OSError, TypeError, ValueError):
        error_stream.write("asterion-dci: command failed\n")
        return 2
    error_stream.write("asterion-dci: command failed\n")
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asterion-dci")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    describe = commands.add_parser("describe")
    describe.add_argument("--json", action="store_true")
    preflight = commands.add_parser("preflight")
    _add_private_operator_arguments(preflight)

    benchmark = commands.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(
        dest="benchmark_command",
        required=True,
    )
    for name in ("plan", "run", "resume"):
        command = benchmark_commands.add_parser(name)
        command.add_argument(
            "--application",
            default=DEFAULT_APPLICATION,
            help="exact DCI application selector",
        )
        command.add_argument(
            "--suite",
            default="github",
            help="DCI suite alias or exact suite selector",
        )
        command.add_argument("--case-limit", type=int)
        command.add_argument("--capability-source-lock", action="append", default=[])
        command.add_argument("--evidence-root")
        _add_private_operator_arguments(command)
        if name in {"run", "resume"}:
            command.add_argument("--execute", action="store_true")
        if name == "resume":
            command.add_argument("--run-id", required=True)
    return parser


def _add_private_operator_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--dataset-root", action="append", default=[])
    parser.add_argument("--corpus-root", action="append", default=[])
    parser.add_argument("--amount")


def _benchmark(
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    forwarded = [
        "benchmark",
        args.benchmark_command,
        "--application",
        args.application,
        "--suite",
        _suite(args.suite),
    ]
    if args.case_limit is not None:
        forwarded.extend(("--case-limit", str(args.case_limit)))
    for lock in args.capability_source_lock:
        forwarded.extend(("--capability-source-lock", lock))
    if args.evidence_root is not None:
        forwarded.extend(("--evidence-root", args.evidence_root))
    if args.benchmark_command in {"run", "resume"} and args.execute:
        forwarded.append("--execute")
    if args.benchmark_command == "resume":
        forwarded.extend(("--run-id", args.run_id))

    inputs = load_operator_inputs(
        operator_root=Path.cwd(),
        env_file=args.env_file,
        dataset_roots=_roots(args.dataset_root),
        corpus_roots=_roots(args.corpus_root),
        amount=args.amount,
    )
    return asterion_main(
        forwarded,
        capability_package_sources=(
            create_capability_package_source(inputs),
        ),
        stdout=stdout,
        stderr=stderr,
    )


def _suite(value: str) -> str:
    if value in SUITE_ALIASES:
        return SUITE_ALIASES[value]
    return value


def _roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for item in values:
        name, separator, raw_path = item.partition("=")
        if not separator:
            raise ValueError("DCI operator root is invalid")
        roots[name] = Path(raw_path)
    return roots


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
