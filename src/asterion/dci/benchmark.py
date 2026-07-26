"""Bounded, durable batch orchestration for independent Asterion DCI runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from asterion.dci.artifacts import (
    DciArtifactError,
    DciConversationFeatures,
    DciRunLock,
    extra_args_fingerprint,
    validate_completed_run_evidence,
    validate_resumable_run_evidence,
)
from asterion.dci.config import DciPaths, DciRuntimeOptions
from asterion.dci.context_extension import (
    ContextExtensionError,
    resolve_context_extension,
)
from asterion.dci.context_profiles import (
    context_contract_for_source,
    context_policy_identity,
    context_source_identity,
    resolve_context_profile,
)
from asterion.dci.datasets import (
    BenchmarkRow,
    DatasetError,
    canonical_input_identity,
    load_benchmark_rows_bytes,
    load_beir_benchmark_rows_bytes,
    load_bright_benchmark_rows_bytes,
)
from asterion.dci.prompts import (
    PromptContract,
    PromptContractError,
    prompt_contract_sha256,
    resolve_prompt_contract,
)
from asterion.dci.evaluation import (
    _load_reusable_result,
    _valid_transaction_candidate,
    evaluate_run_directory_async,
)
from asterion.dci.experiment_profiles import (
    EXPERIMENT_AUTHORIZATION_SCHEMA,
    ExperimentAuthorizationError,
    ExperimentProfile,
    FullExecutionAuthorization,
    FullExecutionReservation,
    authorized_scope_output_root,
    cancel_full_execution_authorization,
    consumed_full_execution_authorization_snapshot,
    experiment_profiles_sha256,
    fail_full_execution_operation,
    reconcile_full_execution_operation,
    reserve_full_execution_operation,
    resolve_experiment_profile,
)
from asterion.dci.judge import (
    ASTERION_SAFE_JUDGE_CONTRACT,
    JudgeConfig,
    judge_public_identity,
    judge_request_fingerprint,
)
from asterion.dci.paper_benchmarks import (
    canonical_sha256,
    paper_scope_for_profile,
    paper_scope_for_selected_ids,
    published_scope_selected_ids,
    require_af320_executable_scope,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.dci.provenance import dci_complete_implementation_identity
from asterion.dci.analysis import (
    aggregate_results,
    extract_agent_usage_metrics,
    gather_query_metrics,
    write_analysis_artifacts,
)
from asterion.dci.metrics import (
    DEDUPLICATED_NDCG_CONTRACT,
    UPSTREAM_LIST_NDCG_CONTRACT,
    compute_ir_ndcg,
)
from asterion.dci.trajectory_resolution import (
    TrajectoryAnalysisConfig,
    TrajectoryResolutionError,
    analyze_trajectory_resolution,
    public_resolution_projection,
    validate_gold_manifest_bytes,
)
from asterion.dci.run import (
    DciRunError,
    DciRunResult,
    request_from_runtime_options,
    resume_request_from_output_dir,
    run_pi_research,
)

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class DciBenchmarkError(RuntimeError):
    """Safe public error for an invalid or incompatible benchmark."""


class _NativeEvidenceError(RuntimeError):
    """Internal classification for unsafe per-query native evidence."""


class _StaleJudgeResult(RuntimeError):
    """A valid prior result needs evaluation under the current Judge identity."""


_PAPER_IR_ASSUMPTION_LABELS = {
    "upstream-list": (
        "asterion.operator-assumption/paper-ir-duplicate-handling/"
        "upstream-list/v1"
    ),
    "deduplicated": (
        "asterion.operator-assumption/paper-ir-duplicate-handling/"
        "deduplicated/v1"
    ),
}
_PAPER_RESOLUTION_ASSUMPTION_LABELS = {
    "segment_characters": (
        "asterion.operator-assumption/paper-resolution-segment-characters/v1"
    ),
    "read_minimum_evidence_overlap": (
        "asterion.operator-assumption/paper-resolution-read-overlap/v1"
    ),
}


@dataclass(frozen=True)
class BenchmarkRequest:
    dataset: Path
    output_root: Path
    cwd: Path
    judge_config: JudgeConfig
    runtime_options: DciRuntimeOptions
    limit: int | None = None
    mode: str = "qa"
    profile: str | None = None
    corpus: Path | None = None
    corpus_hint: str | None = None
    max_concurrency: int = 1
    max_turns: int | None = None
    system_prompt_file: Path | None = None
    append_system_prompt_file: Path | None = None
    conversation_features: DciConversationFeatures | None = None
    resume_policy: str = "compatible"
    analysis: bool = True
    figures: bool = True
    resolution_registry: Path | None = None
    resolution_segment_characters: int | None = None
    resolution_read_minimum_evidence_overlap: float | None = None
    ablation_row: str | None = None
    full_execution_authorization: FullExecutionAuthorization | None = None
    experiment_scope_id: str | None = None
    paper_ir_duplicate_handling: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedBenchmarkExecution:
    scope_id: str
    request: BenchmarkRequest
    paths: DciPaths


@dataclass(frozen=True)
class BenchmarkResult:
    output_root: Path
    counts: dict[str, int]


def execute_authorized_reproduction(
    *,
    authority: FullExecutionAuthorization,
    profile: ExperimentProfile,
    scope_ids: tuple[str, ...],
    output_root: Path,
    execution_items: tuple[AuthorizedBenchmarkExecution, ...],
) -> dict[str, object]:
    """Run one already-authorized paper reproduction plan in this process."""

    try:
        requested_root = Path(os.path.abspath(os.path.normpath(output_root)))
        if (
            not isinstance(authority, FullExecutionAuthorization)
            or type(profile) is not ExperimentProfile
            or authority.profile_id != profile.profile_id
            or authority.profile_sha256 != profile.identity_sha256
            or tuple(scope_ids) != tuple(authority.authorized_scope_ids)
            or tuple(scope_ids) != tuple(item.scope_id for item in execution_items)
            or len(scope_ids) != len(execution_items)
        ):
            raise DciBenchmarkError("DCI benchmark authorization scope changed")
        expected_digests = tuple(
            dict(zip(profile.scope_ids, profile.selected_ids_sha256, strict=True)).get(
                scope_id, ""
            )
            for scope_id in scope_ids
        )
        if expected_digests != tuple(authority.selected_ids_sha256):
            raise DciBenchmarkError("DCI benchmark authorization scope changed")

        output_identities: list[dict[str, object]] = []
        expected_roots: dict[str, Path] = {}
        for item in execution_items:
            request = item.request
            scope_id = item.scope_id
            try:
                authorized_root = authorized_scope_output_root(authority, scope_id)
            except ExperimentAuthorizationError as error:
                raise DciBenchmarkError(
                    "DCI benchmark authorization scope changed"
                ) from error
            if (
                request.full_execution_authorization is not authority
                or request.experiment_scope_id != scope_id
                or request.profile != profile.profile_id
                or Path(os.path.abspath(os.path.normpath(request.output_root)))
                != authorized_root
                or requested_root not in authorized_root.parents
            ):
                raise DciBenchmarkError("DCI benchmark authorization root changed")
            metadata = authorized_root.stat()
            output_identities.append(
                {
                    "scope_id": scope_id,
                    "output_root_device": metadata.st_dev,
                    "output_root_inode": metadata.st_ino,
                }
            )
            expected_roots[scope_id] = authorized_root

        benchmark_totals: dict[str, int] = {}
        for item in execution_items:
            result = run_benchmark(item.request, paths=item.paths)
            if Path(os.path.abspath(os.path.normpath(result.output_root))) != (
                expected_roots[item.scope_id]
            ):
                raise DciBenchmarkError("DCI benchmark authorization root changed")
            for key, value in result.counts.items():
                if type(value) is int:
                    benchmark_totals[key] = benchmark_totals.get(key, 0) + value
        receipt = consumed_full_execution_authorization_snapshot(authority)
        agent_operations, judge_operations = _receipt_operation_counts(receipt)
    except BaseException:
        try:
            cancel_full_execution_authorization(authority)
        except ExperimentAuthorizationError:
            pass
        raise

    return {
        "schema": "dci.paper-reproduction-result/v1",
        "profile_id": profile.profile_id,
        "profile_sha256": authority.profile_sha256,
        "authorized_scope_ids": list(scope_ids),
        "operation_counts": {
            "agent": agent_operations,
            "judge": judge_operations,
            "total": agent_operations + judge_operations,
            "benchmark_total": benchmark_totals.get("total", 0),
        },
        "outputs": output_identities,
        "receipt": receipt,
    }


def _receipt_operation_counts(receipt: object) -> tuple[int, int]:
    if not isinstance(receipt, dict):
        raise DciBenchmarkError("DCI benchmark authorization receipt is invalid")
    ledger = receipt.get("ledger")
    if not isinstance(ledger, dict):
        raise DciBenchmarkError("DCI benchmark authorization receipt is invalid")
    agent_operations = ledger.get("completed_agent_operations")
    judge_operations = ledger.get("completed_judge_operations")
    if (
        type(agent_operations) is not int
        or agent_operations < 0
        or type(judge_operations) is not int
        or judge_operations < 0
    ):
        raise DciBenchmarkError("DCI benchmark authorization receipt is invalid")
    return agent_operations, judge_operations


@dataclass
class _SnapshotAuthority:
    paths: dict[str, Path]
    fds: tuple[int, ...]

    def close(self) -> None:
        for descriptor in self.fds:
            os.close(descriptor)


@dataclass
class _RowAuthority:
    query: _Directory
    native: _Directory | None = None
    generation: str | None = None

    def bind_native(self, native: _Directory, generation: str) -> None:
        if self.native is not None:
            self.native.close()
        self.native = _Directory(os.dup(native.fd))
        self.generation = generation

    def close(self) -> None:
        if self.native is not None:
            self.native.close()
        self.query.close()


async def run_benchmark_async(
    request: BenchmarkRequest, *, paths: DciPaths
) -> BenchmarkResult:
    """Run one bounded batch while retaining its writer lock until all work drains."""

    authorized_identity = _authorize_paper_execution_before_inputs(request)
    try:
        rows, output_root, config, row_documents, snapshots = _prepare(request)
    except BaseException:
        _cancel_request_authorization(request)
        raise
    try:
        authorized_identity = _consume_paper_execution_after_inputs(
            request,
            output_root,
            authorized_identity,
        )
    except BaseException:
        _cancel_request_authorization(request)
        raise
    expected_identity: tuple[int, int] | None = None
    if authorized_identity is not None:
        authorized_root, device, inode = authorized_identity
        if authorized_root != output_root:
            raise DciBenchmarkError("DCI benchmark authorization root changed")
        expected_identity = (device, inode)
    try:
        lock = _BatchLock.acquire(output_root, expected_identity=expected_identity)
    except BaseException:
        _cancel_request_authorization(request)
        raise
    tasks: list[asyncio.Task[tuple[int, dict[str, object]]]] = []
    results: dict[int, dict[str, object]] = {}
    snapshot_authority: _SnapshotAuthority | None = None
    row_authorities: dict[int, _RowAuthority] = {}
    batch_started = False
    try:
        _preflight_locked(lock, config, row_documents)
        snapshot_authority = _publish_input_snapshots(lock, snapshots)
        lock.write_json("config.json", config)
        _publish_batch_state(lock, "running", {})
        batch_started = True
        row_authorities = {
            index: _RowAuthority(lock.open_query(row.query_id))
            for index, row in enumerate(rows)
        }
        semaphore = asyncio.Semaphore(request.max_concurrency)

        async def worker(index: int, row: BenchmarkRow) -> tuple[int, dict[str, object]]:
            async with semaphore:
                prior_timing = _validate_timing(
                    row_authorities[index].query.read_optional_json("timing.json")
                )
                value = await _run_row(
                    request,
                    paths,
                    lock,
                    row,
                    row_documents[index],
                    snapshot_authority,
                    authority=row_authorities[index],
                    prior_timing=prior_timing,
                )
                return index, value

        tasks = [
            asyncio.create_task(worker(index, row)) for index, row in enumerate(rows)
        ]
        pending: set[asyncio.Task[tuple[int, dict[str, object]]]] = set(tasks)
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                index, value = task.result()
                results[index] = value
            _publish_aggregates(
                lock,
                results,
                request=request,
                paths=paths,
                rows=rows,
                authorities=row_authorities,
                input_snapshots=snapshots,
                resolution_config=config.get("resolution"),
                implementation_sha256=str(config["implementation_sha256"]),
            )
        counts = _counts(results)
        _publish_aggregates(
            lock, results, request=request, paths=paths, rows=rows,
            authorities=row_authorities,
            include_analysis=True,
            input_snapshots=snapshots,
            resolution_config=config.get("resolution"),
            implementation_sha256=str(config["implementation_sha256"]),
        )
        _publish_batch_state(lock, "completed", results)
        return BenchmarkResult(output_root=output_root, counts=counts)
    except asyncio.CancelledError:
        _cancel_request_authorization(request)
        if not batch_started:
            raise
        for task in tasks:
            task.cancel()
        await _drain_tasks(tasks)
        results.update(_drained_task_results(tasks))
        results = _terminal_results(
            lock,
            rows,
            row_documents,
            authorities=row_authorities,
            trusted=results,
            missing_status="not_started",
        )
        _publish_aggregates(
            lock, results, request=request, paths=paths, rows=rows,
            authorities=row_authorities,
            include_analysis=True,
            input_snapshots=snapshots,
            resolution_config=config.get("resolution"),
            implementation_sha256=str(config["implementation_sha256"]),
        )
        _publish_batch_state(lock, "cancelled", results)
        raise
    except BaseException:
        _cancel_request_authorization(request)
        if not batch_started:
            raise
        for task in tasks:
            task.cancel()
        await _drain_tasks(tasks)
        results.update(_drained_task_results(tasks))
        results = _terminal_results(
            lock,
            rows,
            row_documents,
            authorities=row_authorities,
            trusted=results,
            missing_status="not_started",
        )
        _publish_aggregates(
            lock, results, request=request, paths=paths, rows=rows,
            authorities=row_authorities,
            include_analysis=True,
            input_snapshots=snapshots,
            resolution_config=config.get("resolution"),
            implementation_sha256=str(config["implementation_sha256"]),
        )
        _publish_batch_state(lock, "failed", results)
        raise
    finally:
        if snapshot_authority is not None:
            snapshot_authority.close()
        for authority in row_authorities.values():
            authority.close()
        lock.release()


def run_benchmark(request: BenchmarkRequest, *, paths: DciPaths) -> BenchmarkResult:
    """Synchronous compatibility wrapper for command-line callers."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_benchmark_async(request, paths=paths))
    raise DciBenchmarkError("DCI benchmark sync API cannot run inside an event loop")


