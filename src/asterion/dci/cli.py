"""Package-local command line for the independent Asterion DCI product."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import secrets
import stat
import sys
from dataclasses import replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import TextIO

from asterion.dci.ablation import (
    bounded_ablation_input_paths,
    bounded_ablation_resolution_registry_path,
    paper_ablation_matrix_sha256,
    paper_ablation_row_ids,
    render_paper_ablation_command,
    require_af320_executable_ablation,
    resolve_paper_ablation_row,
    validate_paper_ablation_matrix,
)
from asterion.dci.config import (
    DciRuntimeOptions,
    load_asterion_dci_env,
    resolve_dci_paths,
    resolve_dci_runtime_options,
)
from asterion.dci.context_profiles import context_profile_names
from asterion.dci.benchmark import BenchmarkRequest, DciBenchmarkError, run_benchmark
from asterion.dci.artifacts import DciConversationFeatures
from asterion.dci.evaluation import DciEvaluationError, evaluate_run_directory
from asterion.dci.export import (
    BRIGHT_SUBSETS,
    DciExportError,
    export_bcplus,
    export_bcplus_qa,
    export_bright,
    export_resolution_summary,
)
from asterion.dci.judge import (
    DEFAULT_JUDGE_API,
    DEFAULT_JUDGE_BASE_URL,
    DEFAULT_JUDGE_MODEL,
    JudgeConfig,
)
from asterion.dci.pi_rpc import run_pi_terminal, validate_terminal_cwd
from asterion.dci.run import (
    DciRunError,
    DciRunResult,
    request_from_runtime_options,
    resume_request_from_output_dir,
    run_pi_research,
    validate_dci_run_request,
)
from asterion.dci.system_prompt import render_pi_system_prompt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asterion-dci")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("question", nargs="*")
    run.add_argument("--question-file", type=Path)
    run.add_argument("--cwd", type=Path, default=Path("."))
    _add_runtime_option_arguments(run)
    run.add_argument("--max-turns", type=int)
    run.add_argument("--show-tools", action="store_true")
    run.add_argument("--system-prompt-file", type=Path)
    run.add_argument("--append-system-prompt-file", type=Path)
    run.add_argument("--output-dir", type=Path)
    run.add_argument("--run-id")
    run.add_argument("--conversation-clear-tool-results", action="store_true")
    run.add_argument("--conversation-clear-tool-results-keep-last", type=int, default=3)
    run.add_argument("--conversation-externalize-tool-results", action="store_true")
    run.add_argument("--conversation-strip-thinking", action="store_true")
    run.add_argument("--conversation-strip-usage", action="store_true")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--eval-answer")
    run.add_argument("--eval-answer-file", type=Path)
    terminal = commands.add_parser("terminal")
    terminal.add_argument("question", nargs="*")
    terminal.add_argument("--question-file", type=Path)
    terminal.add_argument("--cwd", type=Path, default=Path("."))
    terminal.add_argument("--provider")
    terminal.add_argument("--model")
    terminal.add_argument("--tools")
    terminal.add_argument("--thinking-level")
    terminal.add_argument("--node-max-old-space-size-mb", type=int)
    terminal.add_argument("--extra-arg", action="append")
    terminal.add_argument("--system-prompt-file", type=Path)
    terminal.add_argument("--append-system-prompt-file", type=Path)
    resume = commands.add_parser("resume")
    resume.add_argument("--output-dir", type=Path, required=True)
    prompt = commands.add_parser("system-prompt")
    prompt.add_argument("--cwd", type=Path, default=Path("."))
    prompt.add_argument("--tools")
    prompt.add_argument("--append-system-prompt-file", type=Path)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--output-dir", type=Path, required=True)
    evaluate.add_argument("--gold-answer", required=True)
    evaluate.add_argument("--answer")
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--dataset", type=Path)
    benchmark.add_argument("--output-root", type=Path)
    benchmark.add_argument("--cwd", type=Path)
    _add_runtime_option_arguments(benchmark)
    benchmark.add_argument("--limit", type=int)
    benchmark.add_argument("--mode", choices=("qa", "ir"))
    benchmark.add_argument("--enable-ir", action="store_true")
    benchmark.add_argument("--profile")
    benchmark.add_argument("--ablation-row")
    benchmark.add_argument("--corpus", "--corpus-dir", dest="corpus", type=Path)
    benchmark.add_argument("--corpus-hint")
    benchmark.add_argument("--resolution-registry", type=Path)
    benchmark.add_argument("--resolution-segment-characters", type=int)
    benchmark.add_argument("--max-concurrency", type=int)
    benchmark.add_argument("--max-turns", type=int)
    benchmark.add_argument(
        "--resume-policy", choices=("compatible", "fresh", "reuse")
    )
    benchmark.add_argument("--no-analysis", action="store_true")
    benchmark.add_argument("--no-figures", action="store_true")
    benchmark.add_argument("--system-prompt-file", type=Path)
    benchmark.add_argument("--append-system-prompt-file", type=Path)
    benchmark.add_argument("--conversation-clear-tool-results", action="store_true")
    benchmark.add_argument(
        "--conversation-clear-tool-results-keep-last", type=int, default=3
    )
    benchmark.add_argument(
        "--conversation-externalize-tool-results", action="store_true"
    )
    benchmark.add_argument("--conversation-strip-thinking", action="store_true")
    benchmark.add_argument("--conversation-strip-usage", action="store_true")
    _add_judge_arguments(benchmark)
    benchmark.add_argument("--package-dir", type=Path)
    benchmark.add_argument("--agent-dir", type=Path)
    export = commands.add_parser("export")
    exporters = export.add_subparsers(dest="export_kind", required=True)
    bcplus = exporters.add_parser("bcplus")
    bcplus.add_argument("--source-dir", type=Path, required=True)
    bcplus.add_argument("--output-dir", type=Path, required=True)
    bright = exporters.add_parser("bright")
    bright.add_argument("--source-root", type=Path, required=True)
    bright.add_argument("--output-root", type=Path, required=True)
    bright.add_argument("--subset", action="append", choices=BRIGHT_SUBSETS)
    qa = exporters.add_parser("bcplus-qa")
    qa.add_argument("--parquet-dir", type=Path, required=True)
    qa.add_argument("--output", type=Path, required=True)
    qa.add_argument("--no-decrypt", action="store_true")
    resolution = exporters.add_parser("resolution")
    resolution.add_argument("--run-dir", type=Path, required=True)
    resolution.add_argument("--attempt", type=int, required=True)
    resolution.add_argument("--corpus-dir", type=Path, required=True)
    resolution.add_argument("--gold-manifest", type=Path, required=True)
    resolution.add_argument("--segment-characters", type=int, required=True)
    ablation = commands.add_parser("ablation")
    ablation_commands = ablation.add_subparsers(
        dest="ablation_command", required=True
    )
    ablation_commands.add_parser("validate")
    ablation_list = ablation_commands.add_parser("list")
    ablation_list.add_argument(
        "--execution-class", choices=("paper-full", "bounded-fixture")
    )
    ablation_render = ablation_commands.add_parser("render")
    ablation_render.add_argument("row_id")
    paper = commands.add_parser("paper")
    paper_commands = paper.add_subparsers(dest="paper_command", required=True)
    paper_commands.add_parser("describe")
    paper_verify = paper_commands.add_parser("verify")
    paper_verify.add_argument("--provider-backed", action="store_true")
    paper_verify.add_argument("--env-file", type=Path)
    paper_verify.add_argument("--output-root", type=Path)
    paper_reproduce = paper_commands.add_parser("reproduce")
    paper_reproduce.add_argument("--profile", required=True)
    paper_reproduce.add_argument("--output-root", type=Path, required=True)
    paper_reproduce.add_argument("--estimated-budget-usd", type=float, required=True)
    paper_reproduce.add_argument("--authorize-full", action="store_true")
    paper_reproduce.add_argument("--dry-run", action="store_true")
    paper_reproduce.add_argument("--provider")
    paper_reproduce.add_argument("--model")
    paper_compare = paper_commands.add_parser("compare")
    paper_compare.add_argument("--baseline", type=Path)
    paper_compare.add_argument("--candidate", type=Path, required=True)
    paper_compare.add_argument("--profile", required=True)
    paper_compare.add_argument("--output", type=Path, required=True)
    paper_compare.add_argument("--provider")
    paper_compare.add_argument("--model")
    return parser


def _add_runtime_option_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared DCI settings with None defaults for environment resolution."""

    parser.add_argument("--runtime")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--tools")
    parser.add_argument("--rpc-timeout-seconds", type=float)
    parser.add_argument("--runtime-context-level", choices=context_profile_names())
    parser.add_argument("--thinking-level", "--pi-thinking-level", dest="thinking_level")
    parser.add_argument("--node-max-old-space-size-mb", type=int)
    parser.add_argument("--keep-session", action="store_true", default=None)
    parser.add_argument("--extra-arg", "--pi-extra-arg", dest="extra_arg", action="append")


