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
    context_policy_identity,
    resolve_context_profile,
)
from asterion.dci.datasets import (
    BENCHMARK_PROMPT_CONTRACT,
    BENCHMARK_PROMPT_CONTRACT_SHA256,
    BenchmarkRow,
    DatasetError,
    build_ir_prompt,
    build_qa_prompt,
    canonical_input_identity,
    load_benchmark_rows_bytes,
    load_beir_benchmark_rows_bytes,
    load_bright_benchmark_rows_bytes,
)
from asterion.dci.evaluation import (
    _load_reusable_result,
    evaluate_run_directory_async,
)
from asterion.dci.experiment_profiles import (
    EXPERIMENT_AUTHORIZATION_SCHEMA,
    FullExecutionAuthorization,
    experiment_profiles_sha256,
    resolve_experiment_profile,
)
from asterion.dci.judge import (
    JudgeConfig,
    judge_public_identity,
    judge_request_fingerprint,
)
from asterion.dci.paper_benchmarks import (
    paper_scope_for_profile,
    paper_scope_for_selected_ids,
    published_scope_selected_ids,
    require_af320_executable_scope,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.dci.analysis import (
    aggregate_results,
    gather_query_metrics,
    write_analysis_artifacts,
)
from asterion.dci.metrics import compute_ir_ndcg
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
    ablation_row: str | None = None
    full_execution_authorization: FullExecutionAuthorization | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    output_root: Path
    counts: dict[str, int]


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

    rows, output_root, config, row_documents, snapshots = _prepare(request)
    expected_identity = None
    if request.full_execution_authorization is not None:
        from asterion.dci.experiment_profiles import (
            _consumed_authorized_output_identity,
        )

        authorized_root, device, inode = _consumed_authorized_output_identity(
            request.full_execution_authorization
        )
        if authorized_root != output_root:
            raise DciBenchmarkError("DCI benchmark authorization root changed")
        expected_identity = (device, inode)
    lock = _BatchLock.acquire(output_root, expected_identity=expected_identity)
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
            )
        counts = _counts(results)
        _publish_aggregates(
            lock, results, request=request, paths=paths, rows=rows,
            authorities=row_authorities,
            include_analysis=True,
            input_snapshots=snapshots,
            resolution_config=config.get("resolution"),
        )
        _publish_batch_state(lock, "completed", results)
        return BenchmarkResult(output_root=output_root, counts=counts)
    except asyncio.CancelledError:
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
        )
        _publish_batch_state(lock, "cancelled", results)
        raise
    except BaseException:
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


def _resolution_manifest_paths(
    request: BenchmarkRequest, rows: tuple[BenchmarkRow, ...]
) -> tuple[dict[str, Path], dict[str, object], dict[str, bytes]]:
    registry_path = request.resolution_registry
    segment_characters = request.resolution_segment_characters
    if registry_path is None and segment_characters is None:
        return {}, {}, {}
    features = request.conversation_features or DciConversationFeatures()
    if (
        registry_path is None
        or type(segment_characters) is not int
        or segment_characters <= 0
        or request.corpus is None
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
            "segment_characters": segment_characters,
            "alignment_version": "dci.paper-alignment/v1",
            "read_minimum_evidence_overlap": 0.5,
            "registry": {
                "identity": str(canonical_input_identity(registry_path)),
                "sha256": hashlib.sha256(registry_raw).hexdigest(),
            },
            "manifests": identities,
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
    )
    if (
        paper_scope is not None
        and request.full_execution_authorization is None
        and not bounded_paper_selection
    ):
        raise DciBenchmarkError(
            "DCI paper scope is not executable in AF-320 without AF-340 authorization"
        )
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
    if any((row.is_ir if request.mode == "qa" else not row.is_ir) for row in rows):
        raise DciBenchmarkError("DCI benchmark dataset does not match its mode")
    _resolution_paths, resolution_config, resolution_snapshots = (
        _resolution_manifest_paths(request, rows)
    )
    output_root = Path(os.path.abspath(os.path.normpath(request.output_root)))
    _reject_symlink_components(output_root)
    authorized_scope = paper_scope or source_scope or selected_scope
    if (
        paper_scope is not None
        and not bounded_paper_selection
        and selected_scope != paper_scope
    ):
        raise DciBenchmarkError("DCI benchmark paper scope does not match its profile")
    corpus_identity = (
        str(canonical_input_identity(request.corpus)) if request.corpus else None
    )
    runtime = _runtime_document(request.runtime_options)
    judge = judge_public_identity(request.judge_config)
    judge_fingerprint = _fingerprint(judge)
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
        "dataset": {"identity": str(dataset_identity), "sha256": dataset_digest},
        "mode": request.mode,
        "profile": request.profile,
        "corpus_identity": corpus_identity,
        "corpus_hint": request.corpus_hint,
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
        "benchmark_prompt_contract": BENCHMARK_PROMPT_CONTRACT,
        "benchmark_prompt_contract_sha256": BENCHMARK_PROMPT_CONTRACT_SHA256,
        "prompt_resources": prompt_resources,
    }
    if bounded_paper_selection:
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
            "comparable": True,
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
    config["selection"] = selection
    if resolution_config:
        config["resolution"] = resolution_config
    if ablation_identity is not None:
        config["ablation"] = ablation_identity
    if paper_authorization_identity is not None:
        config["paper_full_authorization"] = paper_authorization_identity
    config["run_fingerprint"] = _fingerprint(
        {key: value for key, value in config.items() if key not in {"judge", "judge_configuration_fingerprint"}}
    )
    config["batch_fingerprint"] = _fingerprint(config)
    documents: list[dict[str, object]] = []
    for row in rows:
        prompt = _prompt(request, row)
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
            "benchmark_prompt_contract": BENCHMARK_PROMPT_CONTRACT,
            "benchmark_prompt_contract_sha256": BENCHMARK_PROMPT_CONTRACT_SHA256,
            "prompt_resources": config["prompt_resources"],
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
            }
        )
    if authorized_scope is not None and not bounded_paper_selection:
        authorization = request.full_execution_authorization
        if authorization is None or authorization.output_root != output_root:
            raise DciBenchmarkError("DCI benchmark requires AF-340 authorization")
        try:
            require_af320_executable_scope(authorized_scope, authorization)
        except ValueError as error:
            raise DciBenchmarkError(str(error)) from error
    return rows, output_root, config, tuple(documents), snapshots