def _authorize_paper_execution_before_inputs(
    request: BenchmarkRequest,
) -> tuple[Path, int, int] | None:
    """Validate an exact paper capability before reading operator inputs."""

    try:
        paper_scope = paper_scope_for_profile(request.profile)
    except ValueError as error:
        raise DciBenchmarkError("DCI benchmark authorization scope changed") from error
    authorization = request.full_execution_authorization
    bounded_paper_selection = (
        paper_scope is not None
        and authorization is None
        and type(request.limit) is int
        and request.limit == 1
        and request.experiment_scope_id is None
    )
    if authorization is None:
        if request.experiment_scope_id is not None or (
            paper_scope is not None and not bounded_paper_selection
        ):
            raise DciBenchmarkError(
                "DCI benchmark requires full execution authorization"
            )
        return None
    if (
        not isinstance(authorization, FullExecutionAuthorization)
        or not isinstance(request.experiment_scope_id, str)
        or (
            paper_scope is not None
            and request.experiment_scope_id != paper_scope
        )
    ):
        raise DciBenchmarkError("DCI benchmark authorization scope changed")
    scope_id = request.experiment_scope_id
    try:
        resolve_paper_experiment_scope(scope_id)
    except ValueError as error:
        raise DciBenchmarkError("DCI benchmark authorization scope changed") from error

    from asterion.dci.experiment_profiles import (
        ExperimentAuthorizationError,
        _authorized_scope_output_identity,
        authorized_scope_output_root,
    )

    try:
        authorized_root = authorized_scope_output_root(authorization, scope_id)
    except ExperimentAuthorizationError as error:
        raise DciBenchmarkError("DCI benchmark authorization scope changed") from error
    requested_root = Path(
        os.path.abspath(os.path.normpath(request.output_root))
    )
    if requested_root != authorized_root:
        raise DciBenchmarkError("DCI benchmark authorization root changed")
    try:
        return _authorized_scope_output_identity(authorization, scope_id)
    except (ExperimentAuthorizationError, RuntimeError, ValueError) as error:
        raise DciBenchmarkError("DCI benchmark authorization is invalid") from error


def _consume_paper_execution_after_inputs(
    request: BenchmarkRequest,
    output_root: Path,
    expected_identity: tuple[Path, int, int] | None,
) -> tuple[Path, int, int] | None:
    if expected_identity is None:
        return None
    authorization = request.full_execution_authorization
    scope_id = request.experiment_scope_id
    if authorization is None or scope_id is None:
        raise DciBenchmarkError("DCI benchmark authorization is invalid")
    from asterion.dci.experiment_profiles import (
        _consumed_authorized_output_identity,
    )

    try:
        require_af320_executable_scope(scope_id, authorization)
        consumed_identity = _consumed_authorized_output_identity(
            authorization, scope_id
        )
    except (ExperimentAuthorizationError, RuntimeError, ValueError) as error:
        raise DciBenchmarkError("DCI benchmark authorization is invalid") from error
    if consumed_identity != expected_identity or consumed_identity[0] != output_root:
        raise DciBenchmarkError("DCI benchmark authorization root changed")
    return consumed_identity


def _cancel_request_authorization(request: BenchmarkRequest) -> None:
    authorization = request.full_execution_authorization
    if authorization is None:
        return
    try:
        cancel_full_execution_authorization(authorization)
    except ExperimentAuthorizationError:
        pass


def _scan_corpus_content(corpus: Path) -> list[dict[str, object]]:
    root = corpus.absolute()
    _reject_symlink_components(root)
    pending = [root]
    records: list[dict[str, object]] = []
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.is_symlink():
                        raise DciBenchmarkError(
                            "DCI benchmark resolution corpus is invalid"
                        )
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise DciBenchmarkError(
                            "DCI benchmark resolution corpus is invalid"
                        )
                    raw = _read_input_snapshot(path)
                    records.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "size": len(raw),
                        }
                    )
    except DciBenchmarkError:
        raise
    except OSError as error:
        raise DciBenchmarkError(
            "DCI benchmark resolution corpus is invalid"
        ) from error
    return sorted(records, key=lambda item: str(item["path"]))


def _corpus_content_identity(corpus: Path) -> dict[str, object]:
    first = _scan_corpus_content(corpus)
    second = _scan_corpus_content(corpus)
    if first != second:
        raise DciBenchmarkError("DCI benchmark resolution corpus changed")
    return {"sha256": _fingerprint(first), "file_count": len(first)}


def _resolution_parameters(
    request: BenchmarkRequest,
) -> tuple[Path, int, float] | None:
    """Return the complete explicit resolution triple or reject partial input."""

    values = (
        request.resolution_registry,
        request.resolution_segment_characters,
        request.resolution_read_minimum_evidence_overlap,
    )
    if values == (None, None, None):
        return None
    registry_path, segment_characters, overlap = values
    if (
        not isinstance(registry_path, Path)
        or type(segment_characters) is not int
        or segment_characters <= 0
        or type(overlap) not in {int, float}
        or not math.isfinite(float(overlap))
        or not 0.0 < float(overlap) <= 1.0
    ):
        raise DciBenchmarkError("DCI benchmark resolution configuration is invalid")
    return registry_path, segment_characters, float(overlap)


def _resolution_operator_assumptions(
    request: BenchmarkRequest,
) -> dict[str, str] | None:
    """Record explicit paper-unreported resolution choices as operator assumptions."""

    if _resolution_parameters(request) is None or request.profile is None:
        return None
    try:
        profile = _resolve_prompt_profile(
            request.profile,
            provider=request.runtime_options.provider,
            model=request.runtime_options.model,
        )
    except ValueError as error:
        raise DciBenchmarkError("DCI benchmark resolution configuration is invalid") from error
    if profile.source_family != "paper-reference":
        return None
    return dict(_PAPER_RESOLUTION_ASSUMPTION_LABELS)


