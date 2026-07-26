from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
import threading
import unittest
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, cast
from unittest.mock import patch

from asterion.dci import reproduction as reproduction_module
from asterion.dci.artifacts import DciConversationFeatures
from asterion.dci.benchmark import BenchmarkRequest, run_benchmark
from asterion.dci.config import DciPaths, DciRuntimeOptions, resolve_dci_paths
from asterion.dci.experiment_profiles import resolve_experiment_profile
from asterion.dci.judge import JudgeConfig
from asterion.dci.paper_benchmarks import canonical_sha256
from asterion.dci.prompts import prompt_contract_sha256, resolve_prompt_contract
from asterion.dci.reproduction import (
    RunManifest,
    compare_reproduction,
    compile_run_manifest,
    load_run_manifest,
    validate_run_manifest,
)
from asterion.dci.run import (
    DciRunRequest,
    DciRunResult,
    run_pi_research as _real_run_pi_research,
)


class _FixtureClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "answer"},
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "answer"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


def _recorded_run(
    paths: DciPaths,
    request: DciRunRequest,
    *,
    output_dir: Path | None = None,
    conversation_features: DciConversationFeatures | None = None,
    _cancel_event: threading.Event | None = None,
    _output_directory_fd: int | None = None,
    _resource_fds: tuple[int, ...] = (),
    _system_prompt_override: Path | None = None,
    _append_system_prompt_override: Path | None = None,
) -> DciRunResult:
    with patch("asterion.dci.run.PiRpcClient", _FixtureClient):
        return _real_run_pi_research(
            paths,
            request,
            output_dir=output_dir,
            conversation_features=conversation_features,
            _cancel_event=_cancel_event,
            _output_directory_fd=_output_directory_fd,
            _resource_fds=_resource_fds,
            _system_prompt_override=_system_prompt_override,
            _append_system_prompt_override=_append_system_prompt_override,
        )


def _verdict(config: JudgeConfig, *, correct: bool = True) -> dict[str, object]:
    return {
        **config.public_dict(),
        "judge_contract": "asterion.dci.answer-judge/strict-json/v1",
        "judged_at": "2026-07-25T00:00:00+00:00",
        "attempts": 1,
        "judge_request_fingerprint": "fixture",
        "is_correct": correct,
        "normalized_prediction": "answer",
        "reason": "fixture",
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        "cost_estimate_usd": {
            "input_cost": 0.01,
            "cached_input_cost": 0.0,
            "output_cost": 0.02,
            "total_cost": 0.03,
        },
    }


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_json_bytes(value))
    path.chmod(0o600)


