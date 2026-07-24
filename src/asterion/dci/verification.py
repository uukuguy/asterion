"""Self-description and bounded verification for the Asterion DCI product."""

from __future__ import annotations

import argparse
import hashlib
import math
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Protocol, TextIO

from asterion.dci.ablation import (
    bounded_ablation_input_paths,
    paper_ablation_matrix_sha256,
    paper_ablation_row_ids,
    resolve_bounded_corpus_manifest,
    validate_paper_ablation_matrix,
)
from asterion.applications.product import (
    CapabilityFunction,
    CapabilityProductDescription,
    ConfigurationRequirement,
    InstalledCapabilityProduct,
    VerificationCheckResult,
    VerificationProfile,
    VerificationRequest,
    VerificationResult,
)
from asterion.dci.config import (
    DciPaths,
    DciRuntimeOptions,
    PI_DEFAULT_AGENT_DIR,
    PI_DEFAULT_MODEL,
    PI_DEFAULT_PROVIDER,
    PI_MIN_NODE_VERSION,
    PI_MIN_NODE_VERSION_TEXT,
    load_asterion_dci_env,
    parse_node_version,
    resolve_dci_paths,
    resolve_dci_runtime_options,
)
from asterion.dci.evaluation import evaluate_run_directory
from asterion.dci.artifacts import DciConversationFeatures
from asterion.dci.judge import (
    DEFAULT_JUDGE_API_KEY_ENV,
    DEFAULT_JUDGE_MODEL,
    JudgeConfig,
    build_judge_request,
)
from asterion.dci.context_profiles import context_profile_names
from asterion.dci.experiment_profiles import (
    EXPERIMENT_AUTHORIZATION_SCHEMA,
    authorize_full_execution,
    experiment_profile_schema_sha256,
    experiment_profiles_sha256,
    experiment_profile_sha256,
    resolve_experiment_profile,
)
from asterion.dci.paper_benchmarks import (
    paper_benchmark_ids,
    paper_benchmark_inventory_sha256,
    paper_experiment_scope_ids,
    paper_experiment_scopes_sha256,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.dci.run import DciRunRequest, DciRunResult, run_pi_research
from asterion.dci.reproduction import (
    compare_reproduction_runs,
    load_run_manifest,
    reproduction_result_schema_sha256,
    reproduction_target_schema_sha256,
    reproduction_targets_sha256,
    write_comparison_report,
)


PAPER_BENCHMARK_REPORT_SCHEMA = "asterion.dci.paper-benchmark-acceptance/v2"
_PAPER_OPERATION_PLAN = ("qa-agent", "qa-judge", "ir-agent")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40,64}")
_PUBLIC_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*")


@dataclass(frozen=True)
class BasicVerificationCase:
    case_id: str
    question: str
    corpus_subdir: str
    expected_answer: str | None
    max_turns: int | None
    thinking_level: str


BASIC_CASES = (
    BasicVerificationCase(
        case_id="basic-corpus-research",
        question=(
            "Answer the following question using only wiki_dump.jsonl in the current "
            "directory. Do not use web search. Use rg instead of grep for fast searching. "
            "Question: In which street did the Great Fire of London originate?"
        ),
        corpus_subdir="wiki_corpus",
        expected_answer=None,
        max_turns=6,
        thinking_level="high",
    ),
    BasicVerificationCase(
        case_id="runtime-context-and-judge",
        question=(
            "Read the files in the current directory. Do not use web search. Use rg instead "
            "of grep when searching. Question: In the Bonang Matheba interview where the "
            "third-to-last question asks about the origin of the name given to her by radio "
            "listeners, what is the interviewer's first name? Answer with just the first "
            "name and one supporting file path."
        ),
        corpus_subdir="bc_plus_docs",
        expected_answer="Adaku",
        max_turns=6,
        thinking_level="high",
    ),
)