def _resolution_manifest_paths(
    request: BenchmarkRequest, rows: tuple[BenchmarkRow, ...]
) -> tuple[dict[str, Path], dict[str, object], dict[str, bytes]]:
    parameters = _resolution_parameters(request)
    if parameters is None:
        return {}, {}, {}
    registry_path, segment_characters, overlap = parameters
    operator_assumptions = _resolution_operator_assumptions(request)
    features = request.conversation_features or DciConversationFeatures()
    if (
        request.corpus is None
        or not features.externalize_tool_results
    ):
        raise DciBenchmarkError("DCI benchmark resolution configuration is invalid")
    _reject_symlink_components(registry_path)
    registry_raw = _read_input_snapshot(registry_path)
    try:
        registry = json.loads(registry_raw)
    except (UnicodeError, ValueError) as error:
        raise DciBenchmarkError("DCI benchmark resolution registry is invalid") from error
    if (
        not isinstance(registry, dict)
        or set(registry) != {"schema", "dataset_id", "manifests"}
        or registry.get("schema") != "dci.gold-document-registry/v1"
        or not isinstance(registry.get("dataset_id"), str)
        or not registry["dataset_id"]
        or not isinstance(registry.get("manifests"), list)
    ):
        raise DciBenchmarkError("DCI benchmark resolution registry is invalid")
    expected_ids = {row.query_id for row in rows}
    paths: dict[str, Path] = {}
    identities: dict[str, object] = {}
    snapshots = {"resolution_registry": registry_raw}
    for index, entry in enumerate(registry["manifests"]):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"query_id", "path", "sha256"}
            or not isinstance(entry.get("query_id"), str)
            or entry["query_id"] not in expected_ids
            or entry["query_id"] in paths
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("sha256"), str)
        ):
            raise DciBenchmarkError("DCI benchmark resolution registry is invalid")
        relative = PurePosixPath(entry["path"])
        if (
            relative.is_absolute()
            or entry["path"] != relative.as_posix()
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise DciBenchmarkError("DCI benchmark resolution registry is invalid")
        manifest_path = registry_path.parent.joinpath(*relative.parts)
        _reject_symlink_components(manifest_path)
        manifest_raw = _read_input_snapshot(manifest_path)
        digest = hashlib.sha256(manifest_raw).hexdigest()
        if digest != entry["sha256"]:
            raise DciBenchmarkError("DCI benchmark resolution registry is stale")
        try:
            dataset_id, manifest_query_id, gold_ids = validate_gold_manifest_bytes(
                manifest_raw, corpus_dir=request.corpus
            )
        except TrajectoryResolutionError as error:
            raise DciBenchmarkError("DCI benchmark resolution manifest is invalid") from error
        row = next(row for row in rows if row.query_id == entry["query_id"])
        if dataset_id != registry["dataset_id"] or manifest_query_id != row.query_id or (
            row.gold_ids is not None and set(gold_ids) != set(row.gold_ids)
        ):
            raise DciBenchmarkError("DCI benchmark resolution manifest is incompatible")
        paths[row.query_id] = manifest_path
        snapshot_key = f"resolution_manifest_{index:04d}"
        identities[row.query_id] = {
            "identity": str(canonical_input_identity(manifest_path)),
            "sha256": digest,
            "snapshot_key": snapshot_key,
        }
        snapshots[snapshot_key] = manifest_raw
    if set(paths) != expected_ids:
        raise DciBenchmarkError("DCI benchmark resolution registry is incomplete")
    return (
        paths,
        {
            "schema": "dci.trajectory-analysis-config/v1",
            "dataset_id": registry["dataset_id"],
            "corpus": _corpus_content_identity(request.corpus),
            "parameter_source": "asterion-defined",
            "segment_characters": segment_characters,
            "alignment_version": "dci.paper-alignment/v1",
            "read_minimum_evidence_overlap": overlap,
            "registry": {
                "identity": str(canonical_input_identity(registry_path)),
                "sha256": hashlib.sha256(registry_raw).hexdigest(),
            },
            "manifests": identities,
            **(
                {"operator_assumptions": operator_assumptions}
                if operator_assumptions is not None
                else {}
            ),
        },
        snapshots,
    )


def _prepare(
    request: BenchmarkRequest,
) -> tuple[
    tuple[BenchmarkRow, ...],
    Path,
    dict[str, object],
    tuple[dict[str, object], ...],
    dict[str, bytes],
]:
    _resolution_parameters(request)
    if request.mode not in {"qa", "ir"}:
        raise DciBenchmarkError("DCI benchmark mode is invalid")
    for value, label in (
        (request.max_concurrency, "concurrency"),
        (request.max_turns, "max turns"),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise DciBenchmarkError(f"DCI benchmark {label} is invalid")
    if request.limit is not None and (
        isinstance(request.limit, bool)
        or not isinstance(request.limit, int)
        or request.limit < 1
    ):
        raise DciBenchmarkError("DCI benchmark limit is invalid")
    if request.resume_policy not in {"compatible", "fresh", "reuse"}:
        raise DciBenchmarkError("DCI benchmark resume policy is invalid")
    if request.figures and not request.analysis:
        raise DciBenchmarkError("DCI benchmark figures require analysis")
    ranking_metric_contract = _metric_contract_for_request(request)
    paper_ir_duplicate_handling_assumption = (
        _paper_ir_assumption_label_for_request(request)
    )
    paper_resolution_assumptions = _resolution_operator_assumptions(request)
    prompt_contract, prompt_contract_sha256_value = _prompt_contract_for_request(
        request
    )
    ablation_identity: dict[str, object] | None = None
    if request.ablation_row is not None:
        from asterion.dci.ablation import (
            bounded_ablation_input_paths,
            bounded_ablation_resolution_registry_path,
            paper_ablation_matrix_sha256,
            require_af320_executable_ablation,
        )

        try:
            ablation = require_af320_executable_ablation(
                request.ablation_row, benchmark_authorized=True
            )
            expected_dataset, expected_corpus = bounded_ablation_input_paths(
                ablation.row_id
            )
            expected_registry = bounded_ablation_resolution_registry_path()
        except (RuntimeError, ValueError) as error:
            raise DciBenchmarkError("DCI benchmark ablation row is invalid") from error
        if (
            canonical_input_identity(request.dataset)
            != canonical_input_identity(expected_dataset)
            or request.corpus is None
            or canonical_input_identity(request.corpus)
            != canonical_input_identity(expected_corpus)
            or canonical_input_identity(request.cwd)
            != canonical_input_identity(expected_corpus)
            or request.mode != "qa"
            or request.runtime_options.tools != ",".join(ablation.tools)
            or request.runtime_options.runtime_context_level
            != ablation.context_profile
            or request.max_turns != ablation.max_turns
            or request.conversation_features is None
            or not request.conversation_features.externalize_tool_results
            or request.resolution_registry is None
            or canonical_input_identity(request.resolution_registry)
            != canonical_input_identity(expected_registry)
            or request.resolution_segment_characters != ablation.segment_characters
            or request.resolution_read_minimum_evidence_overlap
            != ablation.read_minimum_evidence_overlap
        ):
            raise DciBenchmarkError("DCI benchmark ablation row is invalid")
        ablation_identity = {
            "schema": "dci.paper-ablation-selection/v1",
            "row_id": ablation.row_id,
            "row_sha256": ablation.identity_sha256,
            "matrix_sha256": paper_ablation_matrix_sha256(),
        }
    paper_authorization_identity: dict[str, object] | None = None
    paper_scope = paper_scope_for_profile(request.profile)
    if request.full_execution_authorization is not None:
        authorization = request.full_execution_authorization
        if not isinstance(authorization, FullExecutionAuthorization):
            raise DciBenchmarkError("DCI benchmark requires AF-340 authorization")
        paper_authorization_identity = {
            "schema": EXPERIMENT_AUTHORIZATION_SCHEMA,
            "profile_id": authorization.profile_id,
            "profile_identity_sha256": authorization.profile_sha256,
            "experiment_profiles_sha256": experiment_profiles_sha256(),
            "paper_benchmark_inventory_sha256": authorization.dataset_inventory_sha256,
            "paper_experiment_scopes_sha256": authorization.experiment_scopes_sha256,
            "estimated_budget_usd": authorization.estimated_budget_usd,
        }
    bounded_paper_selection = (
        paper_scope is not None
        and request.full_execution_authorization is None
        and type(request.limit) is int
        and request.limit == 1
        and request.experiment_scope_id is None
    )
    if (
        paper_scope is not None
        and request.full_execution_authorization is None
        and not bounded_paper_selection
    ):
        raise DciBenchmarkError("DCI benchmark requires full execution authorization")
    try:
        dataset_raw = _read_input_snapshot(request.dataset)
        beir_scope = {
            "beir.arguana": "beir.arguana.main.random50",
            "beir.scifact": "beir.scifact.main.random50",
        }.get(request.profile)
        bright_benchmark = None
        if paper_scope is not None:
            candidate = resolve_paper_benchmark(
                resolve_paper_experiment_scope(paper_scope).dataset_id
            )
            if candidate.dataset_id.startswith("bright."):
                bright_benchmark = candidate
        if bright_benchmark is not None:
            rows = load_bright_benchmark_rows_bytes(
                dataset_raw, expected_count=bright_benchmark.source_count
            )
        elif beir_scope is None:
            try:
                rows = load_benchmark_rows_bytes(dataset_raw)
            except DatasetError as generic_error:
                try:
                    rows = load_beir_benchmark_rows_bytes(dataset_raw)
                except DatasetError:
                    raise generic_error
        else:
            rows = load_beir_benchmark_rows_bytes(dataset_raw, expected_count=50)
            if tuple(sorted(row.query_id for row in rows)) != published_scope_selected_ids(
                beir_scope
            ):
                raise DatasetError("DCI BEIR selected-ID manifest does not match")
    except DatasetError as error:
        raise DciBenchmarkError("DCI benchmark dataset is invalid") from error
    source_scope = _paper_scope_for_rows(rows)
    if paper_scope is not None and source_scope != paper_scope:
        raise DciBenchmarkError("DCI benchmark paper scope does not match its profile")
    if request.limit is not None:
        rows = rows[: request.limit]
    selected_scope = _paper_scope_for_rows(rows)
    authorized_scope = paper_scope or source_scope or selected_scope
    bounded_paper_selection = (
        request.full_execution_authorization is None
        and type(request.limit) is int
        and request.limit == 1
        and request.experiment_scope_id is None
        and (paper_scope is not None or source_scope is not None)
    )
    if (
        request.full_execution_authorization is not None
        and request.experiment_scope_id != authorized_scope
    ):
        raise DciBenchmarkError("DCI benchmark authorization scope changed")
    if request.full_execution_authorization is not None:
        if authorized_scope is None:
            raise DciBenchmarkError("DCI benchmark authorization scope changed")
        from asterion.dci.experiment_profiles import (
            _authorized_scope_selection_identity,
        )

        try:
            authorized_selection_sha256, authorized_selection_count = (
                _authorized_scope_selection_identity(
                    request.full_execution_authorization,
                    authorized_scope,
                )
            )
        except (ExperimentAuthorizationError, RuntimeError, TypeError, ValueError) as error:
            raise DciBenchmarkError(
                "DCI benchmark authorization selection changed"
            ) from error
        bounded_selected_ids_sha256 = canonical_sha256(
            tuple(sorted(row.query_id for row in rows))
        )
        if (
            bounded_selected_ids_sha256 != authorized_selection_sha256
            or len(rows) != authorized_selection_count
            or (
                request.limit is not None
                and authorized_selection_count != request.limit
            )
        ):
            raise DciBenchmarkError(
                "DCI benchmark authorization selection changed"
            )
    if any((row.is_ir if request.mode == "qa" else not row.is_ir) for row in rows):
        raise DciBenchmarkError("DCI benchmark dataset does not match its mode")
    _resolution_paths, resolution_config, resolution_snapshots = (
        _resolution_manifest_paths(request, rows)
    )
    output_root = Path(os.path.abspath(os.path.normpath(request.output_root)))
    _reject_symlink_components(output_root)
    if (
        authorized_scope is not None
        and not bounded_paper_selection
        and request.full_execution_authorization is None
    ):
        raise DciBenchmarkError("DCI benchmark requires full execution authorization")
    if (
        paper_scope is not None
        and not bounded_paper_selection
        and selected_scope != paper_scope
    ):
        raise DciBenchmarkError("DCI benchmark paper scope does not match its profile")
    corpus_identity = (
        str(canonical_input_identity(request.corpus)) if request.corpus else None
    )
    context_contract: str | None = None
    selected_profile: ExperimentProfile | None = None
    if request.profile is not None:
        try:
            selected_profile = _resolve_prompt_profile(
                request.profile,
                provider=request.runtime_options.provider,
                model=request.runtime_options.model,
            )
            context_contract = selected_profile.context_contract
            if (
                request.ablation_row is not None
                and request.runtime_options.runtime_context_level is not None
            ):
                context_contract = context_contract_for_source(
                    selected_profile.source_family,
                    request.runtime_options.runtime_context_level,
                )
        except ValueError as error:
            raise DciBenchmarkError(
                "DCI benchmark context policy is invalid"
            ) from error
    corpus_contract = selected_profile.corpus_identity if selected_profile else None
    corpus_content_identity = (
        _batch_corpus_content_identity(request.corpus, corpus_contract)
        if request.corpus is not None and corpus_contract is not None
        else None
    )
    runtime = _runtime_document(
        request.runtime_options,
        context_contract=context_contract,
    )
    judge_contract = _judge_contract_for_request(request)
    judge = judge_public_identity(
        request.judge_config, contract_id=judge_contract
    )
    judge_fingerprint = _fingerprint(judge)
    implementation_sha256 = dci_complete_implementation_identity()
    dataset_identity = canonical_input_identity(request.dataset)
    dataset_digest = hashlib.sha256(dataset_raw).hexdigest()
    snapshots: dict[str, bytes] = {}
    snapshots.update(resolution_snapshots)
    prompt_resources: dict[str, object] = {}
    for name in ("system_prompt_file", "append_system_prompt_file"):
        path = getattr(request, name)
        if path is None:
            prompt_resources[name] = None
            continue
        raw = _read_input_snapshot(path)
        snapshots[name] = raw
        prompt_resources[name] = {
            "identity": str(canonical_input_identity(path)),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    config: dict[str, object] = {
        "schema": "asterion.dci.batch/v1",
        "run_id": f"batch-{dataset_digest[:16]}",
        "product": "asterion-dci",
        "dataset": {"identity": str(dataset_identity), "sha256": dataset_digest},
        "mode": request.mode,
        "profile": request.profile,
        "corpus_identity": corpus_identity,
        "corpus_contract": corpus_contract,
        "corpus_content_identity": corpus_content_identity,
        "corpus_hint": request.corpus_hint,
        "runtime_contract": (
            selected_profile.runtime_contract if selected_profile is not None else None
        ),
        "context_contract": context_contract,
        "cwd": str(canonical_input_identity(request.cwd)),
        "runtime": runtime,
        "conversation_features": (
            request.conversation_features.to_mapping()
            if request.conversation_features is not None
            else DciConversationFeatures().to_mapping()
        ),
        "max_concurrency": request.max_concurrency,
        "max_turns": request.max_turns,
        "analysis": request.analysis,
        "figures": request.figures,
        "judge": judge,
        "judge_configuration_fingerprint": judge_fingerprint,
        "ranking_metric_contract": ranking_metric_contract,
        "paper_ir_duplicate_handling_assumption": (
            paper_ir_duplicate_handling_assumption
        ),
        "implementation_sha256": implementation_sha256,
        "benchmark_prompt_contract": prompt_contract.contract_id,
        "benchmark_prompt_contract_sha256": prompt_contract_sha256_value,
        "prompt_resources": prompt_resources,
    }
    if selected_profile is not None:
        config["profile_sha256"] = selected_profile.identity_sha256
        config["source_identity"] = (
            dict(selected_profile.source_identity)
            if isinstance(selected_profile.source_identity, Mapping)
            else selected_profile.source_identity
        )
    dataset_id = (
        resolve_paper_experiment_scope(selected_scope).dataset_id
        if selected_scope is not None
        else "dataset.local"
    )
    config["dataset"] = {
        **config["dataset"],  # type: ignore[arg-type]
        "dataset_id": dataset_id,
    }
    authorized_bounded = (
        authorized_scope is not None
        and request.full_execution_authorization is not None
        and request.limit is not None
    )
    if authorized_bounded:
        authorization = request.full_execution_authorization
        if authorization is None:
            raise DciBenchmarkError("DCI benchmark authorization scope changed")
        selection = {
            "schema": "asterion.dci.selection/v1",
            "execution_class": "paper-bounded-authorized",
            "id": f"limit-{request.limit}",
            "paper_scope": authorized_scope,
            "selected_rows": len(rows),
            "full_dataset": False,
            "comparable": False,
            "authorization_profile": authorization.profile_id,
        }
    elif bounded_paper_selection:
        selection = {
            "schema": "asterion.dci.selection/v1",
            "execution_class": "paper-bounded",
            "id": "limit-1",
            "paper_scope": paper_scope,
            "selected_rows": len(rows),
            "full_dataset": False,
            "comparable": False,
            "authorization_profile": None,
        }
    elif authorized_scope is not None:
        authorization = request.full_execution_authorization
        selection = {
            "schema": "asterion.dci.selection/v1",
            "execution_class": "paper-full-authorized",
            "id": "paper-full",
            "paper_scope": authorized_scope,
            "selected_rows": len(rows),
            "full_dataset": True,
            "comparable": _paper_selection_is_comparable(
                paper_ir_duplicate_handling_assumption,
                paper_resolution_assumptions,
            ),
            "authorization_profile": (
                authorization.profile_id if authorization is not None else None
            ),
        }
    else:
        selection = {
            "schema": "asterion.dci.selection/v1",
            "execution_class": "non-paper",
            "id": "request",
            "paper_scope": None,
            "selected_rows": len(rows),
            "full_dataset": False,
            "comparable": False,
            "authorization_profile": None,
        }
    selection["selected_ids_sha256"] = canonical_sha256(
        tuple(sorted(row.query_id for row in rows))
    )
    config["selection"] = selection
    if resolution_config:
        config["resolution"] = resolution_config
    if ablation_identity is not None:
        config["ablation"] = ablation_identity
    if paper_authorization_identity is not None:
        config["paper_full_authorization"] = paper_authorization_identity
    config["product_effective_config_sha256"] = canonical_sha256(
        {
            "product": config["product"],
            "runtime": config["runtime"],
            "prompt": config["benchmark_prompt_contract_sha256"],
            "judge": config["judge_configuration_fingerprint"],
            "corpus_identity": config["corpus_identity"],
            "corpus_contract": config["corpus_contract"],
            "corpus_content_identity": config["corpus_content_identity"],
            "runtime_contract": config["runtime_contract"],
            "context_contract": config["context_contract"],
        }
    )
    config["run_fingerprint"] = _fingerprint(
        {
            key: value
            for key, value in config.items()
            if key
            not in {
                "judge",
                "judge_configuration_fingerprint",
                "product_effective_config_sha256",
            }
        }
    )
    config["batch_fingerprint"] = _fingerprint(config)
    documents: list[dict[str, object]] = []
    for row in rows:
        prompt = _prompt(request, row, prompt_contract)
        identity: dict[str, object] = {
            "schema": "asterion.dci.batch-row/v1",
            "row": row.as_dict(),
            "mode": request.mode,
            "profile": request.profile,
            "prompt": prompt,
            "corpus_identity": corpus_identity,
            "corpus_hint": request.corpus_hint,
            "cwd": config["cwd"],
            "runtime": runtime,
            "conversation_features": config["conversation_features"],
            "max_turns": request.max_turns,
            "benchmark_prompt_contract": prompt_contract.contract_id,
            "benchmark_prompt_contract_sha256": prompt_contract_sha256_value,
            "ranking_metric_contract": ranking_metric_contract,
            "paper_ir_duplicate_handling_assumption": (
                paper_ir_duplicate_handling_assumption
            ),
            "prompt_resources": config["prompt_resources"],
            "implementation_sha256": implementation_sha256,
        }
        if resolution_config:
            identity["resolution"] = resolution_config.get("manifests", {}).get(
                row.query_id
            )
        if ablation_identity is not None:
            identity["ablation"] = ablation_identity
        if paper_authorization_identity is not None:
            identity["paper_full_authorization"] = paper_authorization_identity
        documents.append(
            {
                "schema": "asterion.dci.batch-item/v1",
                "query_id": row.query_id,
                "input": row.as_dict(),
                "prompt": prompt,
                "identity": identity,
                "row_fingerprint": _fingerprint(identity),
                "judge_configuration_fingerprint": judge_fingerprint,
                "implementation_sha256": implementation_sha256,
            }
        )
    return rows, output_root, config, tuple(documents), snapshots


def _paper_scope_for_rows(rows: tuple[BenchmarkRow, ...]) -> str | None:
    return paper_scope_for_selected_ids(
        tuple(row.query_id for row in rows)
    )


def _batch_corpus_content_identity(path: Path, contract: str) -> dict[str, object]:
    root = Path(os.path.abspath(os.path.normpath(path)))
    _reject_symlink_components(root)
    if not root.is_dir():
        raise DciBenchmarkError("DCI benchmark corpus identity is invalid")
    files: list[dict[str, str]] = []
    try:
        for directory, directories, filenames in os.walk(root, followlinks=False):
            current = Path(directory)
            for dirname in tuple(directories):
                if (current / dirname).is_symlink():
                    raise DciBenchmarkError("DCI benchmark corpus identity is invalid")
            directories.sort()
            for filename in sorted(filenames):
                file_path = current / filename
                if file_path.is_symlink() or not file_path.is_file():
                    raise DciBenchmarkError("DCI benchmark corpus identity is invalid")
                relative = file_path.relative_to(root).as_posix()
                files.append(
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                    }
                )
    except OSError as error:
        raise DciBenchmarkError("DCI benchmark corpus identity is invalid") from error
    return {
        "schema": "asterion.dci.corpus-content/v1",
        "contract": contract,
        "file_count": len(files),
        "sha256": canonical_sha256(files),
    }


async def _run_row(
    request: BenchmarkRequest,
    paths: DciPaths,
    lock: _BatchLock,
    row: BenchmarkRow,
    item: dict[str, object],
    snapshots: _SnapshotAuthority,
    *,
    authority: _RowAuthority,
    prior_timing: dict[str, Any] | None,
) -> dict[str, object]:
    query = authority.query
    prompt_contract, _prompt_contract_sha256_value = _prompt_contract_for_request(
        request
    )
    agent_started_at: str | None = None
    agent_finished_at: str | None = None
    agent_operation_performed = False
    judge_operation_performed = False
    agent_operation_cost_usd = 0.0
    judge_operation_cost_usd = 0.0
    try:
        existing_item = query.read_optional_json("item.json")
        if existing_item is not None:
            _validate_item_document(existing_item)
            if not _same_run_item(existing_item, item):
                raise DciBenchmarkError("DCI benchmark row is incompatible")
        query.write_json("item.json", item)
        query.write_text("input_question.txt", str(item["prompt"]))
        existing = query.read_optional_json("result.json")
        generation = _result_generation(existing) or _latest_generation(query)

        if existing is not None and existing.get("status") != "completed":
            _validate_terminal_result(existing, item)

        if (
            request.resume_policy != "fresh"
            and existing is not None
            and existing.get("status") == "completed"
        ):
            _validate_result_shape(existing, item, request.mode)
            native = query.open_existing_query(str(existing["native_generation"]))
            if native is None:
                raise DciBenchmarkError("DCI benchmark result evidence is invalid")
            try:
                authority.bind_native(native, str(existing["native_generation"]))
                try:
                    _validate_exact_reuse(
                        native,
                        existing,
                        item,
                        row,
                        request,
                        query_path=lock.path / row.query_id,
                    )
                except _StaleJudgeResult:
                    pass
                else:
                    reused = {
                        **existing,
                        "agent_operation_performed": False,
                        "judge_operation_performed": False,
                        "agent_operation_cost_usd": 0.0,
                        "judge_operation_cost_usd": 0.0,
                    }
                    query.write_json("result.json", reused)
                    _write_query_timing(
                        query,
                        reused,
                        prior_timing=prior_timing,
                        started_at=None,
                        finished_at=None,
                    )
                    return reused
            finally:
                native.close()

        if request.resume_policy == "reuse":
            result = _failed_result(
                row.query_id,
                item["row_fingerprint"],
                "failed",
                implementation_sha256=item["implementation_sha256"],
                ranking_metric_contract=item["identity"]["ranking_metric_contract"],
                paper_ir_duplicate_handling_assumption=item["identity"][
                    "paper_ir_duplicate_handling_assumption"
                ],
                native_generation=authority.generation,
                native_evidence_available=False,
            )
            query.write_json("result.json", result)
            _write_query_timing(
                query,
                result,
                prior_timing=prior_timing,
                started_at=None,
                finished_at=None,
            )
            return result

        if request.resume_policy == "fresh" or generation is None:
            generation = _next_generation(query)
            native_authority = query.open_query(generation)
            native_state = "missing"
        else:
            native_authority = query.open_existing_query(generation)
            if native_authority is None:
                raise DciBenchmarkError("DCI benchmark native evidence is invalid")
            native_state = _native_state(native_authority, lock.path / row.query_id / generation)
        authority.bind_native(native_authority, generation)
        native_dir = lock.path / row.query_id / generation
        try:
            if native_state == "malformed":
                result = _failed_result(
                    row.query_id,
                    item["row_fingerprint"],
                    "failed",
                    implementation_sha256=item["implementation_sha256"],
                    ranking_metric_contract=item["identity"]["ranking_metric_contract"],
                    paper_ir_duplicate_handling_assumption=item["identity"][
                        "paper_ir_duplicate_handling_assumption"
                    ],
                    native_generation=generation,
                    native_evidence_available=False,
                )
                query.write_json("result.json", result)
                return result
            if native_state != "completed":
                native_request = request_from_runtime_options(
                    request.runtime_options,
                    run_id=row.query_id,
                    question=str(item["prompt"]),
                    cwd=canonical_input_identity(request.cwd),
                    stream_text=False,
                    final_answer_recovery=prompt_contract.final_answer_recovery,
                )
                native_request = replace(
                    native_request,
                    max_turns=request.max_turns,
                    system_prompt_file=request.system_prompt_file,
                    append_system_prompt_file=request.append_system_prompt_file,
                    conversation_features=request.conversation_features,
                )
                if native_state in {"failed", "incomplete", "running"}:
                    native_request = replace(
                        resume_request_from_output_dir(
                            native_dir,
                            extra_args=request.runtime_options.extra_args,
                            _directory_fd=native_authority.fd,
                        ),
                        final_answer_recovery=prompt_contract.final_answer_recovery,
                    )
                agent_started_at = _utc_now()
                agent_reservation = _reserve_authorized_operation(request, "agent")
                try:
                    try:
                        agent_operation_performed = True
                        await _run_pi_async(
                            paths,
                            native_request,
                            output_dir=native_dir,
                            output_directory_fd=native_authority.fd,
                            resource_fds=snapshots.fds,
                            system_prompt_override=snapshots.paths.get(
                                "system_prompt_file"
                            ),
                            append_system_prompt_override=snapshots.paths.get(
                                "append_system_prompt_file"
                            ),
                        )
                        if agent_reservation is not None:
                            actual_cost = _validated_agent_cost(
                                native_authority, native_dir
                            )
                            agent_operation_cost_usd = actual_cost
                            _reconcile_authorized_operation(
                                request, agent_reservation, actual_cost
                            )
                    except BaseException:
                        _fail_authorized_operation(request, agent_reservation)
                        raise
                finally:
                    agent_finished_at = _utc_now()
            result: dict[str, object] = {
                "schema": "asterion.dci.batch-result/v1",
                "query_id": row.query_id,
                "row_fingerprint": item["row_fingerprint"],
                "implementation_sha256": item["implementation_sha256"],
                "ranking_metric_contract": item["identity"]["ranking_metric_contract"],
                "paper_ir_duplicate_handling_assumption": item["identity"][
                    "paper_ir_duplicate_handling_assumption"
                ],
                "status": "completed",
                "mode": request.mode,
                "native_generation": generation,
                "agent_operation_performed": agent_operation_performed,
                "judge_operation_performed": judge_operation_performed,
                "agent_operation_cost_usd": agent_operation_cost_usd,
                "judge_operation_cost_usd": judge_operation_cost_usd,
            }
            if request.mode == "qa":
                assert row.answer is not None
                verdict = _reusable_judge_verdict(
                    native_authority,
                    native_dir,
                    row,
                    request,
                )
                if verdict is None:
                    judge_reservation = _reserve_authorized_operation(
                        request, "judge"
                    )
                    try:
                        judge_operation_performed = True
                        verdict = await evaluate_run_directory_async(
                            native_dir,
                            gold_answer=_qa_gold_answer(row),
                            judge_config=request.judge_config,
                            judge_contract=_judge_contract_for_request(request),
                            _directory_fd=native_authority.fd,
                        )
                        actual_cost = _validated_judge_cost(verdict)
                        judge_operation_cost_usd = actual_cost
                        if judge_reservation is not None:
                            _reconcile_authorized_operation(
                                request, judge_reservation, actual_cost
                            )
                    except BaseException:
                        _fail_authorized_operation(request, judge_reservation)
                        raise
                result["is_correct"] = verdict["is_correct"]
                result["judge_configuration_fingerprint"] = item[
                    "judge_configuration_fingerprint"
                ]
                result["judge_request_fingerprint"] = verdict[
                    "judge_request_fingerprint"
                ]
                result["judge_operation_performed"] = judge_operation_performed
                result["judge_operation_cost_usd"] = judge_operation_cost_usd
            result["native_evidence_fingerprint"] = _native_evidence_fingerprint(
                native_authority, request.mode
            )
            query.write_json("result.json", result)
            _write_query_timing(
                query,
                result,
                prior_timing=prior_timing,
                started_at=agent_started_at,
                finished_at=agent_finished_at,
            )
            return result
        finally:
            native_authority.close()
    except asyncio.CancelledError:
        generation, available, evidence_fingerprint = _terminal_native_evidence(
            authority, request, paths
        )
        result = _failed_result(
            row.query_id,
            item["row_fingerprint"],
            "cancelled",
            implementation_sha256=item["implementation_sha256"],
            ranking_metric_contract=item["identity"]["ranking_metric_contract"],
            paper_ir_duplicate_handling_assumption=item["identity"][
                "paper_ir_duplicate_handling_assumption"
            ],
            native_generation=generation,
            native_evidence_available=available,
            native_evidence_fingerprint=evidence_fingerprint,
            agent_operation_performed=agent_operation_performed,
            judge_operation_performed=judge_operation_performed,
            agent_operation_cost_usd=agent_operation_cost_usd,
            judge_operation_cost_usd=judge_operation_cost_usd,
        )
        query.write_json("result.json", result)
        raise
    except DciBenchmarkError:
        raise
    except Exception:
        generation, available, evidence_fingerprint = _terminal_native_evidence(
            authority, request, paths
        )
        result = _failed_result(
            row.query_id,
            item["row_fingerprint"],
            "failed",
            implementation_sha256=item["implementation_sha256"],
            ranking_metric_contract=item["identity"]["ranking_metric_contract"],
            paper_ir_duplicate_handling_assumption=item["identity"][
                "paper_ir_duplicate_handling_assumption"
            ],
            native_generation=generation,
            native_evidence_available=available,
            native_evidence_fingerprint=evidence_fingerprint,
            agent_operation_performed=agent_operation_performed,
            judge_operation_performed=judge_operation_performed,
            agent_operation_cost_usd=agent_operation_cost_usd,
            judge_operation_cost_usd=judge_operation_cost_usd,
        )
        query.write_json("result.json", result)
        return result


def _reserve_authorized_operation(
    request: BenchmarkRequest, kind: str
) -> FullExecutionReservation | None:
    authorization = request.full_execution_authorization
    if authorization is None:
        return None
    scope_id = request.experiment_scope_id
    if scope_id is None:
        raise DciBenchmarkError("DCI benchmark authorization scope changed")
    try:
        return reserve_full_execution_operation(authorization, scope_id, kind)
    except ExperimentAuthorizationError as error:
        raise DciBenchmarkError(str(error)) from error


def _reconcile_authorized_operation(
    request: BenchmarkRequest,
    reservation: FullExecutionReservation,
    actual_cost: float,
) -> None:
    authorization = request.full_execution_authorization
    if authorization is None:
        raise DciBenchmarkError("DCI benchmark authorization is invalid")
    try:
        reconcile_full_execution_operation(
            authorization, reservation, actual_cost
        )
    except ExperimentAuthorizationError as error:
        raise DciBenchmarkError(str(error)) from error


def _fail_authorized_operation(
    request: BenchmarkRequest,
    reservation: FullExecutionReservation | None,
) -> None:
    if reservation is None:
        return
    authorization = request.full_execution_authorization
    if authorization is None:
        return
    try:
        fail_full_execution_operation(authorization, reservation)
    except ExperimentAuthorizationError:
        pass


def _validated_cost(value: object, *, source: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise DciBenchmarkError(f"DCI benchmark {source} cost evidence is invalid")
    return float(value)


def _validated_agent_cost(native: _Directory, display_path: Path) -> float:
    lock: DciRunLock | None = None
    try:
        lock = DciRunLock.acquire_fd(native.fd, path=display_path, wait=True)
        state, _question, _prediction = validate_completed_run_evidence(lock)
        return _validated_agent_cost_from_state(state)
    except DciBenchmarkError:
        raise
    except (DciArtifactError, OSError, TypeError, ValueError) as error:
        raise DciBenchmarkError(
            "DCI benchmark Agent cost evidence is invalid"
        ) from error
    finally:
        if lock is not None:
            lock.release()


def _validated_agent_cost_from_state(state: object) -> float:
    if not isinstance(state, Mapping):
        raise DciBenchmarkError("DCI benchmark Agent cost evidence is invalid")
    messages = state.get("messages")
    if not isinstance(messages, list):
        raise DciBenchmarkError("DCI benchmark Agent cost evidence is invalid")
    found = False
    for item in messages:
        if not isinstance(item, Mapping) or item.get("event") != "message_end":
            continue
        message = item.get("message")
        if not isinstance(message, Mapping):
            raise DciBenchmarkError(
                "DCI benchmark Agent cost evidence is invalid"
            )
        if message.get("role") != "assistant":
            continue
        usage = message.get("usage")
        cost = usage.get("cost") if isinstance(usage, Mapping) else None
        if not isinstance(cost, Mapping):
            raise DciBenchmarkError(
                "DCI benchmark Agent cost evidence is invalid"
            )
        _validated_cost(cost.get("total"), source="Agent")
        found = True
    if not found:
        raise DciBenchmarkError("DCI benchmark Agent cost evidence is invalid")
    return _validated_cost(
        extract_agent_usage_metrics(state).get("cost_total"),
        source="Agent",
    )


def _validated_judge_cost(verdict: object) -> float:
    if not isinstance(verdict, Mapping):
        raise DciBenchmarkError("DCI benchmark Judge cost evidence is invalid")
    cost = verdict.get("cost_estimate_usd")
    if not isinstance(cost, Mapping):
        raise DciBenchmarkError("DCI benchmark Judge cost evidence is invalid")
    return _validated_cost(cost.get("total_cost"), source="Judge")


def _reusable_judge_verdict(
    native: _Directory,
    display_path: Path,
    row: BenchmarkRow,
    request: BenchmarkRequest,
) -> dict[str, object] | None:
    lock: DciRunLock | None = None
    try:
        lock = DciRunLock.acquire_fd(native.fd, path=display_path, wait=True)
        state, question, prediction = validate_completed_run_evidence(lock)
        if lock.recover_evaluation_transaction(
            validate_candidate=_valid_transaction_candidate
        ):
            state, question, prediction = validate_completed_run_evidence(lock)
        fingerprint = judge_request_fingerprint(
            config=request.judge_config,
            question=question,
            gold_answer=_qa_gold_answer(row),
            predicted_answer=prediction,
            contract_id=_judge_contract_for_request(request),
        )
        return _load_reusable_result(
            lock,
            state,
            fingerprint,
            request.judge_config,
            judge_contract=_judge_contract_for_request(request),
        )
    except DciBenchmarkError:
        raise
    except (DciArtifactError, OSError, TypeError, ValueError) as error:
        raise DciBenchmarkError(
            "DCI benchmark Judge cache evidence is invalid"
        ) from error
    finally:
        if lock is not None:
            lock.release()


async def _run_pi_async(
    paths: DciPaths,
    request: Any,
    *,
    output_dir: Path,
    output_directory_fd: int | None = None,
    resource_fds: tuple[int, ...] = (),
    system_prompt_override: Path | None = None,
    append_system_prompt_override: Path | None = None,
) -> DciRunResult:
    cancel_event = threading.Event()
    work = asyncio.create_task(
        asyncio.to_thread(
            run_pi_research,
            paths,
            request,
            output_dir=output_dir,
            _cancel_event=cancel_event,
            _output_directory_fd=output_directory_fd,
            _resource_fds=resource_fds,
            _system_prompt_override=system_prompt_override,
            _append_system_prompt_override=append_system_prompt_override,
        )
    )
    try:
        await asyncio.wait({work})
        return work.result()
    except asyncio.CancelledError:
        cancel_event.set()
        await _drain_tasks([work])
        raise


async def _drain_tasks(tasks: list[asyncio.Task[Any]]) -> None:
    pending = [task for task in tasks if not task.done()]
    while pending:
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        try:
            await asyncio.wait(pending)
        except asyncio.CancelledError:
            continue
        pending = [task for task in pending if not task.done()]
    for task in tasks:
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass


def _preflight_existing(
    output_root: Path,
    config: dict[str, object],
    items: tuple[dict[str, object], ...],
) -> None:
    if not output_root.exists():
        return
    config_path = output_root / "config.json"
    if config_path.exists():
        value = _read_public_json(config_path)
        if value.get("run_fingerprint") != config["run_fingerprint"]:
            raise DciBenchmarkError("DCI benchmark configuration is incompatible")
    for item in items:
        path = output_root / str(item["query_id"]) / "item.json"
        if not path.exists():
            continue
        value = _read_public_json(path)
        if not isinstance(value, dict) or value.get("row_fingerprint") != item["row_fingerprint"]:
            raise DciBenchmarkError("DCI benchmark row is incompatible")


def _preflight_locked(
    lock: _BatchLock,
    config: dict[str, object],
    items: tuple[dict[str, object], ...],
) -> None:
    existing = lock.read_optional_json("config.json")
    names = lock.list_names()
    if existing is None:
        if names - {lock.LOCK_NAME}:
            raise DciBenchmarkError("DCI benchmark configuration evidence is missing")
    else:
        legacy_nonpaper = "selection" not in existing
        expected_selection = config.get("selection")
        if not isinstance(expected_selection, dict):
            raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
        _validate_config_document(
            existing,
            expected_execution_class=str(expected_selection.get("execution_class")),
            allow_legacy_nonpaper=legacy_nonpaper,
        )
        compatible_fingerprints = {config["run_fingerprint"]}
        if legacy_nonpaper:
            compatible_fingerprints.add(_legacy_nonpaper_run_fingerprint(config))
        if existing.get("run_fingerprint") not in compatible_fingerprints:
            raise DciBenchmarkError("DCI benchmark configuration is incompatible")
    for item in items:
        query = lock.open_existing_query(str(item["query_id"]))
        if query is None:
            continue
        try:
            existing_item = query.read_optional_json("item.json")
            if existing_item is None and query.list_names():
                raise DciBenchmarkError("DCI benchmark item evidence is missing")
            if existing_item is not None:
                _validate_item_document(existing_item)
        finally:
            query.close()
        if existing_item is not None and not _same_run_item(existing_item, item):
            raise DciBenchmarkError("DCI benchmark row is incompatible")


def _legacy_nonpaper_run_fingerprint(config: dict[str, object]) -> str:
    selection = config.get("selection")
    if (
        not isinstance(selection, dict)
        or selection.get("execution_class") != "non-paper"
    ):
        return ""
    legacy = {key: item for key, item in config.items() if key != "selection"}
    return _fingerprint(
        {
            key: item
            for key, item in legacy.items()
            if key
            not in {
                "judge",
                "judge_configuration_fingerprint",
                "product_effective_config_sha256",
                "run_fingerprint",
                "batch_fingerprint",
            }
        }
    )


def _valid_resolution_configuration(
    value: object, *, profile_id: object, runtime: object
) -> bool:
    """Validate the closed, body-free resolution configuration evidence."""

    if not isinstance(value, dict):
        return False
    expected = {
        "schema",
        "dataset_id",
        "corpus",
        "parameter_source",
        "segment_characters",
        "alignment_version",
        "read_minimum_evidence_overlap",
        "registry",
        "manifests",
    }
    assumptions = value.get("operator_assumptions")
    if assumptions is not None:
        expected.add("operator_assumptions")
    corpus = value.get("corpus")
    registry = value.get("registry")
    manifests = value.get("manifests")
    overlap = value.get("read_minimum_evidence_overlap")
    if (
        set(value) != expected
        or value.get("schema") != "dci.trajectory-analysis-config/v1"
        or type(value.get("dataset_id")) is not str
        or not value["dataset_id"]
        or value.get("parameter_source") != "asterion-defined"
        or type(value.get("segment_characters")) is not int
        or value["segment_characters"] <= 0
        or value.get("alignment_version") != "dci.paper-alignment/v1"
        or type(overlap) not in {int, float}
        or not math.isfinite(float(overlap))
        or not 0.0 < float(overlap) <= 1.0
        or type(corpus) is not dict
        or set(corpus) != {"sha256", "file_count"}
        or re.fullmatch(r"[0-9a-f]{64}", str(corpus.get("sha256"))) is None
        or type(corpus.get("file_count")) is not int
        or corpus["file_count"] < 1
        or type(registry) is not dict
        or set(registry) != {"identity", "sha256"}
        or type(registry.get("identity")) is not str
        or not registry["identity"]
        or re.fullmatch(r"[0-9a-f]{64}", str(registry.get("sha256"))) is None
        or type(manifests) is not dict
        or not manifests
    ):
        return False
    for query_id, manifest in manifests.items():
        if (
            type(query_id) is not str
            or not query_id
            or type(manifest) is not dict
            or set(manifest) != {"identity", "sha256", "snapshot_key"}
            or type(manifest.get("identity")) is not str
            or not manifest["identity"]
            or re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("sha256"))) is None
            or type(manifest.get("snapshot_key")) is not str
            or not manifest["snapshot_key"]
        ):
            return False
    try:
        provider = runtime.get("provider") if isinstance(runtime, dict) else None
        model = runtime.get("model") if isinstance(runtime, dict) else None
        source_family = (
            None
            if profile_id is None
            else _resolve_prompt_profile(profile_id, provider=provider, model=model).source_family
        )
    except ValueError:
        return False
    if source_family == "paper-reference":
        return assumptions == _PAPER_RESOLUTION_ASSUMPTION_LABELS
    return assumptions is None


def _validate_config_document(
    value: dict[str, Any], *, expected_execution_class: str,
    allow_legacy_nonpaper: bool = False,
) -> None:
    if expected_execution_class not in {
        "paper-bounded",
        "paper-bounded-authorized",
        "paper-full-authorized",
        "non-paper",
    }:
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    expected = {
        "schema", "run_id", "product", "dataset", "mode", "profile",
        "corpus_identity", "corpus_contract", "corpus_content_identity",
        "corpus_hint", "runtime_contract", "context_contract", "cwd", "runtime",
        "conversation_features", "max_concurrency", "max_turns", "analysis",
        "figures", "judge", "judge_configuration_fingerprint",
        "ranking_metric_contract",
        "paper_ir_duplicate_handling_assumption",
        "implementation_sha256",
        "benchmark_prompt_contract", "benchmark_prompt_contract_sha256",
        "prompt_resources", "product_effective_config_sha256",
        "run_fingerprint", "batch_fingerprint",
    }
    optional = {
        "resolution",
        "ablation",
        "paper_full_authorization",
        "selection",
        "profile_sha256",
        "source_identity",
        "artifact_digests",
    }
    if (
        not expected.issubset(value)
        or not set(value).issubset(expected | optional)
        or value.get("schema") != "asterion.dci.batch/v1"
        or not _has_selected_prompt_contract(value)
        or not _has_selected_metric_contract(value)
        or not _has_selected_paper_ir_assumption(value)
        or (
            "resolution" in value
            and not _valid_resolution_configuration(
                value["resolution"],
                profile_id=value.get("profile"),
                runtime=value.get("runtime"),
            )
        )
        or re.fullmatch(
            r"[0-9a-f]{64}", str(value.get("implementation_sha256"))
        )
        is None
        or re.fullmatch(
            r"[0-9a-f]{64}", str(value.get("product_effective_config_sha256"))
        )
        is None
        or not isinstance(value.get("run_id"), str)
        or not value["run_id"]
        or value.get("product") != "asterion-dci"
    ):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    paper_authorization = value.get("paper_full_authorization")
    if paper_authorization is not None and (
        type(paper_authorization) is not dict
        or set(paper_authorization)
        != {
            "schema",
            "profile_id",
            "profile_identity_sha256",
            "experiment_profiles_sha256",
            "paper_benchmark_inventory_sha256",
            "paper_experiment_scopes_sha256",
            "estimated_budget_usd",
        }
        or paper_authorization.get("schema")
        != "asterion.dci.paper-full-authorization/v1"
        or any(
            re.fullmatch(r"[0-9a-f]{64}", str(paper_authorization.get(field)))
            is None
            for field in (
                "profile_identity_sha256",
                "experiment_profiles_sha256",
                "paper_benchmark_inventory_sha256",
                "paper_experiment_scopes_sha256",
            )
        )
        or type(paper_authorization.get("profile_id")) is not str
        or type(paper_authorization.get("estimated_budget_usd")) not in {int, float}
        or not math.isfinite(float(paper_authorization["estimated_budget_usd"]))
        or float(paper_authorization["estimated_budget_usd"]) < 0
    ):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    if (
        expected_execution_class
        in {"paper-bounded-authorized", "paper-full-authorized"}
    ) != (
        paper_authorization is not None
    ):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    selection = value.get("selection")
    resolution = value.get("resolution")
    resolution_assumptions = (
        resolution.get("operator_assumptions")
        if isinstance(resolution, dict)
        else None
    )
    try:
        selection_profile_scope = paper_scope_for_profile(value.get("profile"))
    except ValueError:
        selection_profile_scope = None
    if selection is None:
        if (
            not allow_legacy_nonpaper
            or expected_execution_class != "non-paper"
            or selection_profile_scope is not None
        ):
            raise DciBenchmarkError(
                "DCI benchmark configuration evidence is invalid"
            )
    elif (
        not isinstance(selection, dict)
        or set(selection)
        != {
            "schema",
            "execution_class",
            "id",
            "paper_scope",
            "selected_rows",
            "full_dataset",
            "comparable",
            "authorization_profile",
            "selected_ids_sha256",
        }
        or selection.get("schema") != "asterion.dci.selection/v1"
        or type(selection.get("selected_rows")) is not int
        or re.fullmatch(
            r"[0-9a-f]{64}", str(selection.get("selected_ids_sha256"))
        )
        is None
    ):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    if isinstance(selection, dict):
        execution_class = selection.get("execution_class")
        if execution_class != expected_execution_class:
            valid_selection = False
        elif execution_class == "paper-bounded":
            valid_selection = (
                selection.get("id") == "limit-1"
                and selection.get("paper_scope") == selection_profile_scope
                and selection.get("selected_rows") == 1
                and selection.get("full_dataset") is False
                and selection.get("comparable") is False
                and selection.get("authorization_profile") is None
            )
        elif execution_class == "paper-bounded-authorized":
            authorization_profile = selection.get("authorization_profile")
            selection_id = selection.get("id")
            limit_match = (
                re.fullmatch(r"limit-([1-9][0-9]*)", selection_id)
                if isinstance(selection_id, str)
                else None
            )
            try:
                authorized_scopes = resolve_experiment_profile(
                    authorization_profile
                ).scope_ids
            except ValueError:
                authorized_scopes = ()
            valid_selection = (
                limit_match is not None
                and selection.get("paper_scope") in authorized_scopes
                and selection.get("selected_rows") == int(limit_match.group(1))
                and selection.get("full_dataset") is False
                and selection.get("comparable") is False
                and type(authorization_profile) is str
                and isinstance(paper_authorization, dict)
                and paper_authorization.get("profile_id")
                == authorization_profile
            )
        elif execution_class == "paper-full-authorized":
            authorization_profile = selection.get("authorization_profile")
            try:
                authorized_scopes = resolve_experiment_profile(
                    authorization_profile
                ).scope_ids
                expected_rows = resolve_paper_experiment_scope(
                    selection.get("paper_scope")
                ).selection_count
            except ValueError:
                authorized_scopes = ()
                expected_rows = None
            valid_selection = (
                selection.get("id") == "paper-full"
                and selection.get("paper_scope") == selection_profile_scope
                and selection.get("paper_scope") in authorized_scopes
                and selection.get("selected_rows") == expected_rows
                and selection.get("full_dataset") is True
                and selection.get("comparable") is _paper_selection_is_comparable(
                    value.get("paper_ir_duplicate_handling_assumption"),
                    resolution_assumptions,
                )
                and type(authorization_profile) is str
            )
        elif execution_class == "non-paper":
            valid_selection = (
                selection_profile_scope is None
                and selection.get("id") == "request"
                and selection.get("paper_scope") is None
                and selection.get("selected_rows") > 0
                and selection.get("full_dataset") is False
                and selection.get("comparable") is False
                and selection.get("authorization_profile") is None
            )
        else:
            valid_selection = False
        if not valid_selection:
            raise DciBenchmarkError(
                "DCI benchmark configuration evidence is invalid"
            )
    batch_payload = dict(value)
    batch_payload.pop("artifact_digests", None)
    batch_fingerprint = batch_payload.pop("batch_fingerprint", None)
    if batch_fingerprint != _fingerprint(batch_payload):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    run_payload = {
        key: item
        for key, item in batch_payload.items()
        if key
        not in {
            "judge",
            "judge_configuration_fingerprint",
            "product_effective_config_sha256",
            "run_fingerprint",
        }
    }
    legacy_run_payload = {
        key: item
        for key, item in batch_payload.items()
        if key not in {"judge", "judge_configuration_fingerprint", "run_fingerprint"}
    }
    if value.get("run_fingerprint") not in {
        _fingerprint(run_payload),
        _fingerprint(legacy_run_payload),
    }:
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")


def _validate_item_document(value: dict[str, Any]) -> None:
    expected = {
        "schema", "query_id", "input", "prompt", "identity", "row_fingerprint",
        "judge_configuration_fingerprint", "implementation_sha256",
    }
    if set(value) != expected or value.get("schema") != "asterion.dci.batch-item/v1":
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")
    identity = value.get("identity")
    if not isinstance(identity, dict):
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")
    if (
        not _has_selected_prompt_contract(identity)
        or not _has_selected_metric_contract(identity)
        or not _has_selected_paper_ir_assumption(identity)
        or re.fullmatch(
            r"[0-9a-f]{64}", str(value.get("implementation_sha256"))
        )
        is None
        or identity.get("implementation_sha256")
        != value.get("implementation_sha256")
    ):
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")
    if value.get("row_fingerprint") != _fingerprint(identity):
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")
    if identity.get("row") != value.get("input") or identity.get("prompt") != value.get("prompt"):
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")


def _same_run_item(left: dict[str, Any], right: dict[str, object]) -> bool:
    return {
        key: value
        for key, value in left.items()
        if key != "judge_configuration_fingerprint"
    } == {
        key: value
        for key, value in right.items()
        if key != "judge_configuration_fingerprint"
    }


def _read_public_json(path: Path) -> dict[str, Any]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, ValueError) as error:
        raise DciBenchmarkError("DCI benchmark evidence is invalid") from error
    if not isinstance(value, dict):
        raise DciBenchmarkError("DCI benchmark evidence is invalid")
    return value