def _paper_scope_for_rows(rows: tuple[BenchmarkRow, ...]) -> str | None:
    return paper_scope_for_selected_ids(
        tuple(row.query_id for row in rows)
    )


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
    agent_started_at: str | None = None
    agent_finished_at: str | None = None
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
                    _write_query_timing(
                        query,
                        existing,
                        prior_timing=prior_timing,
                        started_at=None,
                        finished_at=None,
                    )
                    return existing
            finally:
                native.close()

        if request.resume_policy == "reuse":
            result = _failed_result(
                row.query_id,
                item["row_fingerprint"],
                "failed",
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
                )
                native_request = replace(
                    native_request,
                    max_turns=request.max_turns,
                    system_prompt_file=request.system_prompt_file,
                    append_system_prompt_file=request.append_system_prompt_file,
                    conversation_features=request.conversation_features,
                )
                if native_state in {"failed", "incomplete", "running"}:
                    native_request = resume_request_from_output_dir(
                        native_dir,
                        extra_args=request.runtime_options.extra_args,
                        _directory_fd=native_authority.fd,
                    )
                agent_started_at = _utc_now()
                try:
                    await _run_pi_async(
                        paths,
                        native_request,
                        output_dir=native_dir,
                        output_directory_fd=native_authority.fd,
                        resource_fds=snapshots.fds,
                        system_prompt_override=snapshots.paths.get("system_prompt_file"),
                        append_system_prompt_override=snapshots.paths.get(
                            "append_system_prompt_file"
                        ),
                    )
                finally:
                    agent_finished_at = _utc_now()
            result: dict[str, object] = {
                "schema": "asterion.dci.batch-result/v1",
                "query_id": row.query_id,
                "row_fingerprint": item["row_fingerprint"],
                "status": "completed",
                "mode": request.mode,
                "native_generation": generation,
            }
            if request.mode == "qa":
                assert row.answer is not None
                verdict = await evaluate_run_directory_async(
                    native_dir,
                    gold_answer=_qa_gold_answer(row),
                    judge_config=request.judge_config,
                    _directory_fd=native_authority.fd,
                )
                result["is_correct"] = verdict["is_correct"]
                result["judge_configuration_fingerprint"] = item[
                    "judge_configuration_fingerprint"
                ]
                result["judge_request_fingerprint"] = verdict[
                    "judge_request_fingerprint"
                ]
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
            native_generation=generation,
            native_evidence_available=available,
            native_evidence_fingerprint=evidence_fingerprint,
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
            native_generation=generation,
            native_evidence_available=available,
            native_evidence_fingerprint=evidence_fingerprint,
        )
        query.write_json("result.json", result)
        return result


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
                "run_fingerprint",
                "batch_fingerprint",
            }
        }
    )