DCI_PRODUCT_DESCRIPTION = CapabilityProductDescription(
    product_id="asterion-dci",
    version="1.0.0",
    summary="DCI local-corpus research, evaluation, and benchmark capability",
    functions=(
        CapabilityFunction(
            "ablation",
            "Validate, list, and render deterministic paper/bounded matrices",
            ("asterion-dci", "ablation", "--help"),
        ),
        CapabilityFunction(
            "benchmark",
            "Run bounded QA and IR benchmarks with metrics and analysis",
            ("asterion-dci", "benchmark", "--help"),
        ),
        CapabilityFunction(
            "evaluate",
            "Evaluate one saved research run with the configured Judge",
            ("asterion-dci", "evaluate", "--help"),
        ),
        CapabilityFunction(
            "export",
            "Export BC+, BRIGHT, or QA result formats",
            ("asterion-dci", "export", "--help"),
        ),
        CapabilityFunction(
            "installed-application",
            "Run the installed DCI research capability through Asterion",
            (
                "asterion",
                "run",
                "--provider",
                "dci-agent-lite",
                "--application",
                "dci.research-capability@1.0.0",
                "--runtime",
                "pi.reference",
            ),
        ),
        CapabilityFunction(
            "paper-contracts",
            "Describe body-free paper benchmark, metric, and matrix identities",
            ("asterion-dci", "paper", "describe"),
        ),
        CapabilityFunction(
            "research",
            "Research a question against a local corpus with Pi",
            ("asterion-dci", "run", "--help"),
        ),
        CapabilityFunction(
            "resume",
            "Continue a saved Pi research session",
            ("asterion-dci", "resume", "--help"),
        ),
        CapabilityFunction(
            "terminal",
            "Open the interactive DCI terminal workflow",
            ("asterion-dci", "terminal", "--help"),
        ),
    ),
    configuration=(
        ConfigurationRequirement(
            "ASTERION_DCI_CORPUS_ROOT",
            "Parent directory containing wiki_corpus and bc_plus_docs",
            ("basic", "complete", "preflight"),
            False,
            "./corpus",
            "Usually pass --corpus-root instead of setting this value",
        ),
        ConfigurationRequirement(
            "ASTERION_DCI_OUTPUT_ROOT",
            "Directory for Asterion DCI run artifacts",
            ("basic", "complete"),
            False,
            "./outputs/asterion-dci-runs",
            "Usually pass --output-root when verifying",
        ),
        ConfigurationRequirement(
            "DCI_EVAL_JUDGE_API_KEY_ENV",
            "Name of the environment variable holding the Judge credential",
            ("basic", "complete", "preflight"),
            False,
            DEFAULT_JUDGE_API_KEY_ENV,
            "Set this name and then set the named secret variable in .env",
        ),
        ConfigurationRequirement(
            "DCI_EVAL_JUDGE_MODEL",
            "Judge model used for the evaluated basic case",
            ("basic", "complete", "preflight"),
            False,
            DEFAULT_JUDGE_MODEL,
            "Use the same Judge settings as original DCI",
        ),
        ConfigurationRequirement(
            "DCI_MODEL",
            "Pi model used for research",
            ("basic", "complete", "preflight"),
            False,
            PI_DEFAULT_MODEL,
            "Override only when selecting another model from DCI_PROVIDER",
        ),
        ConfigurationRequirement(
            "DCI_PI_AGENT_DIR",
            "User-managed Pi agent and authentication directory",
            ("basic", "complete", "preflight"),
            False,
            PI_DEFAULT_AGENT_DIR,
            "Authenticate with Pi, then select its agent directory; setup never copies credentials",
        ),
        ConfigurationRequirement(
            "DCI_PI_DIR",
            "External Pi checkout",
            ("basic", "complete", "preflight"),
            False,
            "./pi",
            "Run make setup-pi to create and build the locked checkout",
        ),
        ConfigurationRequirement(
            "DCI_PROVIDER",
            "Pi model provider",
            ("basic", "complete", "preflight"),
            False,
            PI_DEFAULT_PROVIDER,
            "Override only when intentionally selecting another Pi provider",
        ),
        ConfigurationRequirement(
            "PROVIDER_API_KEY",
            "Credential selected from the provider name, such as OPENAI_API_KEY",
            ("basic", "complete", "preflight"),
            True,
            None,
            "Set the provider-specific key in .env; its value is never displayed",
        ),
    ),
    profiles=(
        VerificationProfile(
            "acceptance",
            "Check the complete local product inventory without model requests",
            "provider-free",
            0,
            False,
        ),
        VerificationProfile(
            "basic",
            "Run the two original DCI-equivalent examples and one Judge check",
            "bounded-provider-backed",
            3,
            False,
        ),
        VerificationProfile(
            "complete",
            "Run preflight, both basic examples, and local product acceptance",
            "bounded-provider-backed",
            3,
            False,
        ),
        VerificationProfile(
            "preflight",
            "Check configuration, Pi, Node, corpora, and Judge without requests",
            "provider-free",
            0,
            False,
        ),
    ),
)


def paper_product_contract() -> dict[str, object]:
    """Return the installed, body-free paper and AF-340 profile identity."""

    from asterion.dci.experiment_profiles import experiment_profile_ids

    dataset_ids = paper_benchmark_ids()
    scope_ids = paper_experiment_scope_ids()
    matrix_sha256 = paper_ablation_matrix_sha256()
    inventory_sha256 = paper_benchmark_inventory_sha256()
    scopes_sha256 = paper_experiment_scopes_sha256()
    profiles_sha256 = experiment_profiles_sha256()
    batch_profiles = tuple(
        sorted(
            {
                dataset.batch_profile
                for dataset_id in dataset_ids
                if (dataset := resolve_paper_benchmark(dataset_id)).batch_profile
                is not None
            }
        )
    )
    return {
        "schema": "dci.paper-product-contract/v1",
        "dataset_ids": list(dataset_ids),
        "experiment_scope_ids": list(scope_ids),
        "ablation_row_ids": list(paper_ablation_row_ids()),
        "context_profiles": list(context_profile_names()),
        "batch_profiles": list(batch_profiles),
        "beir_profiles": ["beir.arguana", "beir.scifact"],
        "resolution_metrics": [
            "coverage_any",
            "coverage_mean",
            "coverage_all",
            "localization",
            "retained_coverage",
        ],
        "analysis_configuration": {
            "alignment_version": "dci.paper-alignment/v1",
            "segment_characters": "required-positive-integer",
            "read_minimum_evidence_overlap": 0.5,
        },
        "safe_artifact_schemas": [
            "asterion.dci.batch-analysis/v1",
            "asterion.dci.batch-item/v1",
            "dci.trajectory-resolution-summary/v1",
        ],
        "benchmark_inventory_sha256": inventory_sha256,
        "experiment_scopes_sha256": scopes_sha256,
        "ablation_matrix_sha256": matrix_sha256,
        "experiment_profile_ids": list(experiment_profile_ids()),
        "experiment_profiles_sha256": profiles_sha256,
        "resources": {
            "experiment-profile.schema.json": experiment_profile_schema_sha256(),
            "experiment-profiles.json": profiles_sha256,
            "paper-ablation-matrix.json": matrix_sha256,
            "paper-benchmarks.json": inventory_sha256,
            "paper-experiment-scopes.json": scopes_sha256,
            "reproduction-result.schema.json": reproduction_result_schema_sha256(),
            "reproduction-target.schema.json": reproduction_target_schema_sha256(),
            "reproduction-targets.json": reproduction_targets_sha256(),
        },
        "paper_full_executable": False,
        "paper_full_requires_invocation_authorization": True,
        "paper_full_authorization": {
            "required": True,
            "schema": EXPERIMENT_AUTHORIZATION_SCHEMA,
            "environment_authorization": False,
        },
    }


@dataclass(frozen=True)
class PaperBenchmarkReadiness:
    """Body-free identities established before any bounded external operation."""

    output_root: Path
    provider: str
    model: str
    judge_identity: tuple[tuple[str, object], ...]
    pi_revision: str
    pi_tracked_status_sha256: str
    resource_digests: tuple[tuple[str, str], ...]
    paths: DciPaths | None = None
    runtime_options: DciRuntimeOptions | None = None
    judge_config: JudgeConfig | None = None
    corpus_dir: Path | None = None