def _runtime_document(
    options: DciRuntimeOptions,
    *,
    context_contract: str | None = None,
) -> dict[str, object]:
    try:
        profile = resolve_context_profile(options.runtime_context_level)
        if profile is None:
            policy_identity = None
        else:
            with resolve_context_extension() as extension:
                if context_contract is None:
                    policy_identity = context_policy_identity(profile, extension)
                else:
                    source_identity = context_source_identity(
                        context_contract,
                        profile,
                        extension,
                    )
                    policy_identity = {
                        key: dict(value) if isinstance(value, Mapping) else value
                        for key, value in source_identity.items()
                    }
    except (ContextExtensionError, ValueError) as error:
        raise DciBenchmarkError("DCI benchmark context policy is invalid") from error
    return {
        "provider": options.provider,
        "model": options.model,
        "tools": options.tools,
        "timeout_seconds": options.timeout_seconds,
        "runtime_context_level": options.runtime_context_level,
        "context_policy_identity": policy_identity,
        "thinking_level": options.thinking_level,
        "node_max_old_space_size_mb": options.node_max_old_space_size_mb,
        "keep_session": options.keep_session,
        "extra_args_count": len(options.extra_args),
        "extra_args_fingerprint": extra_args_fingerprint(options.extra_args),
    }


def _prompt_contract_for_request(
    request: BenchmarkRequest,
) -> tuple[PromptContract, str]:
    if request.profile is None:
        if request.corpus is not None:
            raise DciBenchmarkError("DCI benchmark prompt contract is invalid")
        contract_id = "asterion.dci.prompt/safe/v1"
        source_family = "asterion-safe"
    else:
        try:
            profile = _resolve_prompt_profile(
                request.profile,
                provider=request.runtime_options.provider,
                model=request.runtime_options.model,
            )
            contract_id = profile.prompt_contract
            source_family = profile.source_family
        except ValueError as error:
            raise DciBenchmarkError("DCI benchmark prompt contract is invalid") from error
    try:
        contract = resolve_prompt_contract(contract_id)
        if contract.source_family != source_family:
            raise PromptContractError
        return contract, prompt_contract_sha256(contract, request.mode)
    except PromptContractError as error:
        raise DciBenchmarkError("DCI benchmark prompt contract is invalid") from error