def _add_judge_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--judge-base-url",
        help=f"Override DCI_EVAL_JUDGE_BASE_URL (default: {DEFAULT_JUDGE_BASE_URL}).",
    )
    parser.add_argument(
        "--judge-api",
        choices=("responses", "chat-completions"),
        help=f"Override DCI_EVAL_JUDGE_API (default: {DEFAULT_JUDGE_API}).",
    )
    parser.add_argument(
        "--judge-model",
        help=f"Override DCI_EVAL_JUDGE_MODEL (default: {DEFAULT_JUDGE_MODEL}).",
    )
    parser.add_argument("--judge-api-key-env")
    parser.add_argument("--judge-timeout-seconds", type=int)
    parser.add_argument("--judge-max-output-tokens", type=int)
    parser.add_argument(
        "--judge-json-mode",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--judge-strict-json-schema",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--judge-responses-store",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--judge-thinking", choices=("auto", "enabled", "disabled", "omit")
    )
    parser.add_argument("--judge-input-price-per-1m", type=float)
    parser.add_argument("--judge-cached-input-price-per-1m", type=float)
    parser.add_argument("--judge-output-price-per-1m", type=float)


def main(
    argv: list[str] | None = None,
    *,
    repo_root: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run an Asterion DCI command without changing generic CLI ownership."""

    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    if effective_argv == ["--help"]:
        parser.print_help(file=stdout)
        return 0
    try:
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            args = parser.parse_args(effective_argv)
    except SystemExit as error:
        if error.code == 0:
            return 0
        _write_command_failure(stderr, _requested_command(effective_argv))
        return 2
    selected_ablation = None
    if args.command == "benchmark" and args.ablation_row is not None:
        try:
            conflict_fields = (
                "dataset",
                "cwd",
                "profile",
                "corpus",
                "mode",
                "limit",
                "max_turns",
                "runtime_context_level",
                "tools",
                "resolution_registry",
                "resolution_segment_characters",
                "system_prompt_file",
                "append_system_prompt_file",
                "corpus_hint",
                "thinking_level",
            )
            if (
                args.enable_ir
                or args.extra_arg
                or args.conversation_clear_tool_results
                or args.conversation_strip_thinking
                or args.conversation_strip_usage
                or any(
                getattr(args, field) is not None for field in conflict_fields
                )
            ):
                raise ValueError("ablation controls conflict")
            selected_ablation = require_af320_executable_ablation(
                args.ablation_row, benchmark_authorized=True
            )
        except (RuntimeError, ValueError):
            stderr.write("DCI benchmark failed\n")
            return 2
    if args.command == "ablation":
        try:
            if args.ablation_command == "validate":
                payload: dict[str, object] = {
                    "schema": "dci.paper-ablation-validation/v1",
                    "rows": validate_paper_ablation_matrix(),
                    "matrix_sha256": paper_ablation_matrix_sha256(),
                }
            elif args.ablation_command == "list":
                rows = tuple(
                    resolve_paper_ablation_row(row_id)
                    for row_id in paper_ablation_row_ids()
                )
                if args.execution_class is not None:
                    rows = tuple(
                        row
                        for row in rows
                        if row.execution_class == args.execution_class
                    )
                payload = {
                    "schema": "dci.paper-ablation-list/v1",
                    "matrix_sha256": paper_ablation_matrix_sha256(),
                    "rows": [row.to_mapping() for row in rows],
                }
            else:
                stdout.write(render_paper_ablation_command(args.row_id) + "\n")
                return 0
            stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            return 0
        except (RuntimeError, ValueError):
            stderr.write("DCI ablation command failed\n")
            return 2
    if args.command == "paper":
        try:
            from asterion.dci.verification import (
                paper_benchmark_acceptance_main,
                paper_product_contract,
            )

            if args.paper_command == "describe":
                stdout.write(
                    json.dumps(
                        paper_product_contract(), ensure_ascii=False, indent=2
                    )
                    + "\n"
                )
                return 0
            if args.paper_command == "compare":
                from asterion.dci.experiment_profiles import resolve_experiment_profile
                from asterion.dci.reproduction import (
                    compare_reproduction_runs,
                    load_run_manifest,
                    write_comparison_report,
                )

                profile = resolve_experiment_profile(
                    args.profile,
                    invocation_provider=args.provider,
                    invocation_model=args.model,
                )
                baseline = (
                    None
                    if args.baseline is None
                    else load_run_manifest(args.baseline)
                )
                candidate = load_run_manifest(args.candidate)
                report = compare_reproduction_runs(baseline, candidate, profile)
                write_comparison_report(args.output, report)
                stdout.write(f"Comparison report: {report.identity_sha256}\n")
                stdout.write(
                    "Acceptance: "
                    + (
                        "not-applicable\n"
                        if report.accepted is None
                        else ("pass\n" if report.accepted else "fail\n")
                    )
                )
                return 0 if report.accepted is not False else 3
            if args.paper_command == "reproduce":
                from asterion.dci.experiment_profiles import (
                    authorize_full_execution,
                    experiment_profile_sha256,
                    resolve_experiment_profile,
                )
                from asterion.dci.paper_benchmarks import (
                    paper_benchmark_ids,
                    resolve_paper_benchmark,
                    resolve_paper_experiment_scope,
                )

                profile = resolve_experiment_profile(
                    args.profile,
                    invocation_provider=args.provider,
                    invocation_model=args.model,
                )
                profile_sha256 = experiment_profile_sha256(
                    args.profile,
                    invocation_provider=args.provider,
                    invocation_model=args.model,
                )
                if (
                    not math.isfinite(args.estimated_budget_usd)
                    or args.estimated_budget_usd < 0
                ):
                    raise ValueError("DCI full execution budget is invalid")
                if args.authorize_full and (
                    args.output_root.exists() or args.output_root.is_symlink()
                ):
                    raise ValueError("DCI full output root must be fresh")
                selected_count = sum(
                    resolve_paper_experiment_scope(scope_id).selection_count
                    for scope_id in profile.scope_ids
                )
                judge_count = sum(
                    resolve_paper_experiment_scope(scope_id).selection_count
                    for scope_id in profile.scope_ids
                    if resolve_paper_benchmark(
                        resolve_paper_experiment_scope(scope_id).dataset_id
                    ).mode == "qa"
                )
                stdout.write(f"Profile: {profile.profile_id}\n")
                stdout.write(f"Profile SHA-256: {profile_sha256}\n")
                stdout.write(f"Dataset inventory SHA-256: {profile.dataset_inventory_sha256}\n")
                stdout.write(f"Experiment scopes SHA-256: {profile.experiment_scopes_sha256}\n")
                stdout.write(f"Datasets: {len(paper_benchmark_ids())}\n")
                stdout.write(f"Experiment scopes: {len(profile.scope_ids)}\n")
                stdout.write(f"Selected queries: {selected_count}\n")
                stdout.write(f"Maximum agent operations: {selected_count}\n")
                stdout.write(f"Maximum Judge operations: {judge_count}\n")
                stdout.write(f"Estimated budget USD: {args.estimated_budget_usd:g}\n")
                stdout.write("Agent operations performed: 0\nJudge operations performed: 0\n")
                stdout.write(
                    "Full authorization requested: "
                    + ("yes\n" if args.authorize_full else "no\n")
                )
                if args.dry_run:
                    stdout.write("Full authorization issued: no\n")
                    stdout.write("reproduction_authorized=no\n")
                    stdout.write("operation_count=0\n")
                    return 0
                if not args.authorize_full:
                    stdout.write("Full authorization issued: no\n")
                    stdout.write("reproduction_authorized=no\n")
                    stdout.write("operation_count=0\n")
                    return 2
                authorize_full_execution(
                    args.profile,
                    args.output_root,
                    args.estimated_budget_usd,
                    args.authorize_full,
                    preflight_profile_sha256=profile_sha256,
                    preflight_dataset_inventory_sha256=profile.dataset_inventory_sha256,
                    preflight_experiment_scopes_sha256=profile.experiment_scopes_sha256,
                    invocation_provider=args.provider,
                    invocation_model=args.model,
                    preflight_scope_ids=profile.scope_ids,
                    preflight_selected_ids_sha256=profile.selected_ids_sha256,
                )
                stdout.write("Full authorization issued: yes\n")
                stdout.write("Execution delegated: no\n")
                stdout.write("reproduction_authorized=yes\n")
                stdout.write("operation_count=0\n")
                return 0
            verify_argv = []
            if args.provider_backed:
                verify_argv.append("--provider-backed")
            if args.env_file is not None:
                verify_argv.extend(("--env-file", str(args.env_file)))
            if args.output_root is not None:
                verify_argv.extend(("--output-root", str(args.output_root)))
            root = Path.cwd().resolve() if repo_root is None else Path(repo_root).resolve()
            return paper_benchmark_acceptance_main(
                verify_argv,
                stdout=stdout,
                stderr=stderr,
            )
        except (RuntimeError, ValueError):
            stderr.write("DCI paper command failed\n")
            return 2
    try:
        invocation_cwd = Path.cwd().resolve()
        root = invocation_cwd if repo_root is None else Path(repo_root).resolve()
        load_asterion_dci_env(root)
        paths = resolve_dci_paths(root)
    except (OSError, ValueError):
        _write_command_failure(stderr, args.command)
        return 2
    if args.command == "export":
        try:
            if args.export_kind == "bcplus":
                total = export_bcplus(
                    _path_from_invocation(args.source_dir, invocation_cwd),
                    _output_path_from_invocation(args.output_dir, invocation_cwd),
                )
            elif args.export_kind == "bright":
                total = export_bright(
                    _path_from_invocation(args.source_root, invocation_cwd),
                    _output_path_from_invocation(args.output_root, invocation_cwd),
                    args.subset,
                )
            elif args.export_kind == "bcplus-qa":
                total = export_bcplus_qa(
                    _path_from_invocation(args.parquet_dir, invocation_cwd),
                    _output_path_from_invocation(args.output, invocation_cwd),
                    decrypt=not args.no_decrypt,
                )
            else:
                if args.attempt < 1 or args.segment_characters < 1:
                    raise ValueError("resolution export configuration is invalid")
                projection = export_resolution_summary(
                    run_dir=args.run_dir,
                    attempt=args.attempt,
                    corpus_dir=args.corpus_dir,
                    gold_manifest_path=args.gold_manifest,
                    segment_characters=args.segment_characters,
                )
                stdout.write(
                    json.dumps(projection, ensure_ascii=False, indent=2) + "\n"
                )
                return 0
        except (DciExportError, OSError, RuntimeError, ValueError):
            stderr.write("DCI export failed\n")
            return 2
        stdout.write(f"exported={total}\n")
        return 0
    if args.command == "evaluate":
        try:
            result = evaluate_run_directory(
                args.output_dir,
                gold_answer=args.gold_answer,
                predicted_answer=args.answer,
                judge_config=JudgeConfig.from_env(),
            )
        except (DciEvaluationError, OSError, ValueError):
            stderr.write("DCI evaluation failed\n")
            return 2
        stdout.write(f"output_dir={args.output_dir}\n")
        stdout.write(f"is_correct={result['is_correct']}\n")
        stdout.write("evaluation_uri=eval_result.json\n")
        return 0
    if args.command == "benchmark":
        try:
            if selected_ablation is not None:
                dataset, corpus = bounded_ablation_input_paths(
                    selected_ablation.row_id
                )
                args.dataset = dataset
                args.corpus = corpus
                args.cwd = corpus
                args.mode = "qa"
                args.tools = ",".join(selected_ablation.tools)
                args.runtime_context_level = selected_ablation.context_profile
                args.max_turns = selected_ablation.max_turns
                args.conversation_externalize_tool_results = True
                args.resolution_registry = (
                    bounded_ablation_resolution_registry_path()
                )
                args.resolution_segment_characters = (
                    selected_ablation.segment_characters
                )
            _apply_benchmark_profile(
                args, repo_root=root, invocation_cwd=invocation_cwd
            )
            if args.package_dir is not None or args.agent_dir is not None:
                raise ValueError("runner-owned Pi paths are not CLI controls")
            if args.limit is not None and args.limit < 1:
                raise ValueError("benchmark limit is invalid")
            if args.max_concurrency < 1:
                raise ValueError("benchmark concurrency is invalid")
            runtime_options = _runtime_options(args)
            runtime_preflight = replace(
                request_from_runtime_options(
                    runtime_options,
                    run_id="asterion-dci-benchmark-preflight",
                    question="Asterion DCI benchmark preflight",
                    cwd=args.cwd,
                    stream_text=False,
                ),
                max_turns=args.max_turns,
            )
            validate_dci_run_request(runtime_preflight)
            benchmark_output_root = args.output_root
            if _path_has_symlink(benchmark_output_root):
                raise ValueError("benchmark destination is unsafe")
            benchmark_system_prompt = _resolve_resource(
                args.system_prompt_file,
                invocation_cwd=invocation_cwd,
                repo_root=root,
            )
            benchmark_append_prompt = _resolve_resource(
                args.append_system_prompt_file,
                invocation_cwd=invocation_cwd,
                repo_root=root,
            )
            benchmark_resolution_registry = _resolve_resource(
                args.resolution_registry,
                invocation_cwd=invocation_cwd,
                repo_root=root,
            )
            result = run_benchmark(
                BenchmarkRequest(
                    dataset=args.dataset,
                    output_root=benchmark_output_root,
                    cwd=args.cwd,
                    judge_config=_judge_config(args),
                    runtime_options=runtime_options,
                    limit=args.limit,
                    mode=args.mode,
                    profile=args.profile,
                    corpus=args.corpus,
                    corpus_hint=args.corpus_hint,
                    max_concurrency=args.max_concurrency,
                    max_turns=args.max_turns,
                    resume_policy=args.resume_policy,
                    analysis=not args.no_analysis,
                    figures=not args.no_figures,
                    resolution_registry=benchmark_resolution_registry,
                    resolution_segment_characters=args.resolution_segment_characters,
                    ablation_row=(
                        selected_ablation.row_id
                        if selected_ablation is not None
                        else None
                    ),
                    system_prompt_file=benchmark_system_prompt,
                    append_system_prompt_file=benchmark_append_prompt,
                    conversation_features=DciConversationFeatures(
                        clear_tool_results=args.conversation_clear_tool_results,
                        clear_tool_results_keep_last=args.conversation_clear_tool_results_keep_last,
                        externalize_tool_results=args.conversation_externalize_tool_results,
                        strip_thinking=args.conversation_strip_thinking,
                        strip_usage=args.conversation_strip_usage,
                    ),
                ),
                paths=paths,
            )
        except (
            DciBenchmarkError,
            DciEvaluationError,
            DciRunError,
            OSError,
            ValueError,
        ):
            stderr.write("DCI benchmark failed\n")
            return 2
        stdout.write(f"output_root={result.output_root}\n")
        stdout.write(f"total={result.counts['total']}\n")
        return 0
    if args.command == "system-prompt":
        try:
            append_system_prompt_file = _resolve_resource(
                args.append_system_prompt_file,
                invocation_cwd=invocation_cwd,
                repo_root=root,
            )
            stdout.write(
                render_pi_system_prompt(
                    paths,
                    _absolute_from_invocation(args.cwd, invocation_cwd),
                    args.tools,
                    append_system_prompt_file,
                )
            )
            return 0
        except (OSError, RuntimeError, ValueError):
            stderr.write("DCI system prompt generation failed\n")
            return 2
    if args.command == "resume":
        try:
            output_dir = _output_path_from_invocation(args.output_dir, invocation_cwd)
            if _path_has_symlink(output_dir):
                raise ValueError("run destination is unsafe")
            request = resume_request_from_output_dir(output_dir)
            result = run_pi_research(paths, request, output_dir=output_dir)
        except (DciRunError, OSError, ValueError):
            stderr.write("DCI Pi execution failed\n")
            return 2
        _write_run_result(stdout, result)
        return 0
    if args.command == "terminal":
        try:
            if not stdin.isatty() or not stdout.isatty():
                raise ValueError("terminal requires an interactive TTY")
            question_file = _resolve_resource(
                args.question_file, invocation_cwd=invocation_cwd, repo_root=root
            )
            system_prompt_file = _resolve_resource(
                args.system_prompt_file,
                invocation_cwd=invocation_cwd,
                repo_root=root,
            )
            append_system_prompt_file = _resolve_resource(
                args.append_system_prompt_file,
                invocation_cwd=invocation_cwd,
                repo_root=root,
            )
            initial_question = _read_terminal_question(
                args, question_file=question_file
            )
            options = _terminal_runtime_options(args)
            terminal_cwd = validate_terminal_cwd(
                _path_from_invocation(args.cwd, invocation_cwd)
            )
            return run_pi_terminal(
                package_dir=paths.pi.package_dir,
                cwd=terminal_cwd,
                agent_dir=paths.pi.agent_dir,
                provider=options.provider,
                model=options.model,
                tools=options.tools,
                system_prompt_file=system_prompt_file,
                append_system_prompt_file=append_system_prompt_file,
                thinking_level=options.thinking_level,
                extra_args=options.extra_args,
                node_max_old_space_size_mb=options.node_max_old_space_size_mb,
                initial_question=initial_question,
                stdin=stdin,
                stdout=stdout,
            )
        except (OSError, RuntimeError, ValueError):
            stderr.write("DCI Pi terminal failed\n")
            return 2
    if args.resume:
        stderr.write("use asterion-dci resume --output-dir RUN_DIR\n")
        return 2
    try:
        question_file = _resolve_resource(
            args.question_file, invocation_cwd=invocation_cwd, repo_root=root
        )
        system_prompt_file = _resolve_resource(
            args.system_prompt_file, invocation_cwd=invocation_cwd, repo_root=root
        )
        append_system_prompt_file = _resolve_resource(
            args.append_system_prompt_file,
            invocation_cwd=invocation_cwd,
            repo_root=root,
        )
        evaluation_answer_file = _resolve_resource(
            args.eval_answer_file,
            invocation_cwd=invocation_cwd,
            repo_root=root,
        )
        evaluation_answer = _read_evaluation_answer(
            args, evaluation_answer_file=evaluation_answer_file
        )
        if (
            args.eval_answer is not None or args.eval_answer_file is not None
        ) and not evaluation_answer:
            raise ValueError("evaluation answer is required")
        question = _read_question(args, stdin, question_file=question_file)
        run_cwd = _absolute_from_invocation(args.cwd, invocation_cwd)
        if args.run_id is not None and not _safe_run_id(args.run_id):
            raise ValueError("invalid run id")
        conversation_features = DciConversationFeatures(
            clear_tool_results=args.conversation_clear_tool_results,
            clear_tool_results_keep_last=args.conversation_clear_tool_results_keep_last,
            externalize_tool_results=args.conversation_externalize_tool_results,
            strip_thinking=args.conversation_strip_thinking,
            strip_usage=args.conversation_strip_usage,
        )
    except (OSError, RuntimeError, ValueError):
        stderr.write("DCI Pi execution failed\n")
        return 2
    if not question:
        stderr.write("question is required\n")
        return 2
    try:
        request = replace(
            request_from_runtime_options(
                _runtime_options(args),
                run_id=args.run_id or "pending-generated-run-id",
                question=question,
                cwd=run_cwd,
            ),
            max_turns=args.max_turns,
            show_tools=args.show_tools,
            system_prompt_file=system_prompt_file,
            append_system_prompt_file=append_system_prompt_file,
            conversation_features=conversation_features,
        )
        validate_dci_run_request(request, paths)
        run_id = args.run_id or _new_run_id()
        request = replace(request, run_id=run_id)
        output_dir = (
            _output_path_from_invocation(args.output_dir, invocation_cwd)
            if args.output_dir is not None
            else paths.output_root / run_id
        )
        if _path_has_symlink(output_dir) or output_dir.exists():
            raise ValueError("run destination already exists")
    except (OSError, RuntimeError, ValueError):
        stderr.write("DCI Pi execution failed\n")
        return 2
    try:
        result = run_pi_research(paths, request, output_dir=output_dir)
    except DciRunError:
        stderr.write("DCI Pi execution failed\n")
        return 2
    if args.eval_answer is not None or args.eval_answer_file is not None:
        try:
            verdict = evaluate_run_directory(
                result.output_dir,
                gold_answer=evaluation_answer,
                judge_config=JudgeConfig.from_env(),
            )
        except (DciEvaluationError, OSError, ValueError):
            stderr.write("DCI evaluation failed\n")
            return 2
        stdout.write(f"output_dir={result.output_dir}\n")
        stdout.write(f"is_correct={verdict['is_correct']}\n")
        stdout.write("evaluation_uri=eval_result.json\n")
        return 0
    _write_run_result(stdout, result)
    return 0


def _read_question(
    args: argparse.Namespace,
    stdin: TextIO,
    *,
    question_file: Path | None,
) -> str:
    if question_file is not None:
        return question_file.read_text(encoding="utf-8").strip()
    if args.question:
        return " ".join(args.question).strip()
    if stdin.isatty():
        return ""
    return stdin.read().strip()


def _read_terminal_question(
    args: argparse.Namespace, *, question_file: Path | None
) -> str | None:
    if question_file is not None:
        return question_file.read_text(encoding="utf-8").strip() or None
    if args.question:
        return " ".join(args.question).strip() or None
    return None


def _absolute_from_invocation(path: Path, invocation_cwd: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = invocation_cwd / candidate
    return candidate.resolve()


def _path_from_invocation(path: Path, invocation_cwd: Path) -> Path:
    """Make an input path absolute without following security-relevant links."""

    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = invocation_cwd / candidate
    return Path(os.path.normpath(candidate))


def _output_path_from_invocation(path: Path, invocation_cwd: Path) -> Path:
    """Make a destination absolute without erasing security-relevant links."""

    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = invocation_cwd / candidate
    return Path(os.path.normpath(candidate))


def _resolve_resource(
    path: Path | None,
    *,
    invocation_cwd: Path,
    repo_root: Path,
) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    candidates = (
        (expanded,)
        if expanded.is_absolute()
        else (invocation_cwd / expanded, repo_root / expanded)
    )
    for candidate in dict.fromkeys(candidates):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if _path_has_symlink(candidate):
            raise ValueError("resource path is unsafe")
        metadata = candidate.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o444 == 0:
            raise ValueError("resource is not readable")
        resolved = candidate.resolve(strict=True)
        with resolved.open("rb"):
            pass
        return resolved
    raise ValueError("resource does not exist")


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    parts = absolute.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"asterion-dci-{timestamp}-{secrets.token_hex(4)}"


def _safe_run_id(value: str) -> bool:
    return (
        bool(value.strip()) and value not in {".", ".."} and Path(value).name == value
    )


def _read_evaluation_answer(
    args: argparse.Namespace,
    *,
    evaluation_answer_file: Path | None,
) -> str | None:
    if evaluation_answer_file is not None:
        return evaluation_answer_file.read_text(encoding="utf-8").strip()
    if args.eval_answer is None:
        return None
    return str(args.eval_answer).strip()


def _write_command_failure(stderr: TextIO, command: str) -> None:
    messages = {
        "ablation": "DCI ablation command failed\n",
        "paper": "DCI paper command failed\n",
        "evaluate": "DCI evaluation failed\n",
        "benchmark": "DCI benchmark failed\n",
        "system-prompt": "DCI system prompt generation failed\n",
        "terminal": "DCI Pi terminal failed\n",
    }
    stderr.write(messages.get(command, "DCI Pi execution failed\n"))


def _requested_command(argv: list[str]) -> str:
    """Classify only the exact command token without retaining argument values."""

    return (
        argv[0]
        if argv
        and argv[0]
        in {
            "run",
            "terminal",
            "resume",
            "system-prompt",
            "evaluate",
            "benchmark",
            "ablation",
            "paper",
        }
        else ""
    )


_BATCH_PROFILE_FIELDS = frozenset(
    {
        "dataset",
        "output_root",
        "corpus",
        "mode",
        "provider",
        "model",
        "tools",
        "max_turns",
        "max_concurrency",
        "runtime_context_level",
        "thinking_level",
        "node_max_old_space_size_mb",
    }
)
_BATCH_PROFILE_REQUIRED_FIELDS = _BATCH_PROFILE_FIELDS - {"provider", "model"}
_BATCH_PROFILE_PATH_FIELDS = frozenset({"dataset", "output_root", "corpus"})


def _load_batch_profiles() -> dict[str, dict[str, object]]:
    resource = resources.files("asterion.dci.resources").joinpath(
        "batch-profiles.json"
    )
    document = json.loads(resource.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "profiles"}
        or document.get("schema") != "asterion.dci.batch-profiles/v1"
        or not isinstance(document.get("profiles"), dict)
    ):
        raise ValueError("batch profile resource is invalid")
    profiles: dict[str, dict[str, object]] = {}
    for name, value in document["profiles"].items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            raise ValueError("batch profile resource is invalid")
        fields = set(value)
        if not _BATCH_PROFILE_REQUIRED_FIELDS.issubset(
            fields
        ) or not fields.issubset(_BATCH_PROFILE_FIELDS):
            raise ValueError("batch profile resource is invalid")
        for field in _BATCH_PROFILE_PATH_FIELDS:
            path_value = value.get(field)
            if not isinstance(path_value, str):
                raise ValueError("batch profile resource is invalid")
            path = Path(path_value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("batch profile resource is invalid")
        if value.get("mode") not in {"qa", "ir"}:
            raise ValueError("batch profile resource is invalid")
        for field in ("provider", "model"):
            if field in value and (
                not isinstance(value[field], str) or not value[field]
            ):
                raise ValueError("batch profile resource is invalid")
        if not isinstance(value.get("tools"), str) or not value["tools"]:
            raise ValueError("batch profile resource is invalid")
        for field in (
            "max_turns",
            "max_concurrency",
            "node_max_old_space_size_mb",
        ):
            number = value.get(field)
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise ValueError("batch profile resource is invalid")
        context_level = value.get("runtime_context_level")
        thinking_level = value.get("thinking_level")
        if not isinstance(context_level, str) or not context_level:
            raise ValueError("batch profile resource is invalid")
        if thinking_level is not None and (
            not isinstance(thinking_level, str) or not thinking_level
        ):
            raise ValueError("batch profile resource is invalid")
        profiles[name] = dict(value)
    return profiles


def _apply_benchmark_profile(
    args: argparse.Namespace, *, repo_root: Path, invocation_cwd: Path
) -> None:
    explicit_mode = args.mode is not None
    explicit_paths = {
        field: getattr(args, field) is not None for field in _BATCH_PROFILE_PATH_FIELDS
    }
    if args.profile is not None:
        profile = _load_batch_profiles().get(args.profile)
        if profile is None:
            raise ValueError("batch profile is unknown")
        for field, value in profile.items():
            if getattr(args, field) is None:
                setattr(args, field, value)
    if args.enable_ir:
        if explicit_mode and args.mode != "ir":
            raise ValueError("benchmark mode controls conflict")
        args.mode = "ir"
    if args.dataset is None or args.output_root is None:
        raise ValueError("benchmark dataset and output are required")
    args.mode = "qa" if args.mode is None else args.mode
    args.max_concurrency = 1 if args.max_concurrency is None else args.max_concurrency
    args.resume_policy = (
        "compatible" if args.resume_policy is None else args.resume_policy
    )
    for field in _BATCH_PROFILE_PATH_FIELDS:
        value = getattr(args, field)
        if value is None:
            continue
        path = Path(value)
        base = invocation_cwd if explicit_paths[field] else repo_root
        if field == "output_root":
            resolved = _output_path_from_invocation(path, base)
        else:
            resolved = _path_from_invocation(path, base)
        setattr(args, field, resolved)
    if args.cwd is None:
        args.cwd = args.corpus if args.corpus is not None else invocation_cwd
    else:
        args.cwd = _path_from_invocation(args.cwd, invocation_cwd)


def _judge_config(args: argparse.Namespace) -> JudgeConfig:
    base = JudgeConfig.from_env()
    argument_fields = {
        "base_url": "judge_base_url",
        "api": "judge_api",
        "model": "judge_model",
        "timeout_seconds": "judge_timeout_seconds",
        "max_output_tokens": "judge_max_output_tokens",
        "json_mode": "judge_json_mode",
        "strict_json_schema": "judge_strict_json_schema",
        "responses_store": "judge_responses_store",
        "thinking": "judge_thinking",
        "input_price_per_1m": "judge_input_price_per_1m",
        "cached_input_price_per_1m": "judge_cached_input_price_per_1m",
        "output_price_per_1m": "judge_output_price_per_1m",
    }
    overrides = {
        field: value
        for field, argument in argument_fields.items()
        if (value := getattr(args, argument)) is not None
    }
    api_key_env = args.judge_api_key_env or base.api_key_env
    direct_key = os.environ.get("DCI_EVAL_JUDGE_API_KEY", "").strip() or os.environ.get(
        "ASTERION_DCI_JUDGE_API_KEY", ""
    ).strip()
    overrides.update(
        {
            "api_key_env": api_key_env,
            "api_key": direct_key or os.environ.get(api_key_env, "").strip(),
        }
    )
    return replace(base, **overrides)


def _runtime_options(args: argparse.Namespace) -> DciRuntimeOptions:
    values = {
        "runtime": args.runtime,
        "provider": args.provider,
        "model": args.model,
        "tools": args.tools,
        "timeout_seconds": args.rpc_timeout_seconds,
        "runtime_context_level": args.runtime_context_level,
        "thinking_level": args.thinking_level,
        "node_max_old_space_size_mb": args.node_max_old_space_size_mb,
        "keep_session": args.keep_session,
        "extra_args": tuple(args.extra_arg or ()),
    }
    return resolve_dci_runtime_options(
        {name: value for name, value in values.items() if value is not None}
    )


def _terminal_runtime_options(args: argparse.Namespace) -> DciRuntimeOptions:
    values = {
        "provider": args.provider,
        "model": args.model,
        "tools": args.tools,
        "thinking_level": args.thinking_level,
        "node_max_old_space_size_mb": args.node_max_old_space_size_mb,
        "extra_args": tuple(args.extra_arg or ()),
        "timeout_seconds": None,
        "runtime_context_level": None,
        "keep_session": True,
    }
    return resolve_dci_runtime_options(
        {name: value for name, value in values.items() if value is not None}
    )


def _write_run_result(stdout: TextIO, result: DciRunResult) -> None:
    stdout.write(f"output_dir={result.output_dir}\n")
    stdout.write(f"status={result.status}\n")
    stdout.write("final_answer_uri=final.txt\n")