def _validate_config_document(
    value: dict[str, Any], *, expected_execution_class: str,
    allow_legacy_nonpaper: bool = False,
) -> None:
    if expected_execution_class not in {
        "paper-bounded",
        "paper-full-authorized",
        "non-paper",
    }:
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    expected = {
        "schema", "dataset", "mode", "profile", "corpus_identity", "corpus_hint",
        "cwd", "runtime", "conversation_features", "max_concurrency", "max_turns",
        "analysis", "figures", "judge", "judge_configuration_fingerprint",
        "benchmark_prompt_contract", "benchmark_prompt_contract_sha256",
        "prompt_resources", "run_fingerprint", "batch_fingerprint",
    }
    optional = {"resolution", "ablation", "paper_full_authorization", "selection"}
    if (
        not expected.issubset(value)
        or not set(value).issubset(expected | optional)
        or value.get("schema") != "asterion.dci.batch/v1"
        or value.get("benchmark_prompt_contract") != BENCHMARK_PROMPT_CONTRACT
        or value.get("benchmark_prompt_contract_sha256")
        != BENCHMARK_PROMPT_CONTRACT_SHA256
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
    if (expected_execution_class == "paper-full-authorized") != (
        paper_authorization is not None
    ):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    selection = value.get("selection")
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
        }
        or selection.get("schema") != "asterion.dci.selection/v1"
        or type(selection.get("selected_rows")) is not int
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
                and selection.get("comparable") is True
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
    batch_fingerprint = batch_payload.pop("batch_fingerprint", None)
    if batch_fingerprint != _fingerprint(batch_payload):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")
    run_payload = {
        key: item
        for key, item in batch_payload.items()
        if key not in {"judge", "judge_configuration_fingerprint", "run_fingerprint"}
    }
    if value.get("run_fingerprint") != _fingerprint(run_payload):
        raise DciBenchmarkError("DCI benchmark configuration evidence is invalid")


def _validate_item_document(value: dict[str, Any]) -> None:
    expected = {
        "schema", "query_id", "input", "prompt", "identity", "row_fingerprint",
        "judge_configuration_fingerprint",
    }
    if set(value) != expected or value.get("schema") != "asterion.dci.batch-item/v1":
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")
    identity = value.get("identity")
    if not isinstance(identity, dict):
        raise DciBenchmarkError("DCI benchmark item evidence is invalid")
    if (
        identity.get("benchmark_prompt_contract") != BENCHMARK_PROMPT_CONTRACT
        or identity.get("benchmark_prompt_contract_sha256")
        != BENCHMARK_PROMPT_CONTRACT_SHA256
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


def _runtime_document(options: DciRuntimeOptions) -> dict[str, object]:
    try:
        profile = resolve_context_profile(options.runtime_context_level)
        if profile is None:
            policy_identity = None
        else:
            with resolve_context_extension() as extension:
                policy_identity = context_policy_identity(profile, extension)
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


def _prompt(request: BenchmarkRequest, row: BenchmarkRow) -> str:
    if request.corpus is None:
        return row.query
    if request.mode == "ir":
        return build_ir_prompt(row.query, request.corpus, request.corpus_hint)
    return build_qa_prompt(row.query, request.corpus)


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
        or value.get("status") != "completed"
        or value.get("mode") != mode
        or not isinstance(value.get("native_generation"), str)
        or not _NATIVE_GENERATION_PATTERN.fullmatch(value["native_generation"])
        or not isinstance(value.get("native_evidence_fingerprint"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["native_evidence_fingerprint"])
        is None
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
            "native_evidence_fingerprint",
        }
        or value.get("schema") != "asterion.dci.batch-result/v1"
        or value.get("query_id") != item.get("query_id")
        or value.get("row_fingerprint") != item.get("row_fingerprint")
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
        )
        cached = _load_reusable_result(lock, state, fingerprint, request.judge_config)
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
    if not isinstance(value, dict) or value.get("status") != "completed" or value.get("row_fingerprint") != item["row_fingerprint"]:
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
    native_generation: str | None = None,
    native_evidence_available: bool = False,
    native_evidence_fingerprint: str | None = None,
) -> dict[str, object]:
    return {
        "schema": "asterion.dci.batch-result/v1",
        "query_id": query_id,
        "row_fingerprint": row_fingerprint,
        "status": status,
        "native_generation": native_generation,
        "native_evidence_available": native_evidence_available,
        "native_evidence_fingerprint": native_evidence_fingerprint,
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
    summary = aggregate_results(metrics)
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
            compute_ir_ndcg(final_text, row, request.corpus, 10)
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
                        segment_characters=request.resolution_segment_characters
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
                row.query_id, items[index]["row_fingerprint"], missing_status
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