def _fingerprint(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_batch_hashes(root: Path) -> None:
    query_ids = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("q")
    )
    rows = []
    for query_id in query_ids:
        item_path = root / query_id / "item.json"
        result_path = root / query_id / "result.json"
        item = json.loads(item_path.read_text(encoding="utf-8"))
        item["row_fingerprint"] = _fingerprint(item["identity"])
        _write_json(item_path, item)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["row_fingerprint"] = item["row_fingerprint"]
        _write_json(result_path, result)
        reproduction_path = root / query_id / "reproduction-evidence.json"
        if reproduction_path.exists():
            reproduction = json.loads(reproduction_path.read_text(encoding="utf-8"))
            reproduction["row_fingerprint"] = item["row_fingerprint"]
            _write_json(reproduction_path, reproduction)
        rows.append(result)
    rows.sort(key=lambda row: row["query_id"])
    (root / "results.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    (root / "results.jsonl").chmod(0o600)
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    artifacts: dict[str, str] = {
        "results.jsonl": _sha256(root / "results.jsonl"),
        "summary.json": _sha256(root / "summary.json"),
    }
    for query_id in query_ids:
        artifacts[f"{query_id}/item.json"] = _sha256(root / query_id / "item.json")
        artifacts[f"{query_id}/result.json"] = _sha256(root / query_id / "result.json")
        reproduction_path = root / query_id / "reproduction-evidence.json"
        if reproduction_path.exists():
            artifacts[f"{query_id}/reproduction-evidence.json"] = _sha256(
                reproduction_path
            )
    config["artifact_digests"] = dict(sorted(artifacts.items()))
    _write_json(root / "config.json", config)


class TestDciRunManifestCompiler(unittest.TestCase):
    def _batch(
        self,
        root: Path,
        *,
        mode: str = "qa",
        query_ids: tuple[str, ...] = ("q001", "q002", "q003", "q004"),
        mutations: tuple[Callable[[Path, dict[str, Any]], None], ...] = (),
    ) -> Path:
        profile = resolve_experiment_profile(
            "paper-reference/pi" if mode == "qa" else "asterion-safe/pi"
        )
        dataset_id = "browsecomp-plus" if mode == "qa" else "bright.biology"
        metric_identity = (
            None
            if mode == "qa"
            else "ndcg@10-binary-deduplicated/v1"
        )
        prompt_sha256 = prompt_contract_sha256(
            resolve_prompt_contract(profile.prompt_contract), mode
        )
        judge_fingerprint = _fingerprint(dict(profile.judge))
        config: dict[str, Any] = {
            "schema": "asterion.dci.batch/v1",
            "run_id": f"synthetic-{mode}",
            "product": "asterion-dci",
            "profile": profile.profile_id,
            "profile_sha256": profile.identity_sha256,
            "source_identity": profile.source_identity,
            "dataset": {
                "dataset_id": dataset_id,
                "identity": f"synthetic://{dataset_id}",
                "sha256": "a" * 64,
            },
            "selection": {
                "schema": "asterion.dci.selection/v1",
                "execution_class": "non-paper",
                "id": f"synthetic-{mode}",
                "paper_scope": None,
                "selected_ids_sha256": canonical_sha256(query_ids),
                "selected_rows": len(query_ids),
                "full_dataset": False,
                "comparable": True,
            },
            "mode": mode,
            "corpus_identity": "dci.paper-corpora/af-320-v1",
            "corpus_contract": profile.corpus_identity,
            "corpus_content_identity": None,
            "cwd": "/private/tmp/should-not-leak",
            "runtime_contract": profile.runtime_contract,
            "context_contract": profile.context_contract,
            "runtime": {
                "runtime_id": "pi",
                "provider": profile.provider,
                "model": profile.model,
                "tools": profile.tools,
                "context_contract": profile.context_contract,
            },
            "benchmark_prompt_contract": profile.prompt_contract,
            "benchmark_prompt_contract_sha256": prompt_sha256,
            "judge": dict(profile.judge),
            "judge_configuration_fingerprint": judge_fingerprint,
            "ranking_metric_contract": metric_identity,
            "implementation_sha256": profile.implementation_sha256,
            "product_effective_config_sha256": None,
        }
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
        rows: list[dict[str, Any]] = []
        agent_tokens = {
            "q001": (10, 1, 5, 0.11),
            "q002": (20, 2, 7, 0.22),
            "q003": (30, 3, 9, 0.33),
            "q004": (40, 4, 11, 0.44),
        }
        for index, query_id in enumerate(query_ids, 1):
            query = root / query_id
            query.mkdir(mode=0o700)
            query.chmod(0o700)
            identity = {
                "schema": "asterion.dci.batch-row/v1",
                "query_id": query_id,
                "profile": profile.profile_id,
                "prompt": f"What is hidden answer {index}? SECRET-answer-{index}",
                "corpus_identity": config["corpus_identity"],
                "runtime": config["runtime"],
                "benchmark_prompt_contract_sha256": config[
                    "benchmark_prompt_contract_sha256"
                ],
                "judge_configuration_fingerprint": config[
                    "judge_configuration_fingerprint"
                ],
                "ranking_metric_contract": config["ranking_metric_contract"],
                "implementation_sha256": config["implementation_sha256"],
            }
            item = {
                "schema": "asterion.dci.batch-item/v1",
                "query_id": query_id,
                "input": {
                    "query_id": query_id,
                    "query": f"Question body {index}",
                    "answer": f"Answer body {index}",
                },
                "prompt": identity["prompt"],
                "identity": identity,
                "row_fingerprint": _fingerprint(identity),
                "judge_configuration_fingerprint": config[
                    "judge_configuration_fingerprint"
                ],
                "implementation_sha256": config["implementation_sha256"],
            }
            input_tokens, cached_tokens, output_tokens, cost = agent_tokens[query_id]
            status = "failed" if query_id == "q003" else "completed"
            result: dict[str, Any] = {
                "schema": "asterion.dci.batch-result/v1",
                "query_id": query_id,
                "row_fingerprint": item["row_fingerprint"],
                "status": status,
                "mode": mode,
                "implementation_sha256": config["implementation_sha256"],
                "ranking_metric_contract": config["ranking_metric_contract"],
                "judge_configuration_fingerprint": config[
                    "judge_configuration_fingerprint"
                ],
                "native_generation": None,
                "failure_class": (
                    "runtime.failed/v1" if status == "failed" else None
                ),
                "exclusion_reason": (
                    "metric.not-applicable/v1" if query_id == "q004" else None
                ),
                "agent_operations": 1,
                "judge_operations": 1 if mode == "qa" and status == "completed" else 0,
                "tokens": {
                    "input": input_tokens,
                    "cached_input": cached_tokens,
                    "output": output_tokens,
                },
                "cost_usd": cost,
            }
            if mode == "qa":
                result["is_correct"] = (
                    True if query_id == "q001" else False if query_id == "q002" else None
                )
                result["ndcg_at_10"] = None
            else:
                result["is_correct"] = None
                result["ndcg_at_10"] = (
                    0.9 if query_id == "q001" else 0.2 if query_id == "q002" else None
                )
            _write_json(query / "item.json", item)
            _write_json(query / "result.json", result)
            rows.append(copy.deepcopy(result))
        _write_json(root / "config.json", config)
        (root / ".asterion-dci-batch.lock").write_text("locked\n", encoding="utf-8")
        (root / ".asterion-dci-batch.lock").chmod(0o600)
        rows.sort(key=lambda row: row["query_id"])
        (root / "results.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        (root / "results.jsonl").chmod(0o600)
        summary = {
            "schema": "asterion.dci.batch-summary/v1",
            "counts": {
                "total": len(rows),
                "completed": sum(row["status"] == "completed" for row in rows),
                "failed": sum(row["status"] == "failed" for row in rows),
                "excluded": sum(
                    row["exclusion_reason"] is not None for row in rows
                ),
            },
            "totals": {
                "agent_operations": sum(row["agent_operations"] for row in rows),
                "judge_operations": sum(row["judge_operations"] for row in rows),
                "input_tokens": sum(row["tokens"]["input"] for row in rows),
                "cached_input_tokens": sum(
                    row["tokens"]["cached_input"] for row in rows
                ),
                "output_tokens": sum(row["tokens"]["output"] for row in rows),
                "total_tokens": sum(
                    row["tokens"]["input"]
                    + row["tokens"]["cached_input"]
                    + row["tokens"]["output"]
                    for row in rows
                ),
                "cost_usd": sum(row["cost_usd"] for row in rows),
            },
            "provenance": {
                "implementation_sha256": config["implementation_sha256"],
                "ranking_metric_contract": config["ranking_metric_contract"],
                "prompt_contract_sha256": config["benchmark_prompt_contract_sha256"],
                "judge_configuration_fingerprint": config[
                    "judge_configuration_fingerprint"
                ],
                "corpus_identity": config["corpus_identity"],
                "selected_ids_sha256": config["selection"]["selected_ids_sha256"],
            },
        }
        _write_json(root / "summary.json", summary)
        artifacts: dict[str, str] = {
            "results.jsonl": _sha256(root / "results.jsonl"),
            "summary.json": _sha256(root / "summary.json"),
        }
        for query_id in query_ids:
            artifacts[f"{query_id}/item.json"] = _sha256(root / query_id / "item.json")
            artifacts[f"{query_id}/result.json"] = _sha256(
                root / query_id / "result.json"
            )
        config["artifact_digests"] = artifacts
        _write_json(root / "config.json", config)
        state = {"root": root, "config": config}
        for mutate in mutations:
            mutate(root, state)
        return root

    def _manifest_dict_without_identity(self, manifest: RunManifest, **overrides: object) -> dict[str, object]:
        payload = manifest.to_dict()
        payload.update(overrides)
        payload.pop("identity_sha256")
        payload["identity_sha256"] = canonical_sha256(payload)
        return payload

    def test_write_run_manifest_is_private_and_descriptor_bound(self) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch"
            batch.mkdir(mode=0o700)
            self._batch(batch)
            manifest_root = root / "manifests"
            manifest_root.mkdir(mode=0o700)
            manifest = compile_run_manifest(
                batch, resolve_experiment_profile("paper-reference/pi")
            )
            expected_identity = (
                manifest_root.stat().st_dev,
                manifest_root.stat().st_ino,
            )
            batch_inventory = tuple(
                sorted(path.relative_to(batch).as_posix() for path in batch.rglob("*"))
            )

            artifact = reproduction_module.write_run_manifest(
                manifest_root,
                expected_identity,
                scope_id,
                manifest,
            )

            self.assertEqual(
                artifact,
                hashlib.sha256(scope_id.encode("utf-8")).hexdigest() + ".json",
            )
            written = manifest_root / artifact
            self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)
            self.assertEqual(load_run_manifest(written), manifest)
            self.assertEqual(
                tuple(
                    sorted(
                        path.relative_to(batch).as_posix()
                        for path in batch.rglob("*")
                    )
                ),
                batch_inventory,
            )

            invalid_manifests = (
                {**manifest.to_dict(), "profile_sha256": "0" * 64},
                {**manifest.to_dict(), "prompt": "/private/sentinel/body"},
            )
            for invalid in invalid_manifests:
                with self.subTest(kind="invalid manifest"):
                    with self.assertRaises(ValueError):
                        reproduction_module.write_run_manifest(
                            manifest_root,
                            expected_identity,
                            "bright.earth-science.main.full",
                            invalid,
                        )
            with self.assertRaises(ValueError):
                reproduction_module.write_run_manifest(
                    manifest_root,
                    expected_identity,
                    "../private/sentinel",
                    manifest,
                )
            self.assertEqual(
                tuple(
                    sorted(
                        path.relative_to(batch).as_posix()
                        for path in batch.rglob("*")
                    )
                ),
                batch_inventory,
            )

    def test_write_run_manifest_rejects_replacement_and_overwrite(self) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch"
            batch.mkdir(mode=0o700)
            self._batch(batch)
            manifest = compile_run_manifest(
                batch, resolve_experiment_profile("paper-reference/pi")
            )
            batch_inventory = tuple(
                sorted(path.relative_to(batch).as_posix() for path in batch.rglob("*"))
            )

            replaced = root / "replaced-manifests"
            replaced.mkdir(mode=0o700)
            replaced_identity = (replaced.stat().st_dev, replaced.stat().st_ino)
            replaced.rename(root / "original-manifests")
            replaced.mkdir(mode=0o700)
            with self.assertRaises(ValueError):
                reproduction_module.write_run_manifest(
                    replaced,
                    replaced_identity,
                    scope_id,
                    manifest,
                )

            target = root / "target-manifests"
            target.mkdir(mode=0o700)
            symlink = root / "symlink-manifests"
            symlink.symlink_to(target, target_is_directory=True)
            target_identity = (target.stat().st_dev, target.stat().st_ino)
            with self.assertRaises(ValueError):
                reproduction_module.write_run_manifest(
                    symlink,
                    target_identity,
                    scope_id,
                    manifest,
                )

            artifact = hashlib.sha256(scope_id.encode("utf-8")).hexdigest() + ".json"
            existing = target / artifact
            existing.write_text("do not overwrite\n", encoding="utf-8")
            existing.chmod(0o600)
            with self.assertRaises(ValueError):
                reproduction_module.write_run_manifest(
                    target,
                    target_identity,
                    scope_id,
                    manifest,
                )
            self.assertEqual(existing.read_text(encoding="utf-8"), "do not overwrite\n")
            self.assertEqual(
                tuple(
                    sorted(
                        path.relative_to(batch).as_posix()
                        for path in batch.rglob("*")
                    )
                ),
                batch_inventory,
            )

    def test_write_run_manifest_close_failure_attempts_cleanup_and_allows_retry(
        self,
    ) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch"
            batch.mkdir(mode=0o700)
            self._batch(batch)
            manifest_root = root / "manifests"
            manifest_root.mkdir(mode=0o700)
            identity = (manifest_root.stat().st_dev, manifest_root.stat().st_ino)
            manifest = compile_run_manifest(
                batch, resolve_experiment_profile("paper-reference/pi")
            )
            artifact = hashlib.sha256(scope_id.encode()).hexdigest() + ".json"
            real_open = os.open
            real_close = os.close
            descriptors: dict[str, int] = {}
            close_calls: list[int] = []
            artifact_close_failed = False

            def open_spy(
                path: os.PathLike[str] | str,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = (
                    real_open(path, flags, mode)
                    if dir_fd is None
                    else real_open(path, flags, mode, dir_fd=dir_fd)
                )
                if path == manifest_root:
                    descriptors["root"] = descriptor
                elif path == artifact and dir_fd == descriptors.get("root"):
                    descriptors["artifact"] = descriptor
                return descriptor

            def close_spy(descriptor: int) -> None:
                nonlocal artifact_close_failed
                close_calls.append(descriptor)
                if (
                    descriptor == descriptors.get("artifact")
                    and not artifact_close_failed
                ):
                    artifact_close_failed = True
                    real_close(descriptor)
                    raise OSError("/private/sentinel artifact close")
                real_close(descriptor)

            with (
                patch("asterion.dci.reproduction.os.open", side_effect=open_spy),
                patch("asterion.dci.reproduction.os.close", side_effect=close_spy),
                self.assertRaisesRegex(
                    ValueError, "^DCI reproduction manifest write failed$"
                ) as raised,
            ):
                reproduction_module.write_run_manifest(
                    manifest_root,
                    identity,
                    scope_id,
                    manifest,
                )

            self.assertNotIn("/private/sentinel", str(raised.exception))
            self.assertIn(descriptors["root"], close_calls)
            self.assertFalse((manifest_root / artifact).exists())
            self.assertEqual(
                reproduction_module.write_run_manifest(
                    manifest_root,
                    identity,
                    scope_id,
                    manifest,
                ),
                artifact,
            )

    def test_write_run_manifest_cleanup_faults_do_not_mask_primary_failure(
        self,
    ) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root / "batch"
            batch.mkdir(mode=0o700)
            self._batch(batch)
            manifest_root = root / "manifests"
            manifest_root.mkdir(mode=0o700)
            identity = (manifest_root.stat().st_dev, manifest_root.stat().st_ino)
            manifest = compile_run_manifest(
                batch, resolve_experiment_profile("paper-reference/pi")
            )
            artifact = hashlib.sha256(scope_id.encode()).hexdigest() + ".json"
            real_open = os.open
            real_close = os.close
            real_fsync = os.fsync
            descriptors: dict[str, int] = {}
            close_calls: list[int] = []
            unlink_calls: list[tuple[str, int | None]] = []
            fsync_failed = False

            def open_spy(
                path: os.PathLike[str] | str,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                descriptor = (
                    real_open(path, flags, mode)
                    if dir_fd is None
                    else real_open(path, flags, mode, dir_fd=dir_fd)
                )
                if path == manifest_root:
                    descriptors["root"] = descriptor
                elif path == artifact and dir_fd == descriptors.get("root"):
                    descriptors["artifact"] = descriptor
                return descriptor

            def fsync_spy(descriptor: int) -> None:
                nonlocal fsync_failed
                if descriptor == descriptors.get("artifact") and not fsync_failed:
                    fsync_failed = True
                    raise OSError("SECRET primary write body")
                real_fsync(descriptor)

            def close_spy(descriptor: int) -> None:
                close_calls.append(descriptor)
                real_close(descriptor)
                if descriptor == descriptors.get("artifact"):
                    raise OSError("SECRET artifact close body")

            def unlink_spy(
                path: os.PathLike[str] | str, *, dir_fd: int | None = None
            ) -> None:
                unlink_calls.append((os.fspath(path), dir_fd))
                raise OSError("/private/sentinel unlink")

            with (
                patch("asterion.dci.reproduction.os.open", side_effect=open_spy),
                patch("asterion.dci.reproduction.os.fsync", side_effect=fsync_spy),
                patch("asterion.dci.reproduction.os.close", side_effect=close_spy),
                patch("asterion.dci.reproduction.os.unlink", side_effect=unlink_spy),
                self.assertRaisesRegex(
                    ValueError, "^DCI reproduction manifest write failed$"
                ) as raised,
            ):
                reproduction_module.write_run_manifest(
                    manifest_root,
                    identity,
                    scope_id,
                    manifest,
                )

            public_error = str(raised.exception)
            for sentinel in ("SECRET", "/private/sentinel"):
                self.assertNotIn(sentinel, public_error)
            self.assertEqual(unlink_calls, [(artifact, descriptors["root"])])
            self.assertIn(descriptors["root"], close_calls)
            failed_artifact = manifest_root / artifact
            self.assertTrue(failed_artifact.exists())
            failed_artifact.unlink()

    def test_compile_run_manifest_validates_locked_batch_and_compares_body_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = self._batch(root)
            profile = resolve_experiment_profile("paper-reference/pi")
            manifest = compile_run_manifest(batch, profile)
            validate_run_manifest(manifest)
            self.assertEqual(manifest.product, "asterion-dci")
            self.assertEqual(manifest.aggregates.included_count, 3)
            self.assertEqual(manifest.aggregates.excluded_count, 1)
            payload = manifest.to_dict()
            for key in (
                "source_identity",
                "corpus_identity",
                "prompt_identity",
                "judge_identity",
                "context_identity",
                "artifact_digests",
            ):
                self.assertIn(key, payload)
            self.assertEqual(
                payload["prompt_identity"],
                {
                    "contract": profile.prompt_contract,
                    "sha256": prompt_contract_sha256(
                        resolve_prompt_contract(profile.prompt_contract), "qa"
                    ),
                },
            )
            self.assertEqual(
                payload["judge_identity"],
                {
                    "contract": profile.judge_contract,
                    "configuration_sha256": _fingerprint(dict(profile.judge)),
                },
            )
            artifact_digests = cast(dict[str, object], payload["artifact_digests"])
            self.assertIn("results.jsonl", artifact_digests)
            rendered = json.dumps(manifest.to_dict(), sort_keys=True)
            for forbidden in (
                "What is hidden",
                "Question body",
                "Answer body",
                "SECRET",
                "/private/tmp",
                "provider_payload",
                "raw output",
            ):
                self.assertNotIn(forbidden, rendered)
            baseline = RunManifest.from_mapping(
                self._manifest_dict_without_identity(
                    manifest,
                    product="original-dci",
                    implementation_sha256="0" * 64,
                    product_effective_config_sha256="1" * 64,
                )
            )
            comparison = compare_reproduction(baseline, manifest, profile)
            self.assertEqual(comparison.candidate_product, "asterion-dci")

    def test_compile_run_manifest_supports_ir_metric_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = self._batch(root, mode="ir")
            manifest = compile_run_manifest(
                batch, resolve_experiment_profile("asterion-safe/pi")
            )
            validate_run_manifest(manifest)
            self.assertEqual(manifest.dataset_id, "bright.biology")
            self.assertEqual(manifest.metric_identities, ("ndcg@10-binary-deduplicated",))
            mean_ndcg_at_10 = manifest.aggregates.mean_ndcg_at_10
            self.assertIsNotNone(mean_ndcg_at_10)
            assert mean_ndcg_at_10 is not None
            self.assertAlmostEqual(mean_ndcg_at_10, (0.9 + 0.2) / 3)

    def test_compile_run_manifest_rejects_identity_and_digest_mutations(self) -> None:
        def mutate_config(key: str, value: object) -> Callable[[Path, dict[str, Any]], None]:
            def mutate(root: Path, state: dict[str, Any]) -> None:
                config = json.loads((root / "config.json").read_text(encoding="utf-8"))
                config[key] = value
                _write_json(root / "config.json", config)

            return mutate

        def mutate_nested_config(
            first: str, second: str, value: object
        ) -> Callable[[Path, dict[str, Any]], None]:
            def mutate(root: Path, state: dict[str, Any]) -> None:
                config = json.loads((root / "config.json").read_text(encoding="utf-8"))
                config[first][second] = value
                _write_json(root / "config.json", config)

            return mutate

        def mutate_prompt(root: Path, state: dict[str, Any]) -> None:
            item_path = root / "q001" / "item.json"
            item = json.loads(item_path.read_text(encoding="utf-8"))
            item["prompt"] = "changed prompt body"
            item["identity"]["prompt"] = "changed prompt body"
            _write_json(item_path, item)

        def mutate_metric(root: Path, state: dict[str, Any]) -> None:
            result_path = root / "q001" / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["ranking_metric_contract"] = "other-metric"
            _write_json(result_path, result)

        def mutate_operation_totals(root: Path, state: dict[str, Any]) -> None:
            summary_path = root / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["totals"]["agent_operations"] = 99
            _write_json(summary_path, summary)

        def mutate_artifact_digest(root: Path, state: dict[str, Any]) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["artifact_digests"]["q001/result.json"] = "f" * 64
            _write_json(root / "config.json", config)

        cases: dict[str, tuple[Callable[[Path, dict[str, Any]], None], ...]] = {
            "profile_sha": (mutate_config("profile_sha256", "0" * 64),),
            "implementation_sha": (mutate_config("implementation_sha256", "1" * 64),),
            "prompt": (mutate_prompt,),
            "judge": (mutate_config("judge_configuration_fingerprint", "2" * 64),),
            "metric": (mutate_metric,),
            "selected_ids": (
                mutate_nested_config("selection", "selected_ids_sha256", "3" * 64),
            ),
            "corpus_identity": (mutate_config("corpus_identity", "changed-corpus/v1"),),
            "operation_totals": (mutate_operation_totals,),
            "artifact_digest": (mutate_artifact_digest,),
        }
        profile = resolve_experiment_profile("paper-reference/pi")
        for label, mutations in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                batch = self._batch(Path(temporary), mutations=mutations)
                with self.assertRaises(ValueError):
                    compile_run_manifest(batch, profile)

    def test_compile_run_manifest_rejects_self_consistent_contract_forgery(self) -> None:
        def forge_every_mutable_contract(root: Path, _state: dict[str, Any]) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["source_identity"] = "attacker.source/v1"
            config["corpus_identity"] = "/private/attacker/corpus"
            config["benchmark_prompt_contract"] = "attacker.prompt/v1"
            config["benchmark_prompt_contract_sha256"] = "4" * 64
            config["judge"] = {"contract": "attacker.judge/v1", "model": "evil"}
            config["judge_configuration_fingerprint"] = "5" * 64
            config["ranking_metric_contract"] = "llm-answer-correctness"
            config["runtime"]["context_contract"] = "attacker.context/v1"
            config["product_effective_config_sha256"] = canonical_sha256(
                {
                    "product": config["product"],
                    "runtime": config["runtime"],
                    "prompt": config["benchmark_prompt_contract_sha256"],
                    "judge": config["judge_configuration_fingerprint"],
                    "corpus_identity": config["corpus_identity"],
                }
            )
            _write_json(root / "config.json", config)

            for query_dir in sorted(path for path in root.iterdir() if path.is_dir()):
                item_path = query_dir / "item.json"
                result_path = query_dir / "result.json"
                item = json.loads(item_path.read_text(encoding="utf-8"))
                item["identity"]["corpus_identity"] = config["corpus_identity"]
                item["identity"]["runtime"] = config["runtime"]
                item["identity"]["benchmark_prompt_contract_sha256"] = config[
                    "benchmark_prompt_contract_sha256"
                ]
                item["identity"]["judge_configuration_fingerprint"] = config[
                    "judge_configuration_fingerprint"
                ]
                item["identity"]["ranking_metric_contract"] = config[
                    "ranking_metric_contract"
                ]
                item["judge_configuration_fingerprint"] = config[
                    "judge_configuration_fingerprint"
                ]
                _write_json(item_path, item)
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result["ranking_metric_contract"] = config["ranking_metric_contract"]
                result["judge_configuration_fingerprint"] = config[
                    "judge_configuration_fingerprint"
                ]
                _write_json(result_path, result)
            _refresh_batch_hashes(root)

        with tempfile.TemporaryDirectory() as temporary:
            batch = self._batch(
                Path(temporary), mutations=(forge_every_mutable_contract,)
            )
            with self.assertRaises(ValueError):
                compile_run_manifest(
                    batch, resolve_experiment_profile("paper-reference/pi")
                )

    def test_compile_run_manifest_rejects_extra_artifact_inventory_entries(self) -> None:
        def add_extra_digest(root: Path, _state: dict[str, Any]) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["artifact_digests"]["provider-payload.json"] = "6" * 64
            _write_json(root / "config.json", config)

        with tempfile.TemporaryDirectory() as temporary:
            batch = self._batch(Path(temporary), mutations=(add_extra_digest,))
            with self.assertRaises(ValueError):
                compile_run_manifest(
                    batch, resolve_experiment_profile("paper-reference/pi")
                )

    def test_compile_run_manifest_rejects_nonpaper_paper_scope_masquerade(self) -> None:
        def masquerade(root: Path, _state: dict[str, Any]) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["selection"]["paper_scope"] = "browsecomp-plus.main.all830"
            _write_json(root / "config.json", config)
            _refresh_batch_hashes(root)

        with tempfile.TemporaryDirectory() as temporary:
            batch = self._batch(Path(temporary), mutations=(masquerade,))
            with self.assertRaises(ValueError):
                compile_run_manifest(
                    batch, resolve_experiment_profile("paper-reference/pi")
                )

    def test_compile_run_manifest_preserves_bounded_selection_identity(self) -> None:
        def bounded(root: Path, _state: dict[str, Any]) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["selection"] = {
                **config["selection"],
                "execution_class": "paper-bounded",
                "id": "limit-1",
                "paper_scope": "browsecomp-plus.main.all830",
                "selected_rows": 4,
                "full_dataset": False,
                "comparable": False,
                "authorization_profile": None,
            }
            _write_json(root / "config.json", config)
            _refresh_batch_hashes(root)

        with tempfile.TemporaryDirectory() as temporary:
            profile = resolve_experiment_profile("paper-reference/pi")
            manifest = compile_run_manifest(
                self._batch(Path(temporary), mutations=(bounded,)), profile
            )
            validate_run_manifest(manifest)
            self.assertEqual(manifest.selection_id, "limit-1")
            baseline = RunManifest.from_mapping(
                self._manifest_dict_without_identity(
                    manifest,
                    product="original-dci",
                    implementation_sha256="0" * 64,
                    product_effective_config_sha256="1" * 64,
                )
            )
            comparison = compare_reproduction(baseline, manifest, profile)
            self.assertEqual(comparison.selection_id, "limit-1")

    def test_compile_authorized_bounded_selection(self) -> None:
        scope_id = "browsecomp-plus.main.all830"
        query_id = "q001"

        def bounded(
            root: Path,
            _state: dict[str, Any],
            **selection_overrides: object,
        ) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["selection"] = {
                **config["selection"],
                "execution_class": "paper-bounded-authorized",
                "id": "limit-1",
                "paper_scope": scope_id,
                "selected_rows": 1,
                "full_dataset": False,
                "comparable": False,
                "authorization_profile": "paper-reference/pi",
                **selection_overrides,
            }
            config["paper_full_authorization"] = {
                "schema": "asterion.dci.paper-full-authorization/v1",
                "profile_id": "paper-reference/pi",
                "profile_identity_sha256": resolve_experiment_profile(
                    "paper-reference/pi"
                ).identity_sha256,
            }
            _write_json(root / "config.json", config)
            _refresh_batch_hashes(root)

        with tempfile.TemporaryDirectory() as temporary:
            profile = resolve_experiment_profile("paper-reference/pi")
            manifest = compile_run_manifest(
                self._batch(
                    Path(temporary),
                    query_ids=(query_id,),
                    mutations=(bounded,),
                ),
                profile,
            )
            validate_run_manifest(manifest)
            self.assertEqual(manifest.selection_id, "limit-1")
            self.assertEqual(
                manifest.selection_sha256,
                canonical_sha256((query_id,)),
            )
            self.assertEqual(manifest.aggregates.query_count, 1)

        forged_cases = {
            "limit ID": {"id": "limit-2"},
            "paper scope": {"paper_scope": "bright.biology.main.full"},
            "selected count": {"selected_rows": 2},
            "authorization profile": {
                "authorization_profile": "asterion-safe/pi"
            },
            "selected digest": {"selected_ids_sha256": "f" * 64},
        }
        profile = resolve_experiment_profile("paper-reference/pi")
        for label, overrides in forged_cases.items():
            def forged(
                root: Path,
                state: dict[str, Any],
                *,
                values: dict[str, object] = overrides,
            ) -> None:
                bounded(root, state, **values)

            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                batch = self._batch(
                    Path(temporary),
                    query_ids=(query_id,),
                    mutations=(forged,),
                )
                with self.assertRaises(ValueError):
                    compile_run_manifest(batch, profile)

    def test_compile_run_manifest_preserves_corpus_content_identity(self) -> None:
        def add_corpus_evidence(root: Path, _state: dict[str, Any]) -> None:
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            config["corpus_identity"] = "/private/corpus/root"
            config["corpus_content_identity"] = {
                "schema": "asterion.dci.corpus-content/v1",
                "contract": config["corpus_contract"],
                "sha256": "7" * 64,
                "file_count": 2,
            }
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
            for query_dir in sorted(path for path in root.iterdir() if path.is_dir()):
                item_path = query_dir / "item.json"
                item = json.loads(item_path.read_text(encoding="utf-8"))
                item["identity"]["corpus_identity"] = config["corpus_identity"]
                _write_json(item_path, item)
            _write_json(root / "config.json", config)
            _refresh_batch_hashes(root)

        with tempfile.TemporaryDirectory() as temporary:
            profile = resolve_experiment_profile("paper-reference/pi")
            manifest = compile_run_manifest(
                self._batch(Path(temporary), mutations=(add_corpus_evidence,)),
                profile,
            )
            validate_run_manifest(manifest)
            self.assertEqual(manifest.corpus_identity, profile.corpus_identity)
            corpus_content_identity = manifest.corpus_content_identity
            self.assertIsNotNone(corpus_content_identity)
            assert corpus_content_identity is not None
            self.assertEqual(corpus_content_identity["file_count"], 2)
            payload = manifest.to_dict()
            payload["corpus_content_identity"] = MappingProxyType(
                dict(corpus_content_identity)
            )
            reparsed = validate_run_manifest(payload)
            reparsed_corpus_content_identity = reparsed.corpus_content_identity
            self.assertIsNotNone(reparsed_corpus_content_identity)
            assert reparsed_corpus_content_identity is not None
            self.assertEqual(reparsed_corpus_content_identity["sha256"], "7" * 64)

    def test_compile_run_manifest_rejects_public_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = self._batch(root)
            os.chmod(batch / "q001" / "result.json", 0o644)
            with self.assertRaises(ValueError):
                compile_run_manifest(batch, resolve_experiment_profile("paper-reference/pi"))

    def test_compile_run_manifest_consumes_real_run_benchmark_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-real",
                        "query": "Question body should remain private",
                        "answer": "Answer body should remain private",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "doc.txt").write_text("body-free corpus digest source\n")
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                corpus=corpus,
                judge_config=JudgeConfig(),
                runtime_options=DciRuntimeOptions(
                    provider="openai-codex", model="gpt-5.6-luna"
                ),
                profile="asterion-safe/pi",
            )
            with patch(
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            manifest = compile_run_manifest(
                request.output_root, resolve_experiment_profile("asterion-safe/pi")
            )
            validate_run_manifest(manifest)
            payload = manifest.to_dict()
            self.assertEqual(payload["source_identity"], manifest.source_identity)
            artifact_digests = cast(dict[str, object], payload["artifact_digests"])
            self.assertIn("q-real/reproduction-evidence.json", artifact_digests)
            self.assertEqual(manifest.queries[0].operations.agent, 1)
            self.assertEqual(manifest.queries[0].operations.judge, 1)
            self.assertEqual(manifest.aggregates.failed_count, 1)
            self.assertIsNotNone(manifest.corpus_content_identity)
            rendered = json.dumps(manifest.to_dict(), sort_keys=True)
            self.assertNotIn("Question body", rendered)
            self.assertNotIn("Answer body", rendered)

    def test_compile_run_manifest_rejects_nested_query_directory_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = self._batch(root)
            nested = batch / "nested"
            nested.mkdir(mode=0o700)
            nested.chmod(0o700)
            target = nested / "q001"
            target.mkdir(mode=0o700)
            target.chmod(0o700)
            item = json.loads((batch / "q001" / "item.json").read_text(encoding="utf-8"))
            result = json.loads(
                (batch / "q001" / "result.json").read_text(encoding="utf-8")
            )
            item["query_id"] = "nested/q001"
            item["identity"]["query_id"] = "nested/q001"
            item["row_fingerprint"] = _fingerprint(item["identity"])
            result["query_id"] = "nested/q001"
            result["row_fingerprint"] = item["row_fingerprint"]
            _write_json(target / "item.json", item)
            _write_json(target / "result.json", result)
            results = []
            for line in (batch / "results.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["query_id"] == "q001":
                    row = result
                results.append(row)
            (batch / "results.jsonl").write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                    for row in results
                ),
                encoding="utf-8",
            )
            (batch / "results.jsonl").chmod(0o600)
            config = json.loads((batch / "config.json").read_text(encoding="utf-8"))
            config["artifact_digests"]["results.jsonl"] = _sha256(
                batch / "results.jsonl"
            )
            config["artifact_digests"]["nested/q001/item.json"] = _sha256(
                target / "item.json"
            )
            config["artifact_digests"]["nested/q001/result.json"] = _sha256(
                target / "result.json"
            )
            _write_json(batch / "config.json", config)
            with self.assertRaisesRegex(ValueError, "query directory"):
                compile_run_manifest(
                    batch, resolve_experiment_profile("paper-reference/pi")
                )

    def test_reproduction_targets_cover_main_ablation_context_and_scaling_matrix(self) -> None:
        payload = json.loads(
            resources.files("asterion.dci.resources")
            .joinpath("reproduction-targets.json")
            .read_text(encoding="utf-8")
        )
        targets = {target["target_id"]: target for target in payload["targets"]}
        expected = {
            "paper.2605.05242v1/dci-agent-lite/main",
            "paper.2605.05242v1/dci-agent-cc/main",
            "paper.2605.05242v1/tools/read-bash",
            "paper.2605.05242v1/tools/read-grep",
            "paper.2605.05242v1/context/level0",
            "paper.2605.05242v1/context/level1",
            "paper.2605.05242v1/context/level2",
            "paper.2605.05242v1/context/level3",
            "paper.2605.05242v1/context/level4",
            "paper.2605.05242v1/corpus/100k",
            "paper.2605.05242v1/corpus/200k",
            "paper.2605.05242v1/corpus/400k",
        }
        self.assertTrue(expected.issubset(targets))
        for target_id in expected:
            target = targets[target_id]
            self.assertIn("paper_table", target)
            self.assertIn("paper_row", target)
            self.assertIn("metric_contract", target)
        self.assertEqual(
            targets["paper.2605.05242v1/dci-agent-cc/main"]["target_status"],
            "executable-comparable",
        )
        for target_id in expected - {"paper.2605.05242v1/dci-agent-cc/main"}:
            self.assertEqual(targets[target_id]["target_status"], "method-incomplete")


if __name__ == "__main__":
    unittest.main()
