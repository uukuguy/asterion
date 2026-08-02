"""Provider-free read-only Pathlight command line."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from asterion.pathlight import (
    MetricFilter,
    PathlightCatalog,
    TraceFilter,
    project_trace_flow,
    read_diagnosis_bundle,
    read_evaluation_bundle,
)
from asterion.pathlight.experiment import ExperimentCatalog, read_experiment_bundle
from asterion.workflow_evidence import read_workflow_observation_bundle


_ERROR = "asterion pathlight: request is invalid\n"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise ValueError("invalid pathlight arguments")


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run a provider-free, public-safe Pathlight read command."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    assert stdout is not None
    assert stderr is not None
    try:
        args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
        result = _execute(args)
        stdout.write(json.dumps(_json_copy(result), sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except Exception:
        stderr.write(_ERROR)
        return 2


def _execute(args: argparse.Namespace) -> object:
    if args.command == "trace":
        catalog = _catalog_from_evidence(args.evidence_file)
        if args.trace_command == "list":
            return catalog.list_traces(
                TraceFilter(args.status, args.kind, args.component_sha256)
            )
        if args.trace_command == "show":
            return catalog.show_trace(args.trace_id)
        if args.trace_command == "tail":
            return catalog.tail_trace(args.trace_id, after_sequence=args.after_sequence)
        if args.trace_command == "flow":
            return project_trace_flow(catalog.show_trace(args.trace_id))
    if args.command == "metrics":
        catalog = _catalog_from_evaluations(args.evaluation_file)
        return catalog.query_metrics(
            MetricFilter(
                args.metric_name,
                args.status,
                args.trace_sha256,
                args.metric_contract_sha256,
                args.dataset_snapshot_sha256,
                args.scope_sha256,
            )
        )
    if args.command == "evaluate":
        return _catalog_from_evaluations(args.evaluation_file).compare_evaluation_ids(
            args.baseline, args.candidate
        )
    if args.command == "experiment":
        catalog = _catalog_from_experiment(args.experiment_file)
        if args.experiment_command == "show":
            return catalog.show_plan(args.experiment_sha256)
        if args.experiment_command == "trials":
            return catalog.list_trials(
                args.experiment_sha256, evidence_state=args.evidence_state
            )
    if args.command == "diagnosis":
        return read_diagnosis_bundle(_diagnosis_path(args.diagnosis_file)).to_mapping()
    if args.command == "proposal":
        return [
            proposal.to_mapping()
            for proposal in read_diagnosis_bundle(_diagnosis_path(args.diagnosis_file)).proposals
        ]
    raise ValueError("invalid pathlight command")


def _catalog_from_evidence(values: Sequence[str]) -> PathlightCatalog:
    paths = _absolute_canonical_paths(values, "workflow-evidence.json")
    return PathlightCatalog.build(
        tuple(read_workflow_observation_bundle(path) for path in paths), (), ()
    )


def _catalog_from_evaluations(values: Sequence[str]) -> PathlightCatalog:
    paths = _absolute_canonical_paths(values, "pathlight-evaluations.json")
    bundles = tuple(read_evaluation_bundle(path) for path in paths)
    return PathlightCatalog.build(
        (),
        tuple(record for bundle in bundles for record in bundle.evaluations),
        tuple(contract for bundle in bundles for contract in bundle.metric_contracts),
    )


def _catalog_from_experiment(value: str) -> ExperimentCatalog:
    path = _absolute_canonical_paths((value,), "pathlight-experiment.json")[0]
    return ExperimentCatalog.build((read_experiment_bundle(path),))


def _diagnosis_path(value: str) -> Path:
    return _absolute_canonical_paths((value,), "pathlight-diagnosis.json")[0]


def _absolute_canonical_paths(values: Sequence[str], filename: str) -> tuple[Path, ...]:
    if not values:
        raise ValueError("pathlight input is missing")
    paths = tuple(Path(value) for value in values)
    if any(not path.is_absolute() or path.name != filename for path in paths):
        raise ValueError("pathlight input is invalid")
    return paths


def _json_copy(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("pathlight output is invalid")
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise ValueError("pathlight output is invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="asterion pathlight", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    trace = commands.add_parser("trace", add_help=False)
    trace_commands = trace.add_subparsers(
        dest="trace_command", required=True, parser_class=_Parser
    )
    trace_list = trace_commands.add_parser("list", add_help=False)
    _add_evidence_file(trace_list)
    trace_list.add_argument("--status")
    trace_list.add_argument("--kind")
    trace_list.add_argument("--component-sha256")
    trace_show = trace_commands.add_parser("show", add_help=False)
    _add_evidence_file(trace_show)
    trace_show.add_argument("--trace-id", required=True)
    trace_tail = trace_commands.add_parser("tail", add_help=False)
    _add_evidence_file(trace_tail)
    trace_tail.add_argument("--trace-id", required=True)
    trace_tail.add_argument("--after-sequence", type=int, default=0)
    trace_flow = trace_commands.add_parser("flow", add_help=False)
    _add_evidence_file(trace_flow)
    trace_flow.add_argument("--trace-id", required=True)

    metrics = commands.add_parser("metrics", add_help=False)
    metric_commands = metrics.add_subparsers(
        dest="metric_command", required=True, parser_class=_Parser
    )
    metric_query = metric_commands.add_parser("query", add_help=False)
    _add_evaluation_file(metric_query)
    metric_query.add_argument("--metric-name")
    metric_query.add_argument("--status")
    metric_query.add_argument("--trace-sha256")
    metric_query.add_argument("--metric-contract-sha256")
    metric_query.add_argument("--dataset-snapshot-sha256")
    metric_query.add_argument("--scope-sha256")

    evaluate = commands.add_parser("evaluate", add_help=False)
    evaluate_commands = evaluate.add_subparsers(
        dest="evaluate_command", required=True, parser_class=_Parser
    )
    compare = evaluate_commands.add_parser("compare", add_help=False)
    _add_evaluation_file(compare)
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)

    experiment = commands.add_parser("experiment", add_help=False)
    experiment_commands = experiment.add_subparsers(
        dest="experiment_command", required=True, parser_class=_Parser
    )
    experiment_show = experiment_commands.add_parser("show", add_help=False)
    _add_experiment_file(experiment_show)
    experiment_show.add_argument("--experiment-sha256", required=True)
    experiment_trials = experiment_commands.add_parser("trials", add_help=False)
    _add_experiment_file(experiment_trials)
    experiment_trials.add_argument("--experiment-sha256", required=True)
    experiment_trials.add_argument("--evidence-state")
    diagnosis = commands.add_parser("diagnosis", add_help=False)
    diagnosis_commands = diagnosis.add_subparsers(
        dest="diagnosis_command", required=True, parser_class=_Parser
    )
    diagnosis_show = diagnosis_commands.add_parser("show", add_help=False)
    _add_diagnosis_file(diagnosis_show)

    proposal = commands.add_parser("proposal", add_help=False)
    proposal_commands = proposal.add_subparsers(
        dest="proposal_command", required=True, parser_class=_Parser
    )
    proposal_list = proposal_commands.add_parser("list", add_help=False)
    _add_diagnosis_file(proposal_list)
    return parser


def _add_evidence_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-file", action="append", required=True)


def _add_evaluation_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evaluation-file", action="append", required=True)


def _add_experiment_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--experiment-file", required=True)


def _add_diagnosis_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--diagnosis-file", required=True)
