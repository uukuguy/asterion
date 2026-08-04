"""Provider-free read-only Pathlight command line."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from asterion.pathlight import (
    DashboardSnapshot,
    MetricFilter,
    PathlightCatalog,
    ProposalCandidate,
    TraceFilter,
    map_opik_exports,
    project_trace_flow,
    read_export_batch,
    read_diagnosis_bundle,
    read_evaluation_bundle,
    trace_graph_from_mapping,
    serve_dashboard,
    validate_external_observation,
    validate_dashboard_bind,
    write_export_batch,
)
from asterion.pathlight._private_file import read_private_file, write_private_file
from asterion.pathlight.experiment import ExperimentCatalog, read_experiment_bundle
from asterion.workflow_evidence import read_workflow_observation_bundle


_ERROR = "asterion pathlight: request is invalid\n"
_WORKFLOW_EVIDENCE_BASENAMES = frozenset(
    {
        "workflow-evidence.json",
        "workflow-evidence.provider-calls.offline.json",
    }
)


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
        result = _execute(args, stdout=stdout)
        stdout.write(
            json.dumps(_json_copy(result), sort_keys=True, separators=(",", ":")) + "\n"
        )
        return 0
    except Exception:
        stderr.write(_ERROR)
        return 2


def _execute(args: argparse.Namespace, *, stdout: TextIO) -> object:
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
            for proposal in read_diagnosis_bundle(
                _diagnosis_path(args.diagnosis_file)
            ).proposals
        ]
    if args.command == "dashboard":
        validate_dashboard_bind(args.host, args.port)
        snapshot = DashboardSnapshot.build(
            workflow_bundles=tuple(
                read_workflow_observation_bundle(path)
                for path in _optional_workflow_evidence_paths(args.evidence_file or ())
            ),
            evaluation_bundles=tuple(
                read_evaluation_bundle(path)
                for path in _optional_absolute_paths(
                    args.evaluation_file or (), "pathlight-evaluations.json"
                )
            ),
            experiment_bundles=tuple(
                read_experiment_bundle(path)
                for path in _optional_absolute_paths(
                    args.experiment_file or (), "pathlight-experiment.json"
                )
            ),
            diagnosis_bundles=tuple(
                read_diagnosis_bundle(path)
                for path in _optional_absolute_paths(
                    args.diagnosis_file or (), "pathlight-diagnosis.json"
                )
            ),
        )

        def ready(url: str) -> None:
            stdout.write(
                json.dumps(
                    {
                        "snapshot_sha256": snapshot.snapshot_sha256,
                        "status": "serving",
                        "url": url,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            stdout.flush()

        serve_dashboard(
            snapshot,
            host=args.host,
            port=args.port,
            open_browser=args.open,
            on_ready=ready,
        )
        return {
            "snapshot_sha256": snapshot.snapshot_sha256,
            "status": "stopped",
            "network_operation_count": 0,
        }
    if args.command == "export":
        if args.export_command == "opik":
            traces = []
            for value in args.evidence_file or ():
                bundle = read_workflow_observation_bundle(
                    _absolute_workflow_evidence_paths((value,))[0]
                )
                for trace in bundle.pathlight_traces:
                    detached = _json_copy(trace)
                    if not isinstance(detached, Mapping):
                        raise ValueError("pathlight input is invalid")
                    traces.append(trace_graph_from_mapping(detached))
            experiments = tuple(
                read_experiment_bundle(path)
                for path in _optional_absolute_paths(
                    args.experiment_file or (), "pathlight-experiment.json"
                )
            )
            evaluations = tuple(
                read_evaluation_bundle(path)
                for path in _optional_absolute_paths(
                    args.evaluation_file or (), "pathlight-evaluations.json"
                )
            )
            diagnoses = tuple(
                read_diagnosis_bundle(path)
                for path in _optional_absolute_paths(
                    args.diagnosis_file or (), "pathlight-diagnosis.json"
                )
            )
            if not any((traces, experiments, evaluations, diagnoses)):
                raise ValueError("Pathlight export input is missing")
            batch = write_export_batch(
                _absolute_root(args.queue_root),
                map_opik_exports(
                    traces=tuple(traces),
                    experiments=experiments,
                    evaluations=evaluations,
                    diagnoses=diagnoses,
                ),
            )
            return {
                "batch_sha256": batch.batch_sha256,
                "envelope_count": len(batch.envelopes),
                "mapping_version": "1.0.0",
                "network_operation_count": 0,
            }
        if args.export_command == "inspect":
            return read_export_batch(_absolute_batch_path(args.batch_file)).to_mapping()
    if args.command == "import":
        if args.import_command == "opik-observation":
            source = _absolute_canonical_paths(
                (args.observation_file,), "pathlight-external-observation.json"
            )[0]
            raw = read_private_file(source, 1_000_000)
            observation = validate_external_observation(json.loads(raw))
            if observation.connector != "opik":
                raise ValueError("Pathlight observation connector is invalid")
            payload = dict(observation.payload)
            required = {
                "change_sha256",
                "scope_sha256",
                "success_criteria_sha256",
                "stop_criteria_sha256",
                "budget_sha256",
                "status",
            }
            if (
                observation.observation_kind != "optimization-suggestion"
                or set(payload) != required
                or payload["status"] != "proposed"
            ):
                raise ValueError("Pathlight observation is not a proposal candidate")
            candidate = ProposalCandidate(
                observation.observation_sha256,
                _sha_payload(payload["change_sha256"]),
                _sha_payload(payload["scope_sha256"]),
                _sha_payload(payload["success_criteria_sha256"]),
                _sha_payload(payload["stop_criteria_sha256"]),
                _sha_payload(payload["budget_sha256"]),
            )
            output_root = _private_output_root(args.output_root)
            _write_idempotent_private(
                output_root
                / f"external-observation-{observation.observation_sha256}.json",
                observation.to_mapping(),
            )
            _write_idempotent_private(
                output_root
                / f"proposal-candidate-{candidate.proposal_candidate_sha256}.json",
                candidate.to_mapping(),
            )
            return {
                "external_observation_sha256": observation.observation_sha256,
                "proposal_candidate_sha256": candidate.proposal_candidate_sha256,
                "execution_authorized": False,
                "network_operation_count": 0,
            }
    raise ValueError("invalid pathlight command")


def _catalog_from_evidence(values: Sequence[str]) -> PathlightCatalog:
    paths = _absolute_workflow_evidence_paths(values)
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


def _absolute_root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path != path.resolve():
        raise ValueError("pathlight root is invalid")
    return path


def _absolute_batch_path(value: str) -> Path:
    path = Path(value)
    if (
        not path.is_absolute()
        or re.fullmatch(r"batch-[0-9a-f]{64}\.json", path.name) is None
    ):
        raise ValueError("pathlight batch path is invalid")
    return path


def _private_output_root(value: str) -> Path:
    root = _absolute_root(value)
    metadata = os.stat(root, follow_symlinks=False)
    if (
        root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError("pathlight output root is invalid")
    return root


def _write_idempotent_private(path: Path, mapping: Mapping[str, object]) -> None:
    encoded = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
    if path.exists() or path.is_symlink():
        if not hmac.compare_digest(read_private_file(path, 1_000_000), encoded):
            raise ValueError("pathlight output conflicts")
        return
    write_private_file(path, encoded)


def _sha_payload(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("pathlight imported digest is invalid")
    return value


def _absolute_canonical_paths(values: Sequence[str], filename: str) -> tuple[Path, ...]:
    if not values:
        raise ValueError("pathlight input is missing")
    paths = tuple(Path(value) for value in values)
    if any(not path.is_absolute() or path.name != filename for path in paths):
        raise ValueError("pathlight input is invalid")
    return paths


def _optional_absolute_paths(values: Sequence[str], filename: str) -> tuple[Path, ...]:
    if not values:
        return ()
    return _absolute_canonical_paths(values, filename)


def _absolute_workflow_evidence_paths(values: Sequence[str]) -> tuple[Path, ...]:
    if not values:
        raise ValueError("pathlight input is missing")
    paths = tuple(Path(value) for value in values)
    if any(
        not path.is_absolute() or path.name not in _WORKFLOW_EVIDENCE_BASENAMES
        for path in paths
    ):
        raise ValueError("pathlight input is invalid")
    return paths


def _optional_workflow_evidence_paths(values: Sequence[str]) -> tuple[Path, ...]:
    if not values:
        return ()
    return _absolute_workflow_evidence_paths(values)


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
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_Parser
    )
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

    dashboard = commands.add_parser("dashboard", add_help=True)
    dashboard.add_argument("--evidence-file", action="append")
    dashboard.add_argument("--evaluation-file", action="append")
    dashboard.add_argument("--experiment-file", action="append")
    dashboard.add_argument("--diagnosis-file", action="append")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--open", action="store_true")

    export = commands.add_parser("export", add_help=False)
    export_commands = export.add_subparsers(
        dest="export_command", required=True, parser_class=_Parser
    )
    export_opik = export_commands.add_parser("opik", add_help=False)
    export_opik.add_argument("--evidence-file", action="append")
    export_opik.add_argument("--experiment-file", action="append")
    export_opik.add_argument("--evaluation-file", action="append")
    export_opik.add_argument("--diagnosis-file", action="append")
    export_opik.add_argument("--queue-root", required=True)
    export_inspect = export_commands.add_parser("inspect", add_help=False)
    export_inspect.add_argument("--batch-file", required=True)

    import_command = commands.add_parser("import", add_help=False)
    import_commands = import_command.add_subparsers(
        dest="import_command", required=True, parser_class=_Parser
    )
    import_opik = import_commands.add_parser("opik-observation", add_help=False)
    import_opik.add_argument("--observation-file", required=True)
    import_opik.add_argument("--output-root", required=True)
    return parser


def _add_evidence_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-file", action="append", required=True)


def _add_evaluation_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evaluation-file", action="append", required=True)


def _add_experiment_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--experiment-file", required=True)


def _add_diagnosis_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--diagnosis-file", required=True)
