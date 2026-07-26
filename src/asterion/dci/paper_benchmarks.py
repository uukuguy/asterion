"""Closed paper benchmark and experiment-scope identity contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


PAPER_BENCHMARK_SCHEMA = "dci.paper-benchmark-inventory/v1"
PAPER_EXPERIMENT_SCOPE_SCHEMA = "dci.paper-experiment-scopes/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXPECTED_DATASET_IDS = (
    "beir.arguana",
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "browsecomp-plus",
    "qa.2wikimultihopqa",
    "qa.bamboogle",
    "qa.hotpotqa",
    "qa.musique",
    "qa.nq",
    "qa.triviaqa",
)
_EXPECTED_SCOPE_IDS = (
    "beir.arguana.main.random50",
    "beir.scifact.main.random50",
    "bright.biology.main.full",
    "bright.earth-science.main.full",
    "bright.economics.main.full",
    "bright.robotics.main.full",
    "browsecomp-plus.analysis.n100",
    "browsecomp-plus.appendix-a1.random50",
    "browsecomp-plus.context-ablation.random100",
    "browsecomp-plus.main.all830",
    "qa.2wikimultihopqa.main.random50",
    "qa.bamboogle.main.full",
    "qa.hotpotqa.main.random50",
    "qa.musique.main.random50",
    "qa.nq.main.random50",
    "qa.triviaqa.main.random50",
)
_EXPECTED_ALL_SCOPE_IDS = _EXPECTED_SCOPE_IDS + (
    "qa.bamboogle.upstream.sample50",
)
_PAPER_SOURCE_REFERENCE = "arxiv:2605.05242v1"
_UPSTREAM_BAMBOOGLE_SOURCE_REFERENCE = (
    "github:DCI-Agent/DCI-Agent-Lite@271f37e71f053bf0c99c05ce6d2fb53b841d922e;"
    "hf:datasets/DCI-Agent/dci-bench@7fdd41059ef06df2a22d10d0f704768d44f1031b"
    "#data/bamboogle/test.jsonl"
)
_PAPER_PROFILE_SCOPES = {
    "beir.arguana": "beir.arguana.main.random50",
    "beir.scifact": "beir.scifact.main.random50",
    "bright.biology": "bright.biology.main.full",
    "bright.earth-science": "bright.earth-science.main.full",
    "bright.economics": "bright.economics.main.full",
    "bright.robotics": "bright.robotics.main.full",
    "bcplus.level3": "browsecomp-plus.main.all830",
    "bcplus.openai": "browsecomp-plus.main.all830",
    "qa.2wikimultihopqa": "qa.2wikimultihopqa.main.random50",
    "qa.hotpotqa": "qa.hotpotqa.main.random50",
    "qa.musique": "qa.musique.main.random50",
    "qa.nq": "qa.nq.main.random50",
    "qa.triviaqa": "qa.triviaqa.main.random50",
}
_DATASET_FIELDS = frozenset(
    {
        "dataset_id",
        "family",
        "mode",
        "source_split",
        "source_count",
        "exclusion_policy",
        "dataset_path",
        "corpus_path",
        "gold_field",
        "metric",
        "judge_contract",
        "bounded_fixture",
        "batch_profile",
        "launcher",
        "source_family",
        "source_reference",
        "launcher_origin",
        "selection_kind",
        "selection_count",
        "selection_seed_status",
        "execution_class",
    }
)
_SCOPE_FIELDS = frozenset(
    {
        "scope_id",
        "dataset_id",
        "experiment",
        "source_family",
        "source_reference",
        "launcher_origin",
        "selection_mode",
        "selection_kind",
        "selection_count",
        "selection_seed",
        "selection_seed_status",
        "selection_algorithm",
        "selected_ids_sha256",
        "execution_class",
    }
)
_DATASET_PROPERTY_SCHEMAS = {
    "dataset_id": {"type": "string", "minLength": 1},
    "family": {"enum": ["agentic-search", "knowledge-qa", "ir"]},
    "mode": {"enum": ["qa", "ir"]},
    "source_split": {"type": "string", "minLength": 1},
    "source_count": {"type": "integer", "minimum": 1},
    "exclusion_policy": {"type": "string", "minLength": 1},
    "dataset_path": {"type": "string", "minLength": 1},
    "corpus_path": {"type": "string", "minLength": 1},
    "gold_field": {"enum": ["answer", "gold_ids"]},
    "metric": {"enum": ["llm-answer-correctness", "ndcg@10-binary-deduplicated"]},
    "judge_contract": {"type": ["string", "null"]},
    "bounded_fixture": {"type": "string", "minLength": 1},
    "batch_profile": {"type": ["string", "null"], "minLength": 1},
    "launcher": {"type": ["string", "null"], "minLength": 1},
    "source_family": {"const": "paper-reference"},
    "source_reference": {"const": _PAPER_SOURCE_REFERENCE},
    "launcher_origin": {"enum": ["upstream-github", "asterion-added"]},
    "selection_kind": {"const": "full"},
    "selection_count": {"type": "integer", "minimum": 1},
    "selection_seed_status": {"const": "reported"},
    "execution_class": {"const": "paper-full"},
}
_SCOPE_PROPERTY_SCHEMAS = {
    "scope_id": {"type": "string", "minLength": 1},
    "dataset_id": {"type": "string", "minLength": 1},
    "experiment": {"type": "string", "minLength": 1},
    "source_family": {"enum": ["paper-reference", "upstream-github"]},
    "source_reference": {"type": "string", "minLength": 1},
    "launcher_origin": {
        "enum": ["upstream-github", "asterion-added", "unavailable"]
    },
    "selection_mode": {
        "enum": ["all", "deterministic-sample", "random-sample", "fixed-selected-ids"]
    },
    "selection_kind": {"enum": ["full", "random-sample", "fixed-selected-ids"]},
    "selection_count": {"type": "integer", "minimum": 1},
    "selection_seed": {"type": ["integer", "null"], "minimum": 0},
    "selection_seed_status": {
        "enum": ["reported", "asterion-defined", "paper-unreported"]
    },
    "selection_algorithm": {"type": "string", "minLength": 1},
    "selected_ids_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "execution_class": {"enum": ["paper-full", "upstream-reference"]},
}


def canonical_sha256(value: object) -> str:
    """Hash canonical UTF-8 JSON with a terminal newline."""

    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetInputBinding:
    raw_content_sha256: str
    paper_benchmark_identity_sha256: str
    device: int
    inode: int

    def __post_init__(self) -> None:
        _dataset_input_binding_identity(self)


_DatasetInputBindingIdentity = tuple[str, str, int, int]


def _dataset_input_binding_identity(
    binding: object,
) -> _DatasetInputBindingIdentity:
    if type(binding) is not DatasetInputBinding:
        raise ValueError("DCI dataset input binding is invalid")
    raw_content_sha256 = binding.raw_content_sha256
    paper_benchmark_identity_sha256 = (
        binding.paper_benchmark_identity_sha256
    )
    device = binding.device
    inode = binding.inode
    if (
        type(raw_content_sha256) is not str
        or _SHA256.fullmatch(raw_content_sha256) is None
        or type(paper_benchmark_identity_sha256) is not str
        or _SHA256.fullmatch(paper_benchmark_identity_sha256) is None
        or type(device) is not int
        or device < 0
        or type(inode) is not int
        or inode < 1
    ):
        raise ValueError("DCI dataset input binding is invalid")
    return (
        raw_content_sha256,
        paper_benchmark_identity_sha256,
        device,
        inode,
    )


def _dataset_input_binding_matches(
    binding: object,
    expected: _DatasetInputBindingIdentity,
) -> bool:
    try:
        actual = _dataset_input_binding_identity(binding)
    except ValueError:
        return False
    return (
        actual[0] == expected[0]
        and actual[1] == expected[1]
        and actual[2] == expected[2]
        and actual[3] == expected[3]
    )


def _copy_dataset_input_binding(
    identity: _DatasetInputBindingIdentity,
) -> DatasetInputBinding:
    return DatasetInputBinding(
        raw_content_sha256=identity[0],
        paper_benchmark_identity_sha256=identity[1],
        device=identity[2],
        inode=identity[3],
    )


@dataclass(frozen=True, slots=True)
class PaperBenchmark:
    dataset_id: str
    family: str
    mode: str
    source_split: str
    source_count: int
    exclusion_policy: str
    dataset_path: str
    corpus_path: str
    gold_field: str
    metric: str
    judge_contract: str | None
    bounded_fixture: str
    batch_profile: str | None
    launcher: str | None
    source_family: str
    source_reference: str
    launcher_origin: str
    selection_kind: str
    selection_count: int
    selection_seed_status: str
    execution_class: str
    identity_sha256: str


def _open_paper_dataset_descriptor(path: Path) -> int:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.anchor != os.path.sep
        or len(path.parts) < 2
        or any(part in ("", ".", "..") for part in path.parts[1:])
    ):
        raise ValueError("DCI paper benchmark dataset binding is invalid")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_descriptor = os.open(path.anchor, directory_flags)
    try:
        root_metadata = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise ValueError(
                "DCI paper benchmark dataset binding is invalid"
            )
        for component in path.parts[1:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            try:
                metadata = os.fstat(next_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise ValueError(
                        "DCI paper benchmark dataset binding is invalid"
                    )
            except BaseException:
                os.close(next_descriptor)
                raise
            previous_descriptor = directory_descriptor
            directory_descriptor = next_descriptor
            os.close(previous_descriptor)
        dataset_descriptor = os.open(
            path.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptor,
        )
        parent_descriptor = directory_descriptor
        directory_descriptor = -1
        try:
            os.close(parent_descriptor)
        except BaseException:
            os.close(dataset_descriptor)
            raise
        return dataset_descriptor
    finally:
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def _read_paper_dataset_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def read_paper_benchmark_dataset(
    path: Path,
    benchmark: PaperBenchmark,
) -> tuple[bytes, DatasetInputBinding]:
    """Read one exact regular dataset descriptor and bind its raw bytes."""

    if type(benchmark) is not PaperBenchmark:
        raise ValueError("DCI paper benchmark dataset binding is invalid")
    descriptor = _open_paper_dataset_descriptor(path)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("DCI paper benchmark dataset binding is invalid")
        raw = _read_paper_dataset_descriptor(descriptor)
    finally:
        os.close(descriptor)
    return raw, DatasetInputBinding(
        raw_content_sha256=hashlib.sha256(raw).hexdigest(),
        paper_benchmark_identity_sha256=benchmark.identity_sha256,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


@dataclass(frozen=True, slots=True)
class PaperExperimentScope:
    scope_id: str
    dataset_id: str
    experiment: str
    source_family: str
    source_reference: str
    launcher_origin: str
    selection_mode: str
    selection_kind: str
    selection_count: int
    selection_seed: int | None
    selection_seed_status: str
    selection_algorithm: str
    selected_ids_sha256: str
    execution_class: str
    identity_sha256: str


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _load_resource(name: str, schema: str, collection: str) -> dict[str, Any]:
    try:
        raw = resources.files("asterion.dci.resources").joinpath(name).read_text(
            encoding="utf-8"
        )
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError):
        raise RuntimeError("DCI paper benchmark contract is invalid") from None
    if (
        type(payload) is not dict
        or set(payload) != {"schema", collection}
        or payload.get("schema") != schema
        or type(payload.get(collection)) is not list
    ):
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return payload


def _load_json_resource(name: str) -> dict[str, Any]:
    try:
        raw = resources.files("asterion.dci.resources").joinpath(name).read_text(
            encoding="utf-8"
        )
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError):
        raise RuntimeError("DCI paper benchmark contract is invalid") from None
    if type(value) is not dict:
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return value


def _validate_closed_schema(
    name: str,
    *,
    schema_id: str,
    collection: str,
    definition: str,
    fields: frozenset[str],
    count: int,
    property_schemas: Mapping[str, object],
) -> None:
    schema = _load_json_resource(name)
    try:
        item = schema["$defs"][definition]
        required = item["required"]
        properties = item["properties"]
    except (KeyError, TypeError):
        raise RuntimeError("DCI paper benchmark contract is invalid") from None
    if (
        set(schema)
        != {"$schema", "$id", "type", "additionalProperties", "required", "properties", "$defs"}
        or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or schema.get("$id") != schema_id
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or schema.get("required") != ["schema", collection]
        or schema.get("properties")
        != {
            "schema": {"const": schema_id},
            collection: {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {"$ref": f"#/$defs/{definition}"},
            },
        }
        or set(schema.get("$defs", {})) != {definition}
        or set(item) != {"type", "additionalProperties", "required", "properties"}
        or item.get("type") != "object"
        or item.get("additionalProperties") is not False
        or type(required) is not list
        or set(required) != fields
        or type(properties) is not dict
        or set(properties) != fields
        or properties != property_schemas
    ):
        raise RuntimeError("DCI paper benchmark contract is invalid")


@lru_cache(maxsize=1)
def _batch_profiles() -> Mapping[str, Mapping[str, object]]:
    payload = _load_json_resource("batch-profiles.json")
    profiles = payload.get("profiles")
    if (
        set(payload) != {"schema", "profiles"}
        or payload.get("schema") != "asterion.dci.batch-profiles/v1"
        or type(profiles) is not dict
    ):
        raise RuntimeError("DCI paper benchmark contract is invalid")
    parsed: dict[str, Mapping[str, object]] = {}
    for name, value in profiles.items():
        if type(name) is not str or not name or type(value) is not dict:
            raise RuntimeError("DCI paper benchmark contract is invalid")
        parsed[name] = MappingProxyType(dict(value))
    return MappingProxyType(parsed)


@lru_cache(maxsize=1)
def _fixture_ids() -> Mapping[str, tuple[str, str]]:
    payload = _load_json_resource("paper-bounded-fixtures.json")
    artifacts = payload.get("artifacts")
    fixtures = payload.get("fixtures")
    if (
        set(payload) != {"schema", "artifacts", "fixtures"}
        or payload.get("schema") != "dci.paper-bounded-fixtures/v1"
        or type(artifacts) is not dict
        or set(artifacts) != {"ir/v1", "qa/v1"}
        or type(fixtures) is not list
    ):
        raise RuntimeError("DCI paper benchmark contract is invalid")
    resource_root = resources.files("asterion.dci.resources")
    for artifact in artifacts.values():
        if (
            type(artifact) is not dict
            or set(artifact)
            != {
                "dataset_resource",
                "dataset_sha256",
                "corpus_document_resource",
                "corpus_document_sha256",
            }
        ):
            raise RuntimeError("DCI paper benchmark contract is invalid")
        for resource_field, digest_field in (
            ("dataset_resource", "dataset_sha256"),
            ("corpus_document_resource", "corpus_document_sha256"),
        ):
            resource_name = artifact[resource_field]
            digest = artifact[digest_field]
            if (
                type(resource_name) is not str
                or not _is_safe_relative_path(resource_name)
                or _SHA256.fullmatch(str(digest)) is None
            ):
                raise RuntimeError("DCI paper benchmark contract is invalid")
            try:
                raw = resource_root.joinpath(resource_name).read_bytes()
            except OSError:
                raise RuntimeError("DCI paper benchmark contract is invalid") from None
            if hashlib.sha256(raw).hexdigest() != digest:
                raise RuntimeError("DCI paper benchmark contract is invalid")
    parsed: dict[str, tuple[str, str]] = {}
    for item in fixtures:
        if (
            type(item) is not dict
            or set(item)
            != {"fixture_id", "dataset_id", "mode", "artifact_id", "execution_class"}
            or type(item.get("fixture_id")) is not str
            or item["fixture_id"] in parsed
            or item.get("mode") not in {"qa", "ir"}
            or item.get("artifact_id") != f"{item.get('mode')}/v1"
            or item.get("artifact_id") not in artifacts
            or item.get("execution_class") != "bounded-fixture"
        ):
            raise RuntimeError("DCI paper benchmark contract is invalid")
        parsed[item["fixture_id"]] = (item.get("dataset_id"), item["mode"])
    return MappingProxyType(parsed)


@lru_cache(maxsize=1)
def _published_manifests() -> Mapping[str, tuple[str, ...]]:
    payload = _load_json_resource("paper-selected-id-manifests.json")
    manifests = payload.get("manifests")
    if (
        set(payload) != {"schema", "manifests"}
        or payload.get("schema") != "dci.paper-selected-id-manifests/v1"
        or type(manifests) is not dict
    ):
        raise RuntimeError("DCI paper benchmark contract is invalid")
    parsed: dict[str, tuple[str, ...]] = {}
    for scope_id, values in manifests.items():
        if (
            type(scope_id) is not str
            or type(values) is not list
            or not values
            or any(type(value) is not str or not value for value in values)
            or values != sorted(values)
            or len(values) != len(set(values))
        ):
            raise RuntimeError("DCI paper benchmark contract is invalid")
        parsed[scope_id] = tuple(values)
    return MappingProxyType(parsed)


def _is_safe_relative_path(value: str) -> bool:
    from pathlib import PurePosixPath

    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _is_launcher_path(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("scripts/")
        and _is_safe_relative_path(value)
    )


def _require_string(value: object) -> str:
    if type(value) is not str or not value:
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return value


@lru_cache(maxsize=1)
def _benchmarks() -> Mapping[str, PaperBenchmark]:
    _validate_closed_schema(
        "paper-benchmark.schema.json",
        schema_id=PAPER_BENCHMARK_SCHEMA,
        collection="datasets",
        definition="dataset",
        fields=_DATASET_FIELDS,
        count=13,
        property_schemas=_DATASET_PROPERTY_SCHEMAS,
    )
    payload = _load_resource(
        "paper-benchmarks.json", PAPER_BENCHMARK_SCHEMA, "datasets"
    )
    profiles = _batch_profiles()
    fixtures = _fixture_ids()
    parsed: dict[str, PaperBenchmark] = {}
    for item in payload["datasets"]:
        if type(item) is not dict or set(item) != _DATASET_FIELDS:
            raise RuntimeError("DCI paper benchmark contract is invalid")
        dataset_id = _require_string(item["dataset_id"])
        source_count = item["source_count"]
        judge_contract = item["judge_contract"]
        family = item["family"]
        mode = item["mode"]
        profile = profiles.get(item["batch_profile"])
        fixture = fixtures.get(item["bounded_fixture"])
        qa_contract = (
            mode == "qa"
            and family in {"agentic-search", "knowledge-qa"}
            and item["gold_field"] == "answer"
            and item["metric"] == "llm-answer-correctness"
            and judge_contract == "dci.paper-answer-judge/gpt-4.1/v1"
        )
        ir_contract = (
            mode == "ir"
            and family == "ir"
            and item["gold_field"] == "gold_ids"
            and item["metric"] == "ndcg@10-binary-deduplicated"
            and judge_contract is None
        )
        bound_profile = (
            profile is not None
            and profile.get("dataset") == item["dataset_path"]
            and profile.get("corpus") == item["corpus_path"]
            and profile.get("mode") == mode
            and _is_launcher_path(item["launcher"])
        )
        intentionally_unbound = (
            dataset_id == "qa.bamboogle"
            and item["batch_profile"] is None
            and item["launcher"] == "scripts/qa/run_bamboogle_test_sample50.sh"
            and item["dataset_path"] == "paper-full/data/bamboogle/test-125.jsonl"
        )
        expected_origin = (
            "asterion-added"
            if dataset_id in {"beir.arguana", "beir.scifact"}
            else "upstream-github"
        )
        source_contract = (
            item["source_family"] == "paper-reference"
            and item["source_reference"] == _PAPER_SOURCE_REFERENCE
            and item["launcher_origin"] == expected_origin
            and item["selection_kind"] == "full"
            and item["selection_count"] == source_count
            and item["selection_seed_status"] == "reported"
        )
        if (
            dataset_id in parsed
            or not (qa_contract or ir_contract)
            or type(source_count) is not int
            or source_count <= 0
            or type(judge_contract) not in {str, type(None)}
            or not (bound_profile or intentionally_unbound)
            or not source_contract
            or fixture != (dataset_id, mode)
            or not _is_safe_relative_path(item["dataset_path"])
            or not _is_safe_relative_path(item["corpus_path"])
            or item["execution_class"] != "paper-full"
        ):
            raise RuntimeError("DCI paper benchmark contract is invalid")
        for field in _DATASET_FIELDS - {
            "source_count",
            "judge_contract",
            "batch_profile",
            "launcher",
            "selection_count",
        }:
            _require_string(item[field])
        parsed[dataset_id] = PaperBenchmark(
            **item, identity_sha256=canonical_sha256(item)
        )
    if tuple(parsed) != _EXPECTED_DATASET_IDS:
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return MappingProxyType(parsed)


@lru_cache(maxsize=1)
def _scopes() -> Mapping[str, PaperExperimentScope]:
    _validate_closed_schema(
        "paper-experiment-scope.schema.json",
        definition="scope",
        fields=_SCOPE_FIELDS,
        schema_id=PAPER_EXPERIMENT_SCOPE_SCHEMA,
        collection="scopes",
        count=17,
        property_schemas=_SCOPE_PROPERTY_SCHEMAS,
    )
    payload = _load_resource(
        "paper-experiment-scopes.json", PAPER_EXPERIMENT_SCOPE_SCHEMA, "scopes"
    )
    datasets = _benchmarks()
    parsed: dict[str, PaperExperimentScope] = {}
    for item in payload["scopes"]:
        if type(item) is not dict or set(item) != _SCOPE_FIELDS:
            raise RuntimeError("DCI paper benchmark contract is invalid")
        scope_id = _require_string(item["scope_id"])
        mode = item["selection_mode"]
        seed = item["selection_seed"]
        seed_status = item["selection_seed_status"]
        algorithm = item["selection_algorithm"]
        dataset = datasets.get(item["dataset_id"])
        published = _published_manifests().get(scope_id)
        paper_selection_contract = (
            mode == "all"
            and seed is None
            and seed_status == "reported"
            and item["selection_kind"] == "full"
            and algorithm == "sorted-selected-id-manifest/v1"
            and published is None
        ) or (
            mode in {"deterministic-sample", "random-sample"}
            and type(seed) is int
            and seed >= 0
            and seed_status == "asterion-defined"
            and item["selection_kind"]
            == ("fixed-selected-ids" if mode == "deterministic-sample" else "random-sample")
            and algorithm == "sha256(seed-colon-id)-ascending/v1"
            and published is None
        ) or (
            mode == "random-sample"
            and seed is None
            and seed_status == "paper-unreported"
            and item["selection_kind"] == "random-sample"
            and algorithm == "published-selected-id-manifest/v1"
            and published is not None
        )
        upstream_selection_contract = (
            scope_id == "qa.bamboogle.upstream.sample50"
            and item["source_family"] == "upstream-github"
            and item["source_reference"] == _UPSTREAM_BAMBOOGLE_SOURCE_REFERENCE
            and item["launcher_origin"] == "upstream-github"
            and mode == "fixed-selected-ids"
            and item["selection_kind"] == "fixed-selected-ids"
            and seed is None
            and seed_status == "reported"
            and algorithm == "pinned-selected-id-manifest/v1"
            and item["execution_class"] == "upstream-reference"
            and published is not None
        )
        expected_origin = (
            "asterion-added"
            if scope_id in {"beir.arguana.main.random50", "beir.scifact.main.random50"}
            else "unavailable"
            if scope_id
            in {
                "browsecomp-plus.analysis.n100",
                "browsecomp-plus.appendix-a1.random50",
                "browsecomp-plus.context-ablation.random100",
                "qa.bamboogle.main.full",
            }
            else "upstream-github"
        )
        paper_source_contract = (
            item["source_family"] == "paper-reference"
            and item["source_reference"] == _PAPER_SOURCE_REFERENCE
            and item["launcher_origin"] == expected_origin
            and item["execution_class"] == "paper-full"
        )
        if (
            scope_id in parsed
            or dataset is None
            or not (upstream_selection_contract or (paper_source_contract and paper_selection_contract))
            or type(item["selection_count"]) is not int
            or item["selection_count"] <= 0
            or (
                item["source_family"] == "paper-reference"
                and item["selection_count"] > dataset.source_count
            )
            or (
                mode == "all"
                and item["selection_count"] != dataset.source_count
            )
            or _SHA256.fullmatch(str(item["selected_ids_sha256"])) is None
            or (
                published is not None
                and (
                    len(published) != item["selection_count"]
                    or canonical_sha256(published) != item["selected_ids_sha256"]
                )
            )
        ):
            raise RuntimeError("DCI paper benchmark contract is invalid")
        for field in _SCOPE_FIELDS - {"selection_count", "selection_seed"}:
            _require_string(item[field])
        parsed[scope_id] = PaperExperimentScope(
            **item, identity_sha256=canonical_sha256(item)
        )
    if tuple(parsed) != _EXPECTED_ALL_SCOPE_IDS:
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return MappingProxyType(parsed)


def paper_benchmark_ids() -> tuple[str, ...]:
    return tuple(_benchmarks())


def paper_experiment_scope_ids() -> tuple[str, ...]:
    _scopes()
    return _EXPECTED_SCOPE_IDS


def all_experiment_scope_ids() -> tuple[str, ...]:
    """Return all source-labelled scopes, including upstream-only references."""

    return tuple(_scopes())


def resolve_paper_benchmark(value: object) -> PaperBenchmark:
    if type(value) is not str or value not in _benchmarks():
        raise ValueError("DCI paper benchmark is invalid")
    return _benchmarks()[value]


def resolve_paper_experiment_scope(value: object) -> PaperExperimentScope:
    if type(value) is not str or value not in _EXPECTED_SCOPE_IDS:
        raise ValueError("DCI paper experiment scope is invalid")
    return _scopes()[value]


def resolve_experiment_scope(value: object) -> PaperExperimentScope:
    """Resolve one source-labelled scope without granting paper authority."""

    if type(value) is not str or value not in _scopes():
        raise ValueError("DCI experiment scope is invalid")
    return _scopes()[value]


def paper_scope_for_profile(profile: object) -> str | None:
    """Return the paper-full scope bound to one exact batch profile, if any."""

    if profile is None:
        return None
    if type(profile) is not str:
        raise ValueError("DCI paper profile is invalid")
    return _PAPER_PROFILE_SCOPES.get(profile)


def paper_scope_for_selected_ids(source_ids: object) -> str | None:
    """Classify an exact paper scope by its complete selected-ID identity."""

    if type(source_ids) not in {list, tuple}:
        raise ValueError("DCI paper selected-ID manifest is invalid")
    values = tuple(source_ids)
    if (
        not values
        or any(type(value) is not str or not value for value in values)
        or len(values) != len(set(values))
    ):
        raise ValueError("DCI paper selected-ID manifest is invalid")
    identity = canonical_sha256(tuple(sorted(values)))
    matches = tuple(
        scope.scope_id
        for scope_id, scope in _scopes().items()
        if scope_id in _EXPECTED_SCOPE_IDS
        and scope.selection_count == len(values)
        and scope.selected_ids_sha256 == identity
    )
    if len(matches) > 1:
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return matches[0] if matches else None


def select_and_verify_scope_ids(
    scope_id: object, source_ids: object
) -> tuple[str, ...]:
    """Apply one closed selection rule and verify its selected-ID manifest."""

    scope = resolve_paper_experiment_scope(scope_id)
    if type(source_ids) not in {list, tuple}:
        raise ValueError("DCI paper selected-ID manifest is invalid")
    values = tuple(source_ids)
    dataset = resolve_paper_benchmark(scope.dataset_id)
    if (
        not values
        or any(type(value) is not str or not value for value in values)
        or len(set(values)) != len(values)
        or len(values) != dataset.source_count
    ):
        raise ValueError("DCI paper selected-ID manifest is invalid")

    if scope.selection_algorithm == "sorted-selected-id-manifest/v1":
        if len(values) != scope.selection_count:
            raise ValueError("DCI paper selected-ID manifest is invalid")
        selected = tuple(sorted(values))
    elif scope.selection_algorithm == "published-selected-id-manifest/v1":
        selected = _published_manifests().get(scope.scope_id, ())
        if len(selected) != scope.selection_count or not set(selected).issubset(values):
            raise ValueError("DCI paper selected-ID manifest is invalid")
    elif scope.selection_algorithm == "sha256(seed-colon-id)-ascending/v1":
        if scope.selection_seed is None:
            raise ValueError("DCI paper selected-ID manifest is invalid")
        prefix = f"{scope.selection_seed}:"
        selected = tuple(
            sorted(
                sorted(
                    values,
                    key=lambda value: (
                        hashlib.sha256((prefix + value).encode("utf-8")).digest(),
                        value,
                    ),
                )[: scope.selection_count]
            )
        )
    else:
        raise ValueError("DCI paper selected-ID manifest is invalid")

    if canonical_sha256(selected) != scope.selected_ids_sha256:
        raise ValueError("DCI paper selected-ID manifest is invalid")
    return selected


def select_and_verify_experiment_scope_ids(
    scope_id: object, source_ids: object
) -> tuple[str, ...]:
    """Verify one source-labelled scope without assuming paper-full input size."""

    scope = resolve_experiment_scope(scope_id)
    if scope.scope_id in _EXPECTED_SCOPE_IDS:
        return select_and_verify_scope_ids(scope_id, source_ids)
    if type(source_ids) not in {list, tuple}:
        raise ValueError("DCI experiment selected-ID manifest is invalid")
    values = tuple(source_ids)
    if (
        len(values) != scope.selection_count
        or any(type(value) is not str or not value for value in values)
        or len(values) != len(set(values))
        or tuple(sorted(values)) != values
        or canonical_sha256(values) != scope.selected_ids_sha256
    ):
        raise ValueError("DCI experiment selected-ID manifest is invalid")
    return values


def published_scope_selected_ids(scope_id: object) -> tuple[str, ...]:
    """Return one exact published selection whose paper seed was unreported."""

    scope = resolve_paper_experiment_scope(scope_id)
    if scope.selection_seed_status != "paper-unreported":
        raise ValueError("DCI paper experiment scope has no published manifest")
    selected = _published_manifests().get(scope.scope_id)
    if selected is None or canonical_sha256(selected) != scope.selected_ids_sha256:
        raise RuntimeError("DCI paper benchmark contract is invalid")
    return selected


def require_af320_executable_scope(
    scope_id: object,
    authorization: object = None,
    dataset_input_binding: DatasetInputBinding | None = None,
) -> None:
    """Require an invocation-authorized AF-340 private output identity."""

    scope = resolve_paper_experiment_scope(scope_id)
    if authorization is None:
        raise ValueError(
            "DCI paper scope is not executable without explicit AF-340 authorization"
        )
    from asterion.dci.experiment_profiles import consume_full_execution_authorization

    consume_full_execution_authorization(
        authorization,
        scope.scope_id,
        dataset_input_binding,
    )


def paper_benchmark_inventory_sha256() -> str:
    return canonical_sha256(
        _load_resource("paper-benchmarks.json", PAPER_BENCHMARK_SCHEMA, "datasets")
    )


def paper_experiment_scopes_sha256() -> str:
    return canonical_sha256(
        _load_resource(
            "paper-experiment-scopes.json",
            PAPER_EXPERIMENT_SCOPE_SCHEMA,
            "scopes",
        )
    )