def _judge_contract_for_request(request: BenchmarkRequest) -> str:
    """Resolve exactly one Judge semantics contract for a benchmark request."""

    if request.profile is None:
        return ASTERION_SAFE_JUDGE_CONTRACT
    try:
        return _resolve_prompt_profile(
            request.profile,
            provider=request.runtime_options.provider,
            model=request.runtime_options.model,
        ).judge_contract
    except ValueError as error:
        raise DciBenchmarkError("DCI benchmark Judge contract is invalid") from error


def _metric_contract_for_request(request: BenchmarkRequest) -> str | None:
    """Resolve the profile's one executable IR metric without model heuristics."""

    if request.mode != "ir":
        if request.paper_ir_duplicate_handling is not None:
            raise DciBenchmarkError("DCI benchmark metric contract is invalid")
        return None
    if request.profile is None:
        if request.paper_ir_duplicate_handling is not None:
            raise DciBenchmarkError("DCI benchmark metric contract is invalid")
        return DEDUPLICATED_NDCG_CONTRACT
    try:
        profile = _resolve_prompt_profile(
            request.profile,
            provider=request.runtime_options.provider,
            model=request.runtime_options.model,
        )
    except ValueError as error:
        raise DciBenchmarkError("DCI benchmark metric contract is invalid") from error
    if profile.source_family == "paper-reference":
        if request.paper_ir_duplicate_handling == "upstream-list":
            return UPSTREAM_LIST_NDCG_CONTRACT
        if request.paper_ir_duplicate_handling == "deduplicated":
            return DEDUPLICATED_NDCG_CONTRACT
        raise DciBenchmarkError("DCI benchmark metric contract is unreported")
    if request.paper_ir_duplicate_handling is not None:
        raise DciBenchmarkError("DCI benchmark metric contract is invalid")
    contracts = tuple(
        contract
        for contract in profile.metric_contracts
        if contract in {DEDUPLICATED_NDCG_CONTRACT, UPSTREAM_LIST_NDCG_CONTRACT}
    )
    if len(contracts) != 1:
        raise DciBenchmarkError("DCI benchmark metric contract is unreported")
    return contracts[0]