@dataclass(frozen=True)
class PaperBenchmarkOperationEvidence:
    """One body-free operation result whose private files remain digest-bound."""

    operation_id: str
    kind: str
    artifact_digests: tuple[tuple[str, str], ...]
    accepted: bool

    def validate(self) -> None:
        expected_kind = {
            "qa-agent": "agent",
            "qa-judge": "judge",
            "ir-agent": "agent",
        }.get(self.operation_id)
        names = [name for name, _digest in self.artifact_digests]
        if (
            self.kind != expected_kind
            or type(self.accepted) is not bool
            or not self.accepted
            or not self.artifact_digests
            or len(names) != len(set(names))
            or any(
                not _safe_relative_artifact_name(name)
                or _SHA256.fullmatch(digest) is None
                for name, digest in self.artifact_digests
            )
        ):
            raise ValueError("DCI paper benchmark evidence is invalid")


PaperReadinessChecker = Callable[[argparse.Namespace, Path], PaperBenchmarkReadiness]
PaperOperationRunner = Callable[
    [PaperBenchmarkReadiness, str], PaperBenchmarkOperationEvidence | None
]


def _safe_relative_artifact_name(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and path.name != ""


def paper_benchmark_resource_digests() -> tuple[tuple[str, str], ...]:
    """Return the closed installed resource identity used by bounded acceptance."""

    validate_paper_ablation_matrix()
    root = resources.files("asterion.dci.resources")
    values: list[tuple[str, str]] = [
        ("ablation_matrix", paper_ablation_matrix_sha256()),
    ]
    for identity, relative in (
        ("experiment_profile_schema", "experiment-profile.schema.json"),
        ("experiment_profiles", "experiment-profiles.json"),
        ("reproduction_result_schema", "reproduction-result.schema.json"),
    ):
        values.append((identity, hashlib.sha256(root.joinpath(relative).read_bytes()).hexdigest()))
    for identity, relative in (
        ("qa_fixture", "paper-fixtures/qa.jsonl"),
        ("ir_fixture", "paper-fixtures/ir.jsonl"),
    ):
        raw = root.joinpath(relative).read_bytes()
        values.append((identity, hashlib.sha256(raw).hexdigest()))
    manifest = resolve_bounded_corpus_manifest("tiny.base/v1")
    values.append(("corpus_manifest", manifest.identity_sha256))
    return tuple(values)


def _canonical_json_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def paper_judge_identity(config: JudgeConfig) -> tuple[tuple[str, object], ...]:
    """Return the credential-free Judge and request-shaping identity."""

    public = config.public_dict()
    request = build_judge_request(
        config,
        question="[question]",
        gold_answer="[gold-answer]",
        predicted_answer="[predicted-answer]",
    )
    public["prompt_contract_sha256"] = _canonical_json_sha256(request)
    return tuple(sorted(public.items()))


def _paper_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asterion-dci paper verify", exit_on_error=False
    )
    parser.add_argument("--provider-backed", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output-root", type=Path)
    return parser


def _paper_reproduce_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asterion-dci paper reproduce", exit_on_error=False
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--estimated-budget-usd", type=float, required=True)
    parser.add_argument("--authorize-full", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _paper_compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asterion-dci paper compare", exit_on_error=False
    )
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _paper_profile_operations(profile_id: str) -> dict[str, int]:
    profile = resolve_experiment_profile(profile_id)
    max_agents = 0
    max_judges = 0
    for scope_id in profile.paper_scope_ids:
        selected_scope = resolve_paper_experiment_scope(scope_id)
        max_agents += selected_scope.selection_count
        dataset = resolve_paper_benchmark(selected_scope.dataset_id)
        if dataset.mode == "qa":
            max_judges += selected_scope.selection_count
    return {
        "max_agent_operations": max_agents,
        "max_judge_operations": max_judges,
        "max_external_operations": max_agents + max_judges,
    }


def _paper_reproduce_plan(profile_id: str) -> dict[str, object]:
    profile = resolve_experiment_profile(profile_id)
    operations = _paper_profile_operations(profile_id)
    return {
        "schema": "dci.paper-reproduction-plan/v1",
        "profile_id": profile.profile_id,
        "profile_identity_sha256": profile.identity_sha256,
        "paper_scope_ids": list(profile.paper_scope_ids),
        "paper_scope_dataset_ids": list(profile.paper_scope_dataset_ids),
        "paper_experiment_scopes_sha256": paper_experiment_scopes_sha256(),
        "dataset_count": len(profile.paper_scope_dataset_ids),
        **operations,
    }


def paper_reproduce_main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Prepare or authorize paper reproduction intent without provider execution."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        args = _paper_reproduce_parser().parse_args(argv)
        plan = _paper_reproduce_plan(args.profile)
    except (argparse.ArgumentError, OSError, RuntimeError, TypeError, ValueError):
        stderr.write("DCI paper reproduction plan failed\n")
        return 2
    profile = resolve_experiment_profile(args.profile)
    if not math.isfinite(args.estimated_budget_usd) or args.estimated_budget_usd < 0:
        stderr.write("DCI paper reproduction plan failed\n")
        return 2
    stdout.write(f"profile={profile.profile_id}\n")
    stdout.write(f"estimated_budget_usd={args.estimated_budget_usd}\n")
    stdout.write(f"dataset_count={plan['dataset_count']}\n")
    stdout.write(f"max_agent_operations={plan['max_agent_operations']}\n")
    stdout.write(f"max_judge_operations={plan['max_judge_operations']}\n")
    stdout.write(f"max_external_operations={plan['max_external_operations']}\n")
    stdout.write(f"profile_identity_sha256={plan['profile_identity_sha256']}\n")
    stdout.write(
        f"paper_experiment_scopes_sha256={plan['paper_experiment_scopes_sha256']}\n"
    )
    if not args.authorize_full:
        stdout.write("reproduction_authorized=no\n")
        stdout.write("operation_count=0\n")
        return 0
    try:
        authorize_full_execution(
            profile_id=args.profile,
            output_root=args.output_root,
            estimated_budget_usd=args.estimated_budget_usd,
            invocation_authorized=True,
            preflight_profile_sha256=experiment_profile_sha256(args.profile),
            preflight_dataset_inventory_sha256=profile.dataset_inventory_sha256,
            preflight_experiment_scopes_sha256=profile.experiment_scopes_sha256,
            preflight_scope_ids=profile.scope_ids,
            preflight_selected_ids_sha256=profile.selected_ids_sha256,
        )
    except (ValueError, OSError):
        stderr.write("DCI paper reproduction authorization failed\n")
        return 2
    stdout.write("reproduction_authorized=yes\n")
    if args.dry_run:
        stdout.write("operation_count=0\n")
        return 0
    stdout.write("operation_count=0\n")
    stdout.write("full execution is deferred\n")
    return 0


def paper_compare_main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Write one private versioned comparison report without exposing row bodies."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        args = _paper_compare_parser().parse_args(argv)
        profile = resolve_experiment_profile(args.profile)
        baseline = (
            None if args.baseline is None else load_run_manifest(args.baseline)
        )
        candidate = load_run_manifest(args.candidate)
        report = compare_reproduction_runs(baseline, candidate, profile)
        write_comparison_report(args.output, report)
    except (argparse.ArgumentError, OSError, RuntimeError, TypeError, ValueError):
        stderr.write("DCI paper reproduction comparison failed\n")
        return 2
    stdout.write(f"comparison_kind={report.comparison_kind}\n")
    stdout.write(f"profile={report.profile_id}\n")
    stdout.write(f"report_identity_sha256={report.identity_sha256}\n")
    if report.accepted is None:
        stdout.write("acceptance=not-applicable\n")
        return 0
    stdout.write(f"acceptance={'pass' if report.accepted else 'fail'}\n")
    return 0 if report.accepted else 1


def _private_regular(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        not path.is_symlink()
        and stat.S_ISREG(metadata.st_mode)
        and metadata.st_mode & 0o077 == 0
    )


def _prepare_private_output(path: Path) -> Path:
    output = Path(os.path.abspath(os.path.normpath(path)))
    current = Path(output.anchor)
    for part in output.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("DCI paper benchmark output is invalid")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("DCI paper benchmark output is invalid")
    else:
        output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    return output


def _clean_pi_identity(pi_dir: Path) -> tuple[str, str]:
    revision = subprocess.run(
        ["git", "-C", str(pi_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        [
            "git",
            "-C",
            str(pi_dir),
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise ValueError("DCI paper benchmark Pi runtime is not clean")
    return revision, hashlib.sha256(status.encode()).hexdigest()


def _paper_default_readiness(
    args: argparse.Namespace, repo_root: Path
) -> PaperBenchmarkReadiness:
    if args.env_file is None or args.output_root is None:
        raise ValueError("DCI paper benchmark preflight failed")
    env_file = Path(args.env_file).expanduser().resolve()
    if not _private_regular(env_file):
        raise ValueError("DCI paper benchmark preflight failed")
    if load_asterion_dci_env(repo_root, env_file=env_file) is None:
        raise ValueError("DCI paper benchmark preflight failed")
    paths = resolve_dci_paths(repo_root)
    options = resolve_dci_runtime_options()
    judge = JudgeConfig.from_env()
    if (
        _PUBLIC_IDENTITY.fullmatch(options.provider) is None
        or _PUBLIC_IDENTITY.fullmatch(options.model) is None
        or not judge.api_key
        or not (paths.pi.package_dir / "package.json").is_file()
        or not paths.pi.agent_dir.is_dir()
    ):
        raise ValueError("DCI paper benchmark preflight failed")
    provider_key = _provider_key_name(options.provider)
    pi_auth = paths.pi.agent_dir / "auth.json"
    if not (
        provider_key
        and os.environ.get(provider_key, "").strip()
        or _private_regular(pi_auth)
    ):
        raise ValueError("DCI paper benchmark preflight failed")
    revision, status_sha256 = _clean_pi_identity(paths.pi.repo_dir)
    try:
        locked_revision = (repo_root / "pi-revision.txt").read_text().strip()
    except OSError:
        raise ValueError("DCI paper benchmark preflight failed") from None
    if revision != locked_revision or _REVISION.fullmatch(revision) is None:
        raise ValueError("DCI paper benchmark preflight failed")
    _dataset, corpus = bounded_ablation_input_paths("bounded.tools.read-grep")
    return PaperBenchmarkReadiness(
        output_root=_prepare_private_output(args.output_root),
        provider=options.provider,
        model=options.model,
        judge_identity=paper_judge_identity(judge),
        pi_revision=revision,
        pi_tracked_status_sha256=status_sha256,
        resource_digests=paper_benchmark_resource_digests(),
        paths=paths,
        runtime_options=options,
        judge_config=judge,
        corpus_dir=corpus,
    )


def _private_artifact_digests(
    directory: Path, *, exclude: frozenset[str] = frozenset()
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_dir():
            if path.is_symlink():
                raise ValueError("DCI paper benchmark evidence is invalid")
            continue
        if not _private_regular(path):
            raise ValueError("DCI paper benchmark evidence is invalid")
        relative = path.relative_to(directory).as_posix()
        if relative in exclude:
            continue
        values.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    if not values:
        raise ValueError("DCI paper benchmark evidence is invalid")
    return tuple(values)


def _write_private_json(path: Path, value: dict[str, object]) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def _fixture_question(name: str) -> tuple[str, str]:
    resource = resources.files("asterion.dci.resources").joinpath(
        f"paper-fixtures/{name}.jsonl"
    )
    row = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(row, dict) or not isinstance(row.get("query"), str):
        raise ValueError("DCI paper benchmark fixture is invalid")
    answer = row.get("answer", "")
    if not isinstance(answer, str):
        raise ValueError("DCI paper benchmark fixture is invalid")
    return row["query"], answer


def _paper_default_operation_runner(
    readiness: PaperBenchmarkReadiness, operation_id: str
) -> PaperBenchmarkOperationEvidence:
    if (
        readiness.paths is None
        or readiness.runtime_options is None
        or readiness.judge_config is None
        or readiness.corpus_dir is None
    ):
        raise ValueError("DCI paper benchmark preflight failed")
    if operation_id == "qa-judge":
        qa_dir = readiness.output_root / "qa-agent"
        accepted = evaluate_run_directory(
            qa_dir,
            gold_answer=_fixture_question("qa")[1],
            judge_config=readiness.judge_config,
        ).get("is_correct") is True
        evaluation = qa_dir / "eval_result.json"
        if not accepted or not _private_regular(evaluation):
            raise ValueError("DCI paper benchmark Judge evidence is invalid")
        directory = readiness.output_root / operation_id
        directory.mkdir(mode=0o700)
        _write_private_json(
            directory / "evaluation-evidence.json",
            {
                "schema": "asterion.dci.paper-judge-evidence/v1",
                "accepted": True,
                "evaluation_sha256": hashlib.sha256(evaluation.read_bytes()).hexdigest(),
            },
        )
        evidence = PaperBenchmarkOperationEvidence(
            operation_id=operation_id,
            kind="judge",
            artifact_digests=_private_artifact_digests(directory),
            accepted=True,
        )
        evidence.validate()
        return evidence

    fixture = "qa" if operation_id == "qa-agent" else "ir"
    if operation_id not in {"qa-agent", "ir-agent"}:
        raise ValueError("DCI paper benchmark operation is invalid")
    question, _answer = _fixture_question(fixture)
    options = readiness.runtime_options
    output_dir = readiness.output_root / operation_id
    request = DciRunRequest(
        run_id=f"paper-benchmark-{fixture}",
        question=(
            "Use only files in the current directory. Do not use web search. "
            "Use the read and grep tools and cite the matching file name. " + question
        ),
        cwd=readiness.corpus_dir,
        provider=options.provider,
        model=options.model,
        tools="read,grep",
        max_turns=8,
        timeout_seconds=options.timeout_seconds,
        runtime_context_level="level4",
        thinking_level=options.thinking_level,
        node_max_old_space_size_mb=options.node_max_old_space_size_mb,
        keep_session=True,
        stream_text=False,
    )
    result = run_pi_research(
        readiness.paths,
        request,
        output_dir=output_dir,
        conversation_features=DciConversationFeatures(
            externalize_tool_results=True
        ),
    )
    if result.status != "completed" or (
        operation_id == "ir-agent" and "doc.txt" not in result.final_text
    ):
        raise ValueError("DCI paper benchmark agent evidence is invalid")
    evidence = PaperBenchmarkOperationEvidence(
        operation_id=operation_id,
        kind="agent",
        artifact_digests=_private_artifact_digests(
            output_dir,
            exclude=frozenset(
                {".dci-run.lock", "eval_result.json", "evaluation.json", "state.json"}
            ),
        ),
        accepted=True,
    )
    evidence.validate()
    return evidence


def _paper_report(
    readiness: PaperBenchmarkReadiness,
    operations: Sequence[PaperBenchmarkOperationEvidence],
) -> dict[str, object]:
    if (
        _PUBLIC_IDENTITY.fullmatch(readiness.provider) is None
        or _PUBLIC_IDENTITY.fullmatch(readiness.model) is None
        or len(dict(readiness.judge_identity)) != len(readiness.judge_identity)
        or set(dict(readiness.judge_identity))
        != set(JudgeConfig().public_dict()) | {"prompt_contract_sha256"}
        or _SHA256.fullmatch(
            str(dict(readiness.judge_identity).get("prompt_contract_sha256"))
        )
        is None
        or _REVISION.fullmatch(readiness.pi_revision) is None
        or _SHA256.fullmatch(readiness.pi_tracked_status_sha256) is None
        or [item.operation_id for item in operations] != list(_PAPER_OPERATION_PLAN)
        or len(dict(readiness.resource_digests)) != len(readiness.resource_digests)
        or any(_SHA256.fullmatch(value) is None for _name, value in readiness.resource_digests)
    ):
        raise ValueError("DCI paper benchmark evidence is invalid")
    for operation in operations:
        operation.validate()
    return {
        "schema": PAPER_BENCHMARK_REPORT_SCHEMA,
        "mode": "bounded-provider-backed",
        "provider": readiness.provider,
        "model": readiness.model,
        "judge": dict(readiness.judge_identity),
        "pi_revision": readiness.pi_revision,
        "pi_tracked_status_sha256": readiness.pi_tracked_status_sha256,
        "agent_operations": 2,
        "judge_operations": 1,
        "external_operations": 3,
        "api_request_multiplicity": "externally ambiguous",
        "operation_order": list(_PAPER_OPERATION_PLAN),
        "full_dataset_ran": False,
        "resources": dict(readiness.resource_digests),
        "operations": [
            {
                "operation_id": item.operation_id,
                "kind": item.kind,
                "accepted": item.accepted,
                "artifact_digests": dict(item.artifact_digests),
            }
            for item in operations
        ],
    }


def paper_benchmark_acceptance_main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    repo_root: Path | None = None,
    readiness_checker: PaperReadinessChecker | None = None,
    operation_runner: PaperOperationRunner | None = None,
) -> int:
    """Verify local contracts or run exactly two agents and one configured Judge."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        args = _paper_parser().parse_args(argv)
        paper_product_contract()
        paper_benchmark_resource_digests()
    except (argparse.ArgumentError, OSError, RuntimeError, TypeError, ValueError):
        stderr.write("DCI paper benchmark verification failed\n")
        return 2
    if not args.provider_backed:
        stdout.write("PASS\nAgent operations: 0\nJudge operations: 0\n")
        stdout.write("Planned external operations: 3\n")
        stdout.write("API request multiplicity: externally ambiguous\n")
        stdout.write("Full dataset ran: no\n")
        return 0
    root = Path.cwd().resolve() if repo_root is None else Path(repo_root).resolve()
    checker = _paper_default_readiness if readiness_checker is None else readiness_checker
    runner = _paper_default_operation_runner if operation_runner is None else operation_runner
    try:
        readiness = checker(args, root)
    except (OSError, RuntimeError, subprocess.SubprocessError, TypeError, ValueError):
        stderr.write("DCI paper benchmark preflight failed\n")
        return 2
    attempted = 0
    try:
        accepted: list[PaperBenchmarkOperationEvidence] = []
        for operation_id in _PAPER_OPERATION_PLAN:
            attempted += 1
            evidence = runner(readiness, operation_id)
            if not isinstance(evidence, PaperBenchmarkOperationEvidence):
                raise ValueError("DCI paper benchmark evidence is invalid")
            evidence.validate()
            accepted.append(evidence)
        report = _paper_report(readiness, accepted)
        _write_private_json(
            readiness.output_root / "paper-benchmark-acceptance.json", report
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        try:
            readiness.output_root.mkdir(parents=True, exist_ok=True)
            _write_private_json(
                readiness.output_root / "paper-benchmark-acceptance-failure.json",
                {
                    "schema": "asterion.dci.paper-benchmark-acceptance-failure/v1",
                    "attempted_external_operations": attempted,
                    "full_dataset_ran": False,
                },
            )
        except OSError:
            pass
        stderr.write(
            "DCI paper benchmark runtime/evidence failed after "
            f"{attempted} external operations\n"
        )
        return 2
    stdout.write("PASS\nAgent operations: 2\nJudge operations: 1\n")
    stdout.write("External operations: 3\n")
    stdout.write("API request multiplicity: externally ambiguous\n")
    stdout.write("Full dataset ran: no\n")
    stdout.write("Report: paper-benchmark-acceptance.json\n")
    return 0


class DciVerificationBackend(Protocol):
    def node_version(self) -> tuple[int, int, int] | None: ...

    def run_research_case(
        self, paths: DciPaths, request: DciRunRequest, *, output_dir: Path
    ) -> DciRunResult: ...

    def evaluate_case(
        self,
        output_dir: Path,
        *,
        expected_answer: str,
        judge_config: JudgeConfig,
    ) -> bool: ...


class LocalDciVerificationBackend:
    """Read-only local prerequisite adapter."""

    def node_version(self) -> tuple[int, int, int] | None:
        try:
            completed = subprocess.run(
                ["node", "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return parse_node_version(completed.stdout)

    def run_research_case(
        self, paths: DciPaths, request: DciRunRequest, *, output_dir: Path
    ) -> DciRunResult:
        return run_pi_research(paths, request, output_dir=output_dir)

    def evaluate_case(
        self,
        output_dir: Path,
        *,
        expected_answer: str,
        judge_config: JudgeConfig,
    ) -> bool:
        result = evaluate_run_directory(
            output_dir,
            gold_answer=expected_answer,
            judge_config=judge_config,
        )
        return result.get("is_correct") is True


def _acceptance_check(
    check_id: str,
    summary: str,
    *,
    actual: int,
    expected: int,
) -> VerificationCheckResult:
    passed = actual == expected
    return VerificationCheckResult(
        check_id=check_id,
        summary=summary if passed else f"{summary} is incomplete",
        status="PASS" if passed else "FAIL",
        counts=(("actual", actual), ("expected", expected)),
    )


def _installed_acceptance_checks() -> tuple[VerificationCheckResult, ...]:
    """Validate the exact installed provider and packaged-resource closure."""

    from asterion.applications.controlled_code import (
        create_provider as create_controlled_provider,
    )
    from asterion.applications.dci_agent_lite import (
        create_provider as create_dci_provider,
    )
    from asterion.applications.provider import validate_installed_provider
    from asterion.packages.catalog import discover_packages

    providers = (
        validate_installed_provider(
            create_controlled_provider(), selected_id="controlled-code"
        ),
        validate_installed_provider(
            create_dci_provider(), selected_id="dci-agent-lite"
        ),
    )
    applications = tuple(
        application
        for provider in providers
        for application in provider.applications
    )
    bound_assemblies = tuple(
        path
        for application in applications
        for path in application.assembly_paths
    )
    if (
        tuple(provider.provider_id for provider in providers)
        != ("controlled-code", "dci-agent-lite")
        or tuple(application.application_id for application in applications)
        != (
            "code.quality",
            "dci.research-capability",
            "dci.complete-application",
        )
        or len(bound_assemblies) != 5
    ):
        raise RuntimeError("installed application closure is invalid")

    catalog_roots = tuple(
        sorted(
            {
                root
                for application in applications
                for root in application.catalog_roots
            }
        )
    )
    manifests = discover_packages(catalog_roots).entries
    package_root = Path(str(resources.files("asterion"))).resolve()
    packaged_assemblies = tuple(
        sorted((package_root / "applications").glob("*/assemblies/*.json"))
    )

    profiles = context_profile_names()
    if profiles != ("level0", "level1", "level2", "level3", "level4"):
        raise RuntimeError("context profile closure is invalid")

    datasets = paper_benchmark_ids()
    scopes = paper_experiment_scope_ids()
    for dataset_id in datasets:
        resolve_paper_benchmark(dataset_id)
    for scope_id in scopes:
        resolve_paper_experiment_scope(scope_id)
    if (
        _SHA256.fullmatch(paper_benchmark_inventory_sha256()) is None
        or _SHA256.fullmatch(paper_experiment_scopes_sha256()) is None
    ):
        raise RuntimeError("paper identity closure is invalid")

    return tuple(
        sorted(
            (
                _acceptance_check(
                    "application-assemblies",
                    "Application assembly closure is valid",
                    actual=len(packaged_assemblies),
                    expected=6,
                ),
                _acceptance_check(
                    "application-providers",
                    "Installed provider closure is valid",
                    actual=len(providers),
                    expected=2,
                ),
                _acceptance_check(
                    "capability-manifests",
                    "Capability manifest closure is valid",
                    actual=len(manifests),
                    expected=11,
                ),
                _acceptance_check(
                    "context-profiles",
                    "Context profile closure is valid",
                    actual=len(profiles),
                    expected=5,
                ),
                _acceptance_check(
                    "paper-benchmarks",
                    "Paper benchmark identity closure is valid",
                    actual=len(datasets),
                    expected=13,
                ),
                _acceptance_check(
                    "paper-scopes",
                    "Paper scope identity closure is valid",
                    actual=len(scopes),
                    expected=16,
                ),
                _acceptance_check(
                    "provider-requests",
                    "Installed acceptance made no provider requests",
                    actual=0,
                    expected=0,
                ),
            ),
            key=lambda check: check.check_id,
        )
    )


@dataclass(frozen=True)
class DciProductVerifier:
    repo_root: Path
    backend: DciVerificationBackend

    def __call__(self, request: VerificationRequest) -> VerificationResult:
        if request.level == "preflight":
            return self.preflight(
                env_file=request.env_file, corpus_root=request.corpus_root
            )
        if request.level == "basic":
            return self.basic(request)
        if request.level == "acceptance":
            return self.acceptance(request.acceptance_root)
        if request.level == "complete":
            return self.complete(request)
        return VerificationResult(
            product_id=DCI_PRODUCT_DESCRIPTION.product_id,
            level=request.level,
            status="NOT RUN",
            checks=(
                VerificationCheckResult(
                    check_id="implementation",
                    summary="This verification level is not available yet",
                    status="NOT RUN",
                ),
            ),
            provider_backed_operation_count=0,
            full_dataset_ran=False,
        )

    def acceptance(self, acceptance_root: Path | None) -> VerificationResult:
        """Run installed package acceptance without provider requests."""

        del acceptance_root
        try:
            checks = _installed_acceptance_checks()
        except (OSError, RuntimeError, TypeError, ValueError):
            checks = (
                VerificationCheckResult(
                    check_id="installed-closure",
                    summary="Installed package closure is invalid",
                    status="FAIL",
                ),
            )
        return VerificationResult(
            product_id=DCI_PRODUCT_DESCRIPTION.product_id,
            level="acceptance",
            status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
            checks=checks,
            provider_backed_operation_count=0,
            full_dataset_ran=False,
        )

    def complete(self, request: VerificationRequest) -> VerificationResult:
        """Run preflight, bounded examples, and provider-free acceptance in order."""

        preflight = self.preflight(
            env_file=request.env_file, corpus_root=request.corpus_root
        )
        aggregate = [
            VerificationCheckResult(
                check_id="preflight",
                summary="All local and configured prerequisites are ready",
                status=preflight.status,
            )
        ]
        if preflight.status != "PASS":
            return _complete_result(aggregate, provider_backed_operations=0)
        basic = self.basic(request)
        aggregate.extend(basic.checks)
        if basic.status != "PASS":
            return _complete_result(
                aggregate, provider_backed_operations=basic.provider_backed_operation_count
            )
        acceptance = self.acceptance(request.acceptance_root)
        aggregate.extend(acceptance.checks)
        return _complete_result(
            aggregate,
            provider_backed_operations=basic.provider_backed_operation_count,
            forced_status=acceptance.status,
        )

    def basic(self, request: VerificationRequest) -> VerificationResult:
        """Run exactly the two accepted DCI examples and one Judge evaluation."""

        preflight = self.preflight(
            env_file=request.env_file, corpus_root=request.corpus_root
        )
        if preflight.status != "PASS":
            return VerificationResult(
                product_id=DCI_PRODUCT_DESCRIPTION.product_id,
                level="basic",
                status="FAIL",
                checks=(
                    VerificationCheckResult(
                        check_id="preflight",
                        summary="Prerequisites must pass before bounded verification",
                        status="FAIL",
                    ),
                ),
                provider_backed_operation_count=0,
                full_dataset_ran=False,
            )
        paths = resolve_dci_paths(self.repo_root)
        options = resolve_dci_runtime_options()
        corpus_root = _corpus_root(self.repo_root, request.corpus_root)
        output_root = (
            paths.output_root
            if request.output_root is None
            else request.output_root
        )
        private_root = output_root / f"verify-{secrets.token_hex(8)}"
        judge_config = JudgeConfig.from_env()
        checks: list[VerificationCheckResult] = []
        external_requests = 0
        for case in BASIC_CASES:
            run_request = _basic_request(case, options, paths, corpus_root)
            destination = private_root / case.case_id
            try:
                external_requests += 1
                run_result = self.backend.run_research_case(
                    paths, run_request, output_dir=destination
                )
                passed = run_result.status == "completed"
                judge_requests = 0
                if passed and case.expected_answer is not None:
                    external_requests += 1
                    judge_requests = 1
                    passed = self.backend.evaluate_case(
                        run_result.output_dir,
                        expected_answer=case.expected_answer,
                        judge_config=judge_config,
                    )
            except Exception:
                passed = False
                judge_requests = 0
            counts = [("native-runs", 1)]
            if judge_requests:
                counts.insert(0, ("judge-requests", judge_requests))
            checks.append(
                VerificationCheckResult(
                    check_id=case.case_id,
                    summary=(
                        "Bounded example completed"
                        if passed
                        else "Bounded example failed"
                    ),
                    status="PASS" if passed else "FAIL",
                    artifact_refs=(f"{case.case_id}/run",),
                    counts=tuple(counts),
                )
            )
            if not passed:
                break
        return VerificationResult(
            product_id=DCI_PRODUCT_DESCRIPTION.product_id,
            level="basic",
            status="PASS" if len(checks) == len(BASIC_CASES) and all(check.status == "PASS" for check in checks) else "FAIL",
            checks=tuple(checks),
            provider_backed_operation_count=external_requests,
            full_dataset_ran=False,
        )

    def preflight(
        self, *, env_file: Path | None, corpus_root: Path | None
    ) -> VerificationResult:
        loaded = load_asterion_dci_env(self.repo_root, env_file=env_file)
        paths = resolve_dci_paths(self.repo_root)
        options = resolve_dci_runtime_options()
        requested_env = self.repo_root / ".env" if env_file is None else env_file
        environment_ready = loaded is not None and requested_env.is_file()
        provider_key = _provider_key_name(options.provider)
        pi_auth = paths.pi.agent_dir / "auth.json"
        pi_managed_auth = (
            paths.pi.agent_dir.is_dir()
            and not paths.pi.agent_dir.is_symlink()
            and pi_auth.is_file()
            and not pi_auth.is_symlink()
        )
        agent_selection_ready = bool(options.provider and options.model)
        agent_authentication_ready = bool(
            (provider_key and os.environ.get(provider_key, "").strip())
            or pi_managed_auth
        )
        try:
            judge_ready = bool(JudgeConfig.from_env().api_key)
        except (TypeError, ValueError):
            judge_ready = False
        node_version = self.backend.node_version()
        pi_checkout_ready = (
            paths.pi.repo_dir.is_dir()
            and not paths.pi.repo_dir.is_symlink()
            and paths.pi.package_dir.is_dir()
            and (paths.pi.package_dir / "package.json").is_file()
        )
        built_pi_cli_ready = (
            pi_checkout_ready
            and (paths.pi.package_dir / "dist" / "cli.js").is_file()
        )
        resolved_corpus = _corpus_root(self.repo_root, corpus_root)
        resources_ready = all(
            (resolved_corpus / name).is_dir()
            and any(item.is_file() for item in (resolved_corpus / name).rglob("*"))
            for name in ("wiki_corpus", "bc_plus_docs")
        )
        checks = (
            _readiness_check(
                "agent-authentication",
                "Pi Agent authentication is available",
                "Authenticate with Pi and set DCI_PI_AGENT_DIR; setup never copies credentials",
                agent_authentication_ready,
            ),
            _readiness_check(
                "agent-selection",
                f"Agent selection resolves to {options.provider} / {options.model}",
                "Set DCI_PROVIDER and DCI_MODEL",
                agent_selection_ready,
            ),
            _readiness_check(
                "built-pi-cli",
                "The locked Pi coding-agent CLI is built",
                "Run make setup-pi to build the locked Pi CLI",
                built_pi_cli_ready,
            ),
            _readiness_check(
                "environment",
                "The selected environment file is available",
                "Run cp .env.template .env and add operator-owned authentication",
                environment_ready,
            ),
            _readiness_check(
                "judge",
                "Judge selection and authentication are available",
                "Set DCI_EVAL_JUDGE_MODEL, DCI_EVAL_JUDGE_API_KEY_ENV, and the named credential",
                judge_ready,
            ),
            _readiness_check(
                "node",
                f"Node.js version is at least {PI_MIN_NODE_VERSION_TEXT}",
                f"Install Node.js {PI_MIN_NODE_VERSION_TEXT} or newer",
                node_version is not None and node_version >= PI_MIN_NODE_VERSION,
            ),
            _readiness_check(
                "pi-checkout",
                "The locked external Pi checkout is available",
                "Run make setup-pi to provision the locked Pi checkout",
                pi_checkout_ready,
            ),
            _readiness_check(
                "resources-basic",
                "The basic wiki and BC+ corpora are available",
                "Run make setup-resources-basic",
                resources_ready,
            ),
        )
        return VerificationResult(
            product_id=DCI_PRODUCT_DESCRIPTION.product_id,
            level="preflight",
            status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
            checks=checks,
            provider_backed_operation_count=0,
            full_dataset_ran=False,
        )


def create_dci_product(
    *,
    repo_root: Path | None = None,
    backend: DciVerificationBackend | None = None,
) -> InstalledCapabilityProduct:
    """Build the installed DCI product contract without performing verification."""

    root = Path.cwd().resolve() if repo_root is None else Path(repo_root).resolve()
    verifier = DciProductVerifier(
        repo_root=root,
        backend=LocalDciVerificationBackend() if backend is None else backend,
    )
    return InstalledCapabilityProduct(
        description=DCI_PRODUCT_DESCRIPTION,
        verifier=verifier,
    )

def _provider_key_name(provider: str | None) -> str | None:
    if provider is None or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", provider) is None:
        return None
    aliases = {"google": "GOOGLE_API_KEY", "gemini": "GOOGLE_API_KEY"}
    return aliases.get(provider.lower(), f"{provider.upper().replace('-', '_')}_API_KEY")


def _corpus_root(repo_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    configured = os.environ.get("ASTERION_DCI_CORPUS_ROOT", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()
    return repo_root / "corpus"


def _check(check_id: str, summary: str, passed: bool) -> VerificationCheckResult:
    return VerificationCheckResult(
        check_id=check_id,
        summary=summary,
        status="PASS" if passed else "FAIL",
    )


def _readiness_check(
    check_id: str, pass_summary: str, repair_summary: str, passed: bool
) -> VerificationCheckResult:
    return _check(check_id, pass_summary if passed else repair_summary, passed)


def _basic_request(
    case: BasicVerificationCase,
    options: DciRuntimeOptions,
    paths: DciPaths,
    corpus_root: Path,
) -> DciRunRequest:
    return DciRunRequest(
        run_id=case.case_id,
        question=case.question,
        cwd=(corpus_root / case.corpus_subdir).resolve(),
        provider=options.provider,
        model=options.model,
        tools=options.tools,
        max_turns=case.max_turns,
        timeout_seconds=options.timeout_seconds,
        runtime_context_level=options.runtime_context_level,
        thinking_level=case.thinking_level,
        node_max_old_space_size_mb=options.node_max_old_space_size_mb,
        keep_session=False,
        extra_args=options.extra_args,
        pi_package_dir=paths.pi.package_dir,
        pi_agent_dir=paths.pi.agent_dir,
        stream_text=False,
    )


def _complete_result(
    checks: list[VerificationCheckResult],
    *,
    provider_backed_operations: int,
    forced_status: str | None = None,
) -> VerificationResult:
    ordered = tuple(sorted(checks, key=lambda check: check.check_id))
    if forced_status is None:
        status = "PASS" if all(check.status == "PASS" for check in ordered) else "FAIL"
    else:
        status = forced_status if forced_status != "PASS" else (
            "PASS" if all(check.status == "PASS" for check in ordered) else "FAIL"
        )
    return VerificationResult(
        product_id=DCI_PRODUCT_DESCRIPTION.product_id,
        level="complete",
        status=status,
        checks=ordered,
        provider_backed_operation_count=provider_backed_operations,
        full_dataset_ran=False,
    )