def validate_benchmark_metric_selection(request: BenchmarkRequest) -> None:
    """Reject missing or injected paper scoring assumptions before execution."""

    _resolution_parameters(request)
    _resolution_operator_assumptions(request)
    _metric_contract_for_request(request)
    _paper_ir_assumption_label_for_request(request)


def _paper_ir_assumption_label_for_request(
    request: BenchmarkRequest,
) -> str | None:
    """Return the explicit operator label without changing paper source claims."""

    _metric_contract_for_request(request)
    if request.mode != "ir" or request.profile is None:
        return None
    try:
        profile = _resolve_prompt_profile(
            request.profile,
            provider=request.runtime_options.provider,
            model=request.runtime_options.model,
        )
    except ValueError as error:
        raise DciBenchmarkError("DCI benchmark metric contract is invalid") from error
    if profile.source_family != "paper-reference":
        return None
    label = _PAPER_IR_ASSUMPTION_LABELS.get(request.paper_ir_duplicate_handling)
    if label is None:
        raise DciBenchmarkError("DCI benchmark metric contract is invalid")
    return label


def _paper_selection_is_comparable(
    assumption_label: object,
    resolution_assumptions: object = None,
) -> bool:
    """Paper-assumption IR results never claim paper-reported comparability."""

    return assumption_label is None and resolution_assumptions is None


def _has_selected_prompt_contract(value: Mapping[str, Any]) -> bool:
    try:
        profile_id = value.get("profile")
        mode = value.get("mode")
        if mode not in {"qa", "ir"}:
            return False
        if profile_id is None:
            contract_id = "asterion.dci.prompt/safe/v1"
            source_family = "asterion-safe"
        else:
            runtime = value.get("runtime")
            provider = runtime.get("provider") if isinstance(runtime, dict) else None
            model = runtime.get("model") if isinstance(runtime, dict) else None
            profile = _resolve_prompt_profile(
                profile_id, provider=provider, model=model
            )
            contract_id = profile.prompt_contract
            source_family = profile.source_family
        contract = resolve_prompt_contract(contract_id)
        return (
            contract.source_family == source_family
            and value.get("benchmark_prompt_contract") == contract.contract_id
            and value.get("benchmark_prompt_contract_sha256")
            == prompt_contract_sha256(contract, mode)
        )
    except (PromptContractError, ValueError):
        return False


def _has_selected_metric_contract(value: Mapping[str, Any]) -> bool:
    try:
        request = _metric_request_from_evidence(value)
        return value.get("ranking_metric_contract") == _metric_contract_for_request(
            request
        )
    except (DciBenchmarkError, ValueError):
        return False


def _has_selected_paper_ir_assumption(value: Mapping[str, Any]) -> bool:
    try:
        request = _metric_request_from_evidence(value)
        return value.get("paper_ir_duplicate_handling_assumption") == (
            _paper_ir_assumption_label_for_request(request)
        )
    except (DciBenchmarkError, ValueError):
        return False


def _metric_request_from_evidence(value: Mapping[str, Any]) -> BenchmarkRequest:
    mode = value.get("mode")
    if mode not in {"qa", "ir"}:
        raise ValueError
    profile_id = value.get("profile")
    runtime = value.get("runtime")
    provider = runtime.get("provider") if isinstance(runtime, dict) else None
    model = runtime.get("model") if isinstance(runtime, dict) else None
    label = value.get("paper_ir_duplicate_handling_assumption")
    handling = next(
        (
            candidate
            for candidate, expected_label in _PAPER_IR_ASSUMPTION_LABELS.items()
            if label == expected_label
        ),
        None,
    )
    if label is not None and handling is None:
        raise ValueError
    return BenchmarkRequest(
        dataset=Path("/metric-contract-input"),
        output_root=Path("/metric-contract-output"),
        cwd=Path("/metric-contract-cwd"),
        judge_config=JudgeConfig(),
        runtime_options=DciRuntimeOptions(provider=provider, model=model),
        mode=mode,
        profile=profile_id if isinstance(profile_id, str) else None,
        paper_ir_duplicate_handling=handling,
    )


def _resolve_prompt_profile(
    profile_id: object, *, provider: str | None, model: str | None
):
    if profile_id == "asterion-safe/claude-minimax":
        return resolve_experiment_profile(
            profile_id,
            invocation_provider=provider,
            invocation_model=model,
        )
    return resolve_experiment_profile(profile_id)


def _prompt(
    request: BenchmarkRequest, row: BenchmarkRow, contract: PromptContract
) -> str:
    if request.corpus is None:
        return row.query
    if request.mode == "ir":
        return contract.ir_builder(row.query, request.corpus, request.corpus_hint)
    return contract.qa_builder(row.query, request.corpus)


def _qa_gold_answer(row: BenchmarkRow) -> str:
    """Match the source runner's exact ``str(row["answer"])`` Judge input."""

    assert row.answer is not None
    return row.answer if isinstance(row.answer, str) else str(list(row.answer))


def _read_input_snapshot(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DciBenchmarkError("DCI benchmark input resource is invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            return handle.read()
    except DciBenchmarkError:
        raise
    except OSError as error:
        raise DciBenchmarkError("DCI benchmark input resource is invalid") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _publish_input_snapshots(
    lock: _BatchLock, snapshots: dict[str, bytes]
) -> _SnapshotAuthority:
    directory = lock.open_query(".inputs")
    descriptors: list[int] = []
    paths: dict[str, Path] = {}
    try:
        for key, raw in snapshots.items():
            name = f"{key}.txt"
            directory.write_bytes(name, raw)
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory.fd,
            )
            descriptors.append(descriptor)
            paths[key] = Path(f"/dev/fd/{descriptor}")
        return _SnapshotAuthority(paths=paths, fds=tuple(descriptors))
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise
    finally:
        directory.close()


def _result_generation(value: object) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("native_generation"), str):
        return value["native_generation"]
    return None


_NATIVE_GENERATION_PATTERN = re.compile(
    r"native-generation-(?:[0-9]{4}|[1-9][0-9]{4,})"
)


def _generation_names(query: _Directory) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                name
                for name in query.list_names()
                if _NATIVE_GENERATION_PATTERN.fullmatch(name)
            ),
            key=lambda name: int(name.rsplit("-", 1)[1]),
        )
    )


def _latest_generation(query: _Directory) -> str | None:
    names = _generation_names(query)
    return names[-1] if names else None


def _next_generation(query: _Directory) -> str:
    names = _generation_names(query)
    number = int(names[-1].rsplit("-", 1)[1]) + 1 if names else 1
    return f"native-generation-{number:04d}"


def _native_state(native: _Directory, display_path: Path) -> str:
    state = native.read_optional_json("state.json")
    if state is None:
        return "missing" if not native.list_names() else "malformed"
    status = state.get("status")
    if status == "completed":
        lock: DciRunLock | None = None
        try:
            lock = DciRunLock.acquire_fd(native.fd, path=display_path, wait=True)
            validate_completed_run_evidence(lock)
            return "completed"
        except (DciArtifactError, OSError, ValueError):
            return "malformed"
        finally:
            if lock is not None:
                lock.release()
    if status in {"failed", "incomplete", "running"}:
        return str(status)
    return "malformed"


def _validate_result_shape(
    value: dict[str, Any], item: dict[str, object], mode: str
) -> None:
    common = {
        "schema", "query_id", "row_fingerprint", "status", "mode",
        "native_generation", "native_evidence_fingerprint",
        "implementation_sha256", "ranking_metric_contract",
        "paper_ir_duplicate_handling_assumption",
        "agent_operation_performed", "judge_operation_performed",
        "agent_operation_cost_usd", "judge_operation_cost_usd",
    }
    expected = common | (
        {
            "is_correct", "judge_configuration_fingerprint",
            "judge_request_fingerprint",
        }
        if mode == "qa"
        else set()
    )
    if (
        set(value) != expected
        or value.get("schema") != "asterion.dci.batch-result/v1"
        or value.get("query_id") != item.get("query_id")
        or value.get("row_fingerprint") != item.get("row_fingerprint")
        or value.get("implementation_sha256")
        != item.get("implementation_sha256")
        or value.get("ranking_metric_contract")
        != item.get("identity", {}).get("ranking_metric_contract")
        or value.get("paper_ir_duplicate_handling_assumption")
        != item.get("identity", {}).get("paper_ir_duplicate_handling_assumption")
        or value.get("status") != "completed"
        or value.get("mode") != mode
        or not isinstance(value.get("native_generation"), str)
        or not _NATIVE_GENERATION_PATTERN.fullmatch(value["native_generation"])
        or not isinstance(value.get("native_evidence_fingerprint"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["native_evidence_fingerprint"])
        is None
        or type(value.get("agent_operation_performed")) is not bool
        or type(value.get("judge_operation_performed")) is not bool
        or not isinstance(value.get("agent_operation_cost_usd"), (int, float))
        or isinstance(value.get("agent_operation_cost_usd"), bool)
        or not math.isfinite(float(value["agent_operation_cost_usd"]))
        or float(value["agent_operation_cost_usd"]) < 0
        or not isinstance(value.get("judge_operation_cost_usd"), (int, float))
        or isinstance(value.get("judge_operation_cost_usd"), bool)
        or not math.isfinite(float(value["judge_operation_cost_usd"]))
        or float(value["judge_operation_cost_usd"]) < 0
        or (mode == "qa" and type(value.get("is_correct")) is not bool)
    ):
        raise DciBenchmarkError("DCI benchmark result evidence is invalid")


def _validate_terminal_result(
    value: dict[str, Any], item: dict[str, object]
) -> None:
    if (
        set(value)
        != {
            "schema", "query_id", "row_fingerprint", "status",
            "native_generation", "native_evidence_available",
            "native_evidence_fingerprint", "implementation_sha256",
            "ranking_metric_contract", "paper_ir_duplicate_handling_assumption",
            "agent_operation_performed", "judge_operation_performed",
            "agent_operation_cost_usd", "judge_operation_cost_usd",
        }
        or value.get("schema") != "asterion.dci.batch-result/v1"
        or value.get("query_id") != item.get("query_id")
        or value.get("row_fingerprint") != item.get("row_fingerprint")
        or value.get("implementation_sha256")
        != item.get("implementation_sha256")
        or value.get("ranking_metric_contract")
        != item.get("identity", {}).get("ranking_metric_contract")
        or value.get("paper_ir_duplicate_handling_assumption")
        != item.get("identity", {}).get("paper_ir_duplicate_handling_assumption")
        or value.get("status") not in {"failed", "cancelled", "not_started"}
        or value.get("native_generation") is not None
        and (
            not isinstance(value.get("native_generation"), str)
            or not _NATIVE_GENERATION_PATTERN.fullmatch(value["native_generation"])
        )
        or type(value.get("native_evidence_available")) is not bool
        or value.get("native_evidence_fingerprint") is not None
        and (
            not isinstance(value.get("native_evidence_fingerprint"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["native_evidence_fingerprint"])
            is None
        )
        or (
            value.get("status") == "not_started"
            and (
                value.get("native_generation") is not None
                or value.get("native_evidence_available") is not False
                or value.get("native_evidence_fingerprint") is not None
                or value.get("agent_operation_performed") is not False
                or value.get("judge_operation_performed") is not False
                or value.get("agent_operation_cost_usd") != 0.0
                or value.get("judge_operation_cost_usd") != 0.0
            )
        )
        or (
            value.get("native_evidence_available") is True
            and value.get("native_generation") is None
        )
        or (
            value.get("native_evidence_available") is True
            and value.get("native_evidence_fingerprint") is None
        )
        or (
            value.get("native_evidence_available") is False
            and value.get("native_evidence_fingerprint") is not None
        )
        or type(value.get("agent_operation_performed")) is not bool
        or type(value.get("judge_operation_performed")) is not bool
        or not isinstance(value.get("agent_operation_cost_usd"), (int, float))
        or isinstance(value.get("agent_operation_cost_usd"), bool)
        or not math.isfinite(float(value["agent_operation_cost_usd"]))
        or float(value["agent_operation_cost_usd"]) < 0
        or not isinstance(value.get("judge_operation_cost_usd"), (int, float))
        or isinstance(value.get("judge_operation_cost_usd"), bool)
        or not math.isfinite(float(value["judge_operation_cost_usd"]))
        or float(value["judge_operation_cost_usd"]) < 0
    ):
        raise DciBenchmarkError("DCI benchmark terminal result is invalid")


def _validate_exact_reuse(
    native: _Directory,
    result: dict[str, Any],
    item: dict[str, object],
    row: BenchmarkRow,
    request: BenchmarkRequest,
    *,
    query_path: Path,
) -> None:
    display_path = query_path / str(result["native_generation"])
    lock: DciRunLock | None = None
    try:
        if result.get("native_evidence_fingerprint") != _native_evidence_fingerprint(
            native, request.mode
        ):
            raise DciBenchmarkError("DCI benchmark result evidence is invalid")
        lock = DciRunLock.acquire_fd(native.fd, path=display_path, wait=True)
        state, question, prediction = validate_completed_run_evidence(lock)
        if request.mode == "ir":
            return
        assert row.answer is not None
        fingerprint = judge_request_fingerprint(
            config=request.judge_config,
            question=question,
            gold_answer=_qa_gold_answer(row),
            predicted_answer=prediction,
            contract_id=_judge_contract_for_request(request),
        )
        cached = _load_reusable_result(
            lock,
            state,
            fingerprint,
            request.judge_config,
            judge_contract=_judge_contract_for_request(request),
        )
        if result.get("judge_configuration_fingerprint") != item.get(
            "judge_configuration_fingerprint"
        ):
            raise _StaleJudgeResult
        if (
            cached is None
            or result.get("judge_request_fingerprint") != fingerprint
            or result.get("is_correct") is not cached.get("is_correct")
        ):
            raise DciBenchmarkError("DCI benchmark result evidence is invalid")
    except DciBenchmarkError:
        raise
    except (DciArtifactError, OSError, ValueError) as error:
        raise DciBenchmarkError("DCI benchmark result evidence is invalid") from error
    finally:
        if lock is not None:
            lock.release()


def _native_evidence_fingerprint(native: _Directory, mode: str) -> str:
    names = [
        "state.json", "question.txt", "final.txt", "events.jsonl",
        "conversation.json", "conversation_full.json",
        "latest_model_context.json", "stderr.txt",
    ]
    if mode == "qa":
        names.append("eval_result.json")
    documents: dict[str, str] = {}
    for name in names:
        value = native.read_optional_text(name)
        if value is None:
            raise DciBenchmarkError("DCI benchmark result evidence is invalid")
        documents[name] = value
    return _fingerprint(documents)


def _prompt_resource_digests(request: BenchmarkRequest) -> dict[str, object]:
    value: dict[str, object] = {}
    for name in ("system_prompt_file", "append_system_prompt_file"):
        path = getattr(request, name)
        value[name] = (
            None
            if path is None
            else {
                "identity": str(canonical_input_identity(path)),
                "sha256": _file_digest(canonical_input_identity(path)),
            }
        )
    return value


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise DciBenchmarkError("DCI benchmark input resource is invalid") from error


def _fingerprint(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _completed_run(path: Path) -> bool:
    state_path = path / "state.json"
    if not state_path.exists():
        return False
    lock: DciRunLock | None = None
    try:
        state = _read_public_json(state_path)
        if state.get("status") != "completed":
            return False
        lock = DciRunLock.acquire_existing(path, wait=True)
        validate_completed_run_evidence(lock)
        return True
    except (DciArtifactError, DciBenchmarkError, OSError, ValueError) as error:
        raise _NativeEvidenceError("DCI benchmark native evidence is invalid") from error
    finally:
        if lock is not None:
            lock.release()


def _resumable_run(path: Path) -> bool:
    try:
        state = json.loads((path / "state.json").read_text(encoding="utf-8"))
        return isinstance(state, dict) and state.get("status") in {"failed", "incomplete", "running"}
    except (OSError, UnicodeError, ValueError):
        return False


def _reusable_result(value: object, item: dict[str, object], mode: str) -> bool:
    identity = item.get("identity")
    if (
        not isinstance(value, dict)
        or not isinstance(identity, dict)
        or "paper_ir_duplicate_handling_assumption" not in value
        or "paper_ir_duplicate_handling_assumption" not in identity
        or value.get("status") != "completed"
        or value.get("row_fingerprint") != item["row_fingerprint"]
        or value.get("ranking_metric_contract")
        != identity.get("ranking_metric_contract")
        or value.get("paper_ir_duplicate_handling_assumption")
        != identity.get("paper_ir_duplicate_handling_assumption")
    ):
        return False
    if mode == "ir":
        return "is_correct" not in value
    return type(value.get("is_correct")) is bool and value.get("judge_configuration_fingerprint") == item["judge_configuration_fingerprint"]


def _terminal_native_evidence(
    authority: _RowAuthority,
    request: BenchmarkRequest,
    paths: DciPaths,
) -> tuple[str | None, bool, str | None]:
    native = authority.native
    generation = authority.generation
    if native is None or generation is None:
        return None, False, None
    try:
        resume_request = resume_request_from_output_dir(
            Path(generation),
            extra_args=request.runtime_options.extra_args,
            _directory_fd=native.fd,
        )
        native_lock = DciRunLock.acquire_fd(
            native.fd, path=Path(generation), wait=True
        )
        try:
            state, _question, final, stderr, context = validate_resumable_run_evidence(
                native_lock, resume_request, paths
            )
        finally:
            native_lock.release()
    except (DciArtifactError, DciRunError, OSError, ValueError):
        return generation, False, None
    return generation, True, _terminal_evidence_fingerprint(
        state=state, context=context, final_text=final, stderr_text=stderr
    )


def _terminal_evidence_fingerprint(
    *,
    state: Mapping[str, Any],
    context: Mapping[str, Any],
    final_text: str,
    stderr_text: str,
) -> str:
    return _fingerprint(
        {
            "state": state,
            "latest_model_context": context,
            "final_text": final_text,
            "stderr_text": stderr_text,
        }
    )


def _failed_result(
    query_id: str,
    row_fingerprint: object,
    status: str,
    *,
    implementation_sha256: object,
    ranking_metric_contract: object,
    paper_ir_duplicate_handling_assumption: object,
    native_generation: str | None = None,
    native_evidence_available: bool = False,
    native_evidence_fingerprint: str | None = None,
    agent_operation_performed: bool = False,
    judge_operation_performed: bool = False,
    agent_operation_cost_usd: float = 0.0,
    judge_operation_cost_usd: float = 0.0,
) -> dict[str, object]:
    return {
        "schema": "asterion.dci.batch-result/v1",
        "query_id": query_id,
        "row_fingerprint": row_fingerprint,
        "implementation_sha256": implementation_sha256,
        "ranking_metric_contract": ranking_metric_contract,
        "paper_ir_duplicate_handling_assumption": (
            paper_ir_duplicate_handling_assumption
        ),
        "status": status,
        "native_generation": native_generation,
        "native_evidence_available": native_evidence_available,
        "native_evidence_fingerprint": native_evidence_fingerprint,
        "agent_operation_performed": agent_operation_performed,
        "judge_operation_performed": judge_operation_performed,
        "agent_operation_cost_usd": agent_operation_cost_usd,
        "judge_operation_cost_usd": judge_operation_cost_usd,
    }


def _write_query_result(lock: _BatchLock, query_id: str, result: dict[str, object]) -> None:
    query = lock.open_query(query_id)
    try:
        query.write_json("result.json", result)
    finally:
        query.close()


def _counts(results: dict[int, dict[str, object]]) -> dict[str, int]:
    values = tuple(results[index] for index in sorted(results))
    return {"total": len(values), "correct": sum(value.get("is_correct") is True for value in values), "failed": sum(value.get("status") != "completed" for value in values)}


def _publish_aggregates(
    lock: _BatchLock,
    results: dict[int, dict[str, object]],
    *,
    request: BenchmarkRequest,
    paths: DciPaths,
    rows: tuple[BenchmarkRow, ...],
    authorities: dict[int, _RowAuthority],
    input_snapshots: Mapping[str, bytes],
    resolution_config: object,
    implementation_sha256: str,
    include_analysis: bool = False,
) -> None:
    ordered = [results[index] for index in sorted(results)]
    lock.write_text("results.jsonl", "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in ordered))
    metrics = _analysis_results(
        lock,
        ordered,
        rows,
        request,
        paths=paths,
        authorities=authorities,
        input_snapshots=input_snapshots,
        resolution_config=resolution_config if include_analysis else None,
    )
    reproduction_totals = _publish_reproduction_evidence(
        rows=rows,
        results=ordered,
        metrics=metrics,
        request=request,
        authorities=authorities,
    )
    summary = aggregate_results(metrics)
    summary["reproduction_totals"] = reproduction_totals
    summary["provenance"] = {
        "implementation_sha256": implementation_sha256,
        "ranking_metric_contract": _metric_contract_for_request(request),
        "paper_ir_duplicate_handling_assumption": (
            _paper_ir_assumption_label_for_request(request)
        ),
        "result_label": _paper_ir_assumption_label_for_request(request),
    }
    lock.write_json("summary.json", summary)
    if include_analysis and request.analysis:
        artifacts = write_analysis_artifacts(
            results=metrics,
            rows=[row.as_dict() for row in rows],
            summary=summary,
            include_figures=request.figures,
        )
        for name, value in artifacts.items():
            if "/" not in name:
                lock.write_bytes(name, value)
                continue
            directory_name, leaf = name.split("/", 1)
            directory = lock.open_query(directory_name)
            try:
                directory.write_bytes(leaf, value)
            finally:
                directory.close()
    _publish_artifact_digest_inventory(lock, ordered)


def _metric_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    result = float(value)
    return result if math.isfinite(result) else 0.0


def _metric_count(value: object) -> int:
    number = _metric_number(value)
    if number < 0 or not number.is_integer():
        raise DciBenchmarkError("DCI benchmark reproduction evidence is invalid")
    return int(number)


def _publish_reproduction_evidence(
    *,
    rows: tuple[BenchmarkRow, ...],
    results: list[dict[str, object]],
    metrics: list[dict[str, Any]],
    request: BenchmarkRequest,
    authorities: dict[int, _RowAuthority],
) -> dict[str, object]:
    if len(results) > len(rows):
        raise DciBenchmarkError("DCI benchmark reproduction evidence is invalid")
    result_ids = {str(result.get("query_id")) for result in results}
    metric_by_id: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        query_id = str(metric.get("query_id"))
        if query_id in metric_by_id or query_id not in result_ids:
            raise DciBenchmarkError("DCI benchmark reproduction evidence is invalid")
        metric_by_id[query_id] = metric
    totals = {
        "agent_operations": 0,
        "judge_operations": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    for index, result in enumerate(results):
        query_id = str(result.get("query_id"))
        metric = metric_by_id.get(query_id)
        if metric is None:
            if result.get("status") == "completed":
                metric = {
                    "query_id": query_id,
                    "is_correct": result.get("is_correct"),
                    "ndcg_at_10": result.get("ndcg_at_10"),
                }
            else:
                metric = {}
        if index not in authorities:
            raise DciBenchmarkError("DCI benchmark reproduction evidence is invalid")
        agent = metric.get("agent_usage")
        judge = metric.get("judge_usage")
        judge_cost = metric.get("judge_cost_estimate_usd")
        agent_usage = agent if isinstance(agent, Mapping) else {}
        judge_usage = judge if isinstance(judge, Mapping) else {}
        judge_costs = judge_cost if isinstance(judge_cost, Mapping) else {}
        agent_performed = result.get("agent_operation_performed")
        judge_performed = result.get("judge_operation_performed")
        if type(agent_performed) is not bool or type(judge_performed) is not bool:
            raise DciBenchmarkError("DCI benchmark reproduction evidence is invalid")
        agent_input_tokens = _metric_count(agent_usage.get("input_tokens"))
        judge_input_tokens = _metric_count(judge_usage.get("input_tokens"))
        cached_tokens = (
            _metric_count(agent_usage.get("cache_read_tokens"))
            + _metric_count(agent_usage.get("cache_write_tokens"))
            if agent_performed
            else 0
        )
        input_tokens = (
            (agent_input_tokens if agent_performed else 0)
            + (judge_input_tokens if judge_performed else 0)
        )
        output_tokens = (
            (_metric_count(agent_usage.get("output_tokens")) if agent_performed else 0)
            + (_metric_count(judge_usage.get("output_tokens")) if judge_performed else 0)
        )
        agent_cost = _metric_number(agent_usage.get("cost_total"))
        judge_total_cost = _metric_number(judge_costs.get("total_cost"))
        status = str(result.get("status"))
        agent_operations = 1 if agent_performed else 0
        judge_operations = 1 if judge_performed else 0
        current_cost = (
            (agent_cost if agent_performed else 0.0)
            + (judge_total_cost if judge_performed else 0.0)
        )
        evidence = {
            "schema": "asterion.dci.reproduction-evidence/v1",
            "query_id": query_id,
            "row_fingerprint": result.get("row_fingerprint"),
            "status": status,
            "mode": request.mode,
            "is_correct": metric.get("is_correct"),
            "ndcg_at_10": metric.get("ndcg_at_10"),
            "failure_class": None if status == "completed" else "runtime.failed/v1",
            "exclusion_reason": None,
            "agent_operations": agent_operations,
            "judge_operations": judge_operations,
            "tokens": {
                "input": input_tokens,
                "cached_input": cached_tokens,
                "output": output_tokens,
            },
            "cost_usd": current_cost,
        }
        query = authorities[index].query
        query.write_json("reproduction-evidence.json", evidence)
        totals["agent_operations"] += agent_operations
        totals["judge_operations"] += judge_operations
        totals["input_tokens"] += input_tokens
        totals["cached_input_tokens"] += cached_tokens
        totals["output_tokens"] += output_tokens
        totals["total_tokens"] += input_tokens + cached_tokens + output_tokens
        totals["cost_usd"] = float(totals["cost_usd"]) + current_cost
    return totals


def _artifact_text_digest(directory: _Directory, name: str) -> str:
    value = directory.read_optional_text(name)
    if value is None:
        raise DciBenchmarkError("DCI benchmark artifact digest inventory is invalid")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _publish_artifact_digest_inventory(
    lock: _BatchLock, results: list[dict[str, object]]
) -> None:
    config = lock.read_optional_json("config.json")
    if config is None:
        raise DciBenchmarkError("DCI benchmark artifact digest inventory is invalid")
    digests: dict[str, str] = {
        "results.jsonl": _artifact_text_digest(lock, "results.jsonl"),
        "summary.json": _artifact_text_digest(lock, "summary.json"),
    }
    for result in results:
        query_id = str(result.get("query_id"))
        query = lock.open_existing_query(query_id)
        if query is None:
            raise DciBenchmarkError("DCI benchmark artifact digest inventory is invalid")
        try:
            for name in ("item.json", "result.json", "reproduction-evidence.json"):
                digests[f"{query_id}/{name}"] = _artifact_text_digest(query, name)
        finally:
            query.close()
    config["artifact_digests"] = dict(sorted(digests.items()))
    lock.write_json("config.json", config)


def _analysis_results(
    lock: _BatchLock,
    results: list[dict[str, object]],
    rows: tuple[BenchmarkRow, ...],
    request: BenchmarkRequest,
    *,
    paths: DciPaths,
    authorities: dict[int, _RowAuthority],
    input_snapshots: Mapping[str, bytes],
    resolution_config: object,
) -> list[dict[str, Any]]:
    row_by_id = {row.query_id: row for row in rows}
    authority_by_id = {
        rows[index].query_id: authority for index, authority in authorities.items()
    }
    if resolution_config is not None and not isinstance(resolution_config, Mapping):
        raise DciBenchmarkError("DCI benchmark resolution evidence is invalid")
    resolution_manifests = (
        resolution_config.get("manifests", {})
        if isinstance(resolution_config, Mapping)
        else {}
    )
    if not isinstance(resolution_manifests, Mapping):
        raise DciBenchmarkError("DCI benchmark resolution evidence is invalid")
    if isinstance(resolution_config, Mapping):
        if (
            request.corpus is None
            or resolution_config.get("corpus")
            != _corpus_content_identity(request.corpus)
        ):
            raise DciBenchmarkError("DCI benchmark resolution corpus changed")
    metrics: list[dict[str, Any]] = []
    for result in results:
        query_id = str(result["query_id"])
        row = row_by_id[query_id]
        state: dict[str, Any] | None = None
        context: dict[str, Any] = {}
        final_text = stderr_text = ""
        judge_result: dict[str, Any] | None = None
        resolution_summary: dict[str, Any] | None = None
        authority = authority_by_id[query_id]
        _validate_bound_directory(lock, query_id, authority.query)
        timing = _validate_timing(authority.query.read_optional_json("timing.json"))
        generation = result.get("native_generation")
        if isinstance(generation, str):
            native = authority.native
            if native is None or authority.generation != generation:
                raise DciBenchmarkError("DCI benchmark analysis evidence is invalid")
            _validate_bound_directory(authority.query, generation, native)
            if result.get("status") == "completed":
                try:
                    item = authority.query.read_optional_json("item.json")
                    if item is None:
                        raise DciBenchmarkError(
                            "DCI benchmark analysis evidence is invalid"
                        )
                    _validate_item_document(item)
                    _validate_exact_reuse(
                        native,
                        result,
                        item,
                        row,
                        request,
                        query_path=lock.path / query_id,
                    )
                    state = native.read_optional_json("state.json") or state
                    context = native.read_optional_json("latest_model_context.json") or {}
                    final_text = native.read_optional_text("final.txt") or str(state.get("assistant_text") or "")
                    stderr_text = native.read_optional_text("stderr.txt") or ""
                    judge_result = native.read_optional_json("eval_result.json")
                except _StaleJudgeResult as error:
                    raise DciBenchmarkError(
                        "DCI benchmark analysis evidence is invalid"
                    ) from error
            elif result.get("native_evidence_available") is True:
                try:
                    resume_request = resume_request_from_output_dir(
                        lock.path / query_id / generation,
                        extra_args=request.runtime_options.extra_args,
                        _directory_fd=native.fd,
                    )
                    native_lock = DciRunLock.acquire_fd(
                        native.fd,
                        path=lock.path / query_id / generation,
                        wait=True,
                    )
                    try:
                        state, _question, final_text, stderr_text, context = (
                            validate_resumable_run_evidence(
                                native_lock, resume_request, paths
                            )
                        )
                        if result.get(
                            "native_evidence_fingerprint"
                        ) != _terminal_evidence_fingerprint(
                            state=state,
                            context=context,
                            final_text=final_text,
                            stderr_text=stderr_text,
                        ):
                            raise DciBenchmarkError(
                                "DCI benchmark analysis evidence is invalid"
                            )
                    finally:
                        native_lock.release()
                except (DciArtifactError, DciRunError, OSError, ValueError) as error:
                    raise DciBenchmarkError(
                        "DCI benchmark analysis evidence is invalid"
                    ) from error
        if judge_result is None and type(result.get("is_correct")) is bool:
            judge_result = {"is_correct": result["is_correct"]}
        ndcg = (
            compute_ir_ndcg(
                final_text,
                row,
                request.corpus,
                10,
                metric_contract=str(_metric_contract_for_request(request)),
            )
            if request.mode == "ir" and result.get("status") == "completed"
            else None
        )
        if (
            query_id in resolution_manifests
            and result.get("status") == "completed"
            and state is not None
            and isinstance(generation, str)
            and request.corpus is not None
            and request.resolution_segment_characters is not None
            and request.resolution_read_minimum_evidence_overlap is not None
        ):
            attempts = state.get("attempts")
            if not isinstance(attempts, list) or not attempts:
                raise DciBenchmarkError("DCI benchmark resolution evidence is invalid")
            try:
                manifest_identity = resolution_manifests[query_id]
                if not isinstance(manifest_identity, Mapping):
                    raise DciBenchmarkError(
                        "DCI benchmark resolution evidence is invalid"
                    )
                snapshot_key = manifest_identity.get("snapshot_key")
                manifest_bytes = input_snapshots.get(str(snapshot_key))
                if (
                    not isinstance(snapshot_key, str)
                    or manifest_bytes is None
                    or hashlib.sha256(manifest_bytes).hexdigest()
                    != manifest_identity.get("sha256")
                ):
                    raise DciBenchmarkError(
                        "DCI benchmark resolution evidence is invalid"
                    )
                evidence = analyze_trajectory_resolution(
                    run_dir=lock.path / query_id / generation,
                    attempt=len(attempts),
                    corpus_dir=request.corpus,
                    config=TrajectoryAnalysisConfig(
                        segment_characters=request.resolution_segment_characters,
                        read_minimum_evidence_overlap=(
                            request.resolution_read_minimum_evidence_overlap
                        ),
                    ),
                    gold_manifest_bytes=manifest_bytes,
                )
                _validate_bound_directory(authority.query, generation, native)
                native.write_json("trajectory-resolution.json", evidence)
                resolution_summary = public_resolution_projection(evidence)
            except (OSError, TrajectoryResolutionError, ValueError) as error:
                raise DciBenchmarkError(
                    "DCI benchmark resolution evidence is invalid"
                ) from error
        metrics.append(
            gather_query_metrics(
                row=row.as_dict(),
                state=state,
                latest_model_context=context,
                final_text=final_text,
                stderr_text=stderr_text,
                judge_result=judge_result,
                ndcg_at_10=ndcg,
                launcher_started_at=str(timing.get("launcher_started_at")) if timing else None,
                launcher_finished_at=str(timing.get("launcher_finished_at")) if timing else None,
                launcher_returncode=(
                    0 if result.get("status") == "completed" else None
                ),
                resolution_summary=resolution_summary,
            )
        )
    return metrics


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_timing(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if (
        set(value)
        != {
            "schema", "native_generation",
            "launcher_started_at", "launcher_finished_at",
        }
        or value.get("schema") != "asterion.dci.batch-timing/v2"
        or not isinstance(value.get("native_generation"), str)
        or not _NATIVE_GENERATION_PATTERN.fullmatch(value["native_generation"])
        or any(
            item is not None and not isinstance(item, str)
            for item in (
                value.get("launcher_started_at"), value.get("launcher_finished_at"),
            )
        )
    ):
        raise DciBenchmarkError("DCI benchmark timing evidence is invalid")
    return value


def _validate_bound_directory(
    parent: _Directory, name: str, child: _Directory
) -> None:
    _validate_component(name)
    try:
        expected = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
        actual = os.fstat(child.fd)
    except OSError as error:
        raise DciBenchmarkError("DCI benchmark analysis evidence is invalid") from error
    if (
        not stat.S_ISDIR(expected.st_mode)
        or expected.st_dev != actual.st_dev
        or expected.st_ino != actual.st_ino
    ):
        raise DciBenchmarkError("DCI benchmark analysis evidence is invalid")


def _write_query_timing(
    query: _Directory,
    result: dict[str, object],
    *,
    prior_timing: dict[str, Any] | None,
    started_at: str | None,
    finished_at: str | None,
) -> None:
    generation = result.get("native_generation")
    if not isinstance(generation, str):
        return
    if prior_timing is not None and prior_timing.get("native_generation") == generation:
        return
    query.write_json(
        "timing.json",
        {
            "schema": "asterion.dci.batch-timing/v2",
            "native_generation": generation,
            "launcher_started_at": started_at,
            "launcher_finished_at": finished_at,
        },
    )


def _publish_batch_state(
    lock: _BatchLock, status: str, results: dict[int, dict[str, object]]
) -> None:
    lock.write_json(
        "batch-state.json",
        {
            "schema": "asterion.dci.batch-state/v1",
            "status": status,
            "counts": _counts(results),
        },
    )


def _terminal_results(
    lock: _BatchLock,
    rows: tuple[BenchmarkRow, ...],
    items: tuple[dict[str, object], ...],
    *,
    authorities: dict[int, _RowAuthority],
    trusted: dict[int, dict[str, object]],
    missing_status: str,
) -> dict[int, dict[str, object]]:
    results: dict[int, dict[str, object]] = {}
    for index, row in enumerate(rows):
        query = authorities[index].query
        query.write_json("item.json", items[index])
        query.write_text("input_question.txt", str(items[index]["prompt"]))
        result = trusted.get(index)
        if result is None:
            candidate = query.read_optional_json("result.json")
            if candidate is not None:
                try:
                    _validate_terminal_result(candidate, items[index])
                except DciBenchmarkError:
                    candidate = None
            result = candidate
        if result is None:
            result = _failed_result(
                row.query_id,
                items[index]["row_fingerprint"],
                missing_status,
                implementation_sha256=items[index]["implementation_sha256"],
                ranking_metric_contract=items[index]["identity"]["ranking_metric_contract"],
                paper_ir_duplicate_handling_assumption=items[index]["identity"][
                    "paper_ir_duplicate_handling_assumption"
                ],
            )
            query.write_json("result.json", result)
        results[index] = result
    return results


def _drained_task_results(
    tasks: list[asyncio.Task[tuple[int, dict[str, object]]]],
) -> dict[int, dict[str, object]]:
    results: dict[int, dict[str, object]] = {}
    for task in tasks:
        if task.cancelled():
            continue
        try:
            index, result = task.result()
        except Exception:
            continue
        results[index] = result
    return results


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise DciBenchmarkError("DCI benchmark destination is unsafe")


def _open_or_create_output_directory(
    path: Path, *, expected_identity: tuple[int, int] | None = None
) -> int:
    descriptor = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for component in path.parts[1:]:
            try:
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if expected_identity is not None:
                    raise
                os.mkdir(component, 0o700, dir_fd=descriptor)
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            os.close(descriptor)
            descriptor = next_descriptor
        opened = os.fstat(descriptor)
        if expected_identity is not None and (
            opened.st_dev,
            opened.st_ino,
        ) != expected_identity:
            raise DciBenchmarkError(
                "DCI benchmark authorized output root identity changed"
            )
        os.fchmod(descriptor, 0o700)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_component(name: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or "\0" in name
        or "/" in name
        or (os.altsep is not None and os.altsep in name)
        or os.path.isabs(name)
    ):
        raise DciBenchmarkError("DCI benchmark evidence name is invalid")


class _Directory:
    def __init__(self, fd: int) -> None:
        self.fd = fd

    def read_optional_json(self, name: str) -> dict[str, Any] | None:
        _validate_component(name)
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.fd)
        except FileNotFoundError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DciBenchmarkError("DCI benchmark evidence is invalid")
            with os.fdopen(fd, encoding="utf-8") as handle:
                fd = -1
                value = json.load(handle)
        except (OSError, UnicodeError, ValueError) as error:
            raise DciBenchmarkError("DCI benchmark evidence is invalid") from error
        finally:
            if fd >= 0:
                os.close(fd)
        if not isinstance(value, dict):
            raise DciBenchmarkError("DCI benchmark evidence is invalid")
        return value

    def read_optional_text(self, name: str) -> str | None:
        _validate_component(name)
        try:
            fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self.fd,
            )
        except FileNotFoundError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DciBenchmarkError("DCI benchmark evidence is invalid")
            with os.fdopen(fd, encoding="utf-8") as handle:
                fd = -1
                return handle.read()
        except (OSError, UnicodeError) as error:
            raise DciBenchmarkError("DCI benchmark evidence is invalid") from error
        finally:
            if fd >= 0:
                os.close(fd)

    def write_json(self, name: str, value: object) -> None:
        self.write_text(name, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def write_text(self, name: str, value: str) -> None:
        self.write_bytes(name, value.encode("utf-8"))

    def write_bytes(self, name: str, value: bytes) -> None:
        _validate_component(name)
        temporary = f".{name}.{secrets.token_hex(16)}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=self.fd)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                target = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                if stat.S_ISLNK(target.st_mode):
                    raise DciBenchmarkError("DCI benchmark destination is unsafe")
            except FileNotFoundError:
                pass
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass

    def list_names(self) -> set[str]:
        return set(os.listdir(self.fd))

    def open_query(self, name: str) -> _Directory:
        _validate_component(name)
        try:
            os.mkdir(name, 0o700, dir_fd=self.fd)
        except FileExistsError:
            pass
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self.fd,
            )
            os.fchmod(descriptor, 0o700)
            return _Directory(descriptor)
        except OSError as error:
            raise DciBenchmarkError(
                "DCI benchmark query destination is unsafe"
            ) from error

    def open_existing_query(self, name: str) -> _Directory | None:
        _validate_component(name)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self.fd,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise DciBenchmarkError(
                "DCI benchmark query destination is unsafe"
            ) from error
        return _Directory(descriptor)

    def close(self) -> None:
        os.close(self.fd)


class _BatchLock(_Directory):
    LOCK_NAME = ".asterion-dci-batch.lock"

    def __init__(self, path: Path, fd: int) -> None:
        super().__init__(fd)
        self.path = path
        self.lock_fd: int | None = None

    @classmethod
    def acquire(
        cls, path: Path, *, expected_identity: tuple[int, int] | None = None
    ) -> _BatchLock:
        if fcntl is None:
            raise DciBenchmarkError("DCI benchmark locking is unavailable")
        _reject_symlink_components(path)
        try:
            fd = _open_or_create_output_directory(
                path, expected_identity=expected_identity
            )
        except OSError as error:
            raise DciBenchmarkError("DCI benchmark destination is unsafe") from error
        lock = cls(path, fd)
        try:
            opened = os.fstat(fd)
            if expected_identity is not None and (
                opened.st_dev,
                opened.st_ino,
            ) != expected_identity:
                raise DciBenchmarkError(
                    "DCI benchmark authorized output root identity changed"
                )
            os.fchmod(fd, 0o700)
            lock.lock_fd = os.open(cls.LOCK_NAME, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=fd)
            os.fchmod(lock.lock_fd, 0o600)
            fcntl.flock(lock.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except DciBenchmarkError:
            lock.release()
            raise
        except (BlockingIOError, OSError) as error:
            lock.release()
            raise DciBenchmarkError("DCI benchmark is already running") from error

    def open_query(self, name: str) -> _Directory:
        _validate_component(name)
        try:
            os.mkdir(name, 0o700, dir_fd=self.fd)
        except FileExistsError:
            pass
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.fd)
            os.fchmod(fd, 0o700)
            return _Directory(fd)
        except OSError as error:
            raise DciBenchmarkError("DCI benchmark query destination is unsafe") from error

    def open_existing_query(self, name: str) -> _Directory | None:
        _validate_component(name)
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.fd)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise DciBenchmarkError("DCI benchmark query destination is unsafe") from error
        return _Directory(fd)

    def release(self) -> None:
        if self.lock_fd is not None:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self.lock_fd)
                self.lock_fd = None
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
