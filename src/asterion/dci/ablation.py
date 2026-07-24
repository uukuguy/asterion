"""Closed deterministic paper and bounded DCI ablation matrices."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from asterion.dci.context_profiles import resolve_context_profile
from asterion.dci.paper_benchmarks import (
    canonical_sha256,
    resolve_paper_experiment_scope,
)


PAPER_ABLATION_SCHEMA = "dci.paper-ablation-matrix/v1"
BOUNDED_CORPUS_SCHEMA = "dci.paper-bounded-corpus-manifests/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXPECTED_ARTIFACT_SCHEMAS = (
    "asterion.dci.batch-analysis/v1",
    "asterion.dci.batch-item/v1",
    "dci.trajectory-resolution/v1",
)
_EXPECTED_ROWS = tuple(
    sorted(
        (
            *(f"bounded.context.level{level}" for level in range(5)),
            "bounded.corpus.base",
            "bounded.corpus.base-plus-one",
            "bounded.corpus.base-plus-two",
            "bounded.tools.read-bash",
            "bounded.tools.read-grep",
            *(f"paper.context.level{level}" for level in range(5)),
            "paper.corpus.100000",
            "paper.corpus.200000",
            "paper.corpus.400000",
            "paper.tools.read-bash",
            "paper.tools.read-grep",
        )
    )
)
_ROW_FIELDS = frozenset(
    {
        "row_id",
        "ablation_kind",
        "axis_value",
        "execution_class",
        "runtime_id",
        "query_scope_id",
        "query_fixture_id",
        "query_selected_ids_sha256",
        "context_profile",
        "tools",
        "corpus_manifest_id",
        "corpus_manifest_sha256",
        "fineweb_source",
        "fineweb_target_count",
        "fineweb_selection_status",
        "fineweb_revision",
        "fineweb_selection_seed",
        "fineweb_selection_algorithm",
        "fineweb_selected_ids_sha256",
        "max_turns",
        "provider",
        "model",
        "segment_characters",
        "alignment_version",
        "read_minimum_evidence_overlap",
        "expected_artifact_schemas",
        "cost_class",
        "executable_default",
    }
)


@dataclass(frozen=True, slots=True)
class BoundedCorpusDocument:
    resource: str
    sha256: str


@dataclass(frozen=True, slots=True)
class BoundedCorpusManifest:
    manifest_id: str
    documents: tuple[BoundedCorpusDocument, ...]
    identity_sha256: str


@dataclass(frozen=True, slots=True)
class PaperAblationRow:
    row_id: str
    ablation_kind: str
    axis_value: str
    execution_class: str
    runtime_id: str
    query_scope_id: str | None
    query_fixture_id: str | None
    query_selected_ids_sha256: str | None
    context_profile: str
    tools: tuple[str, ...]
    corpus_manifest_id: str | None
    corpus_manifest_sha256: str | None
    fineweb_source: str | None
    fineweb_target_count: int | None
    fineweb_selection_status: str
    fineweb_revision: str | None
    fineweb_selection_seed: int | None
    fineweb_selection_algorithm: str | None
    fineweb_selected_ids_sha256: str | None
    max_turns: int
    provider: str | None
    model: str | None
    segment_characters: int
    alignment_version: str
    read_minimum_evidence_overlap: float
    expected_artifact_schemas: tuple[str, ...]
    cost_class: str
    executable_default: bool
    identity_sha256: str

    def to_mapping(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("identity_sha256")
        value["tools"] = list(self.tools)
        value["expected_artifact_schemas"] = list(self.expected_artifact_schemas)
        return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _load_json_resource(name: str) -> dict[str, Any]:
    try:
        raw = resources.files("asterion.dci.resources").joinpath(name).read_text(
            encoding="utf-8"
        )
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError):
        raise RuntimeError("DCI paper ablation contract is invalid") from None
    if type(value) is not dict:
        raise RuntimeError("DCI paper ablation contract is invalid")
    return value


def _safe_resource(value: object) -> bool:
    if type(value) is not str or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _text(value: object) -> bool:
    return type(value) is str and bool(value)


@lru_cache(maxsize=1)
def _bounded_manifests() -> Mapping[str, BoundedCorpusManifest]:
    payload = _load_json_resource("paper-bounded-corpus-manifests.json")
    manifests = payload.get("manifests")
    if (
        set(payload) != {"schema", "manifests"}
        or payload.get("schema") != BOUNDED_CORPUS_SCHEMA
        or type(manifests) is not list
        or len(manifests) != 3
    ):
        raise RuntimeError("DCI paper ablation contract is invalid")
    root = resources.files("asterion.dci.resources")
    parsed: dict[str, BoundedCorpusManifest] = {}
    for item in manifests:
        if (
            type(item) is not dict
            or set(item) != {"manifest_id", "documents"}
            or not _text(item.get("manifest_id"))
            or item["manifest_id"] in parsed
            or type(item.get("documents")) is not list
            or not item["documents"]
        ):
            raise RuntimeError("DCI paper ablation contract is invalid")
        documents: list[BoundedCorpusDocument] = []
        seen: set[str] = set()
        for document in item["documents"]:
            if (
                type(document) is not dict
                or set(document) != {"resource", "sha256"}
                or not _safe_resource(document.get("resource"))
                or document["resource"] in seen
                or _SHA256.fullmatch(str(document.get("sha256"))) is None
            ):
                raise RuntimeError("DCI paper ablation contract is invalid")
            try:
                raw = root.joinpath(document["resource"]).read_bytes()
            except OSError:
                raise RuntimeError("DCI paper ablation contract is invalid") from None
            if hashlib.sha256(raw).hexdigest() != document["sha256"]:
                raise RuntimeError("DCI paper ablation contract is invalid")
            seen.add(document["resource"])
            documents.append(BoundedCorpusDocument(**document))
        parsed[item["manifest_id"]] = BoundedCorpusManifest(
            manifest_id=item["manifest_id"],
            documents=tuple(documents),
            identity_sha256=canonical_sha256(item),
        )
    expected = (
        "tiny.base/v1",
        "tiny.base-plus-one/v1",
        "tiny.base-plus-two/v1",
    )
    if tuple(parsed) != expected or tuple(len(value.documents) for value in parsed.values()) != (1, 2, 3):
        raise RuntimeError("DCI paper ablation contract is invalid")
    def document_identity(
        manifest: BoundedCorpusManifest,
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (PurePosixPath(document.resource).name, document.sha256)
            for document in manifest.documents
        )

    base = document_identity(parsed["tiny.base/v1"])
    plus_one = tuple(
        document_identity(parsed["tiny.base-plus-one/v1"])
    )
    plus_two = tuple(
        document_identity(parsed["tiny.base-plus-two/v1"])
    )
    if plus_one[:1] != base or plus_two[:2] != plus_one:
        raise RuntimeError("DCI paper ablation contract is invalid")
    return MappingProxyType(parsed)


def _validate_schema() -> None:
    schema = _load_json_resource("paper-ablation.schema.json")
    try:
        row = schema["$defs"]["row"]
    except (KeyError, TypeError):
        raise RuntimeError("DCI paper ablation contract is invalid") from None
    if (
        set(schema)
        != {
            "$schema",
            "$id",
            "type",
            "additionalProperties",
            "required",
            "properties",
            "$defs",
        }
        or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or schema.get("$id") != PAPER_ABLATION_SCHEMA
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or schema.get("required") != ["schema", "rows"]
        or set(schema.get("$defs", {})) != {"row"}
        or type(row) is not dict
        or set(row) != {"type", "additionalProperties", "required", "properties"}
        or row.get("type") != "object"
        or row.get("additionalProperties") is not False
        or set(row.get("required", ())) != _ROW_FIELDS
        or set(row.get("properties", {})) != _ROW_FIELDS
        or row["properties"].get("execution_class")
        != {"enum": ["paper-full", "bounded-fixture"]}
        or row["properties"].get("context_profile")
        != {"enum": ["level0", "level1", "level2", "level3", "level4"]}
        or row["properties"].get("tools")
        != {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {"enum": ["read", "grep", "bash"]},
        }
        or row["properties"].get("fineweb_selection_status")
        != {"enum": ["not-applicable", "paper-unreported"]}
        or row["properties"].get("cost_class")
        != {"enum": ["paper-full", "bounded-tiny"]}
        or row["properties"].get("executable_default") != {"const": False}
        or schema.get("properties", {}).get("schema")
        != {"const": PAPER_ABLATION_SCHEMA}
        or schema.get("properties", {}).get("rows")
        != {
            "type": "array",
            "minItems": 20,
            "maxItems": 20,
            "items": {"$ref": "#/$defs/row"},
        }
    ):
        raise RuntimeError("DCI paper ablation contract is invalid")


def _basic_row_valid(item: dict[str, object]) -> bool:
    nullable_text = (
        "query_scope_id",
        "query_fixture_id",
        "query_selected_ids_sha256",
        "corpus_manifest_id",
        "corpus_manifest_sha256",
        "fineweb_source",
        "fineweb_revision",
        "fineweb_selection_algorithm",
        "fineweb_selected_ids_sha256",
        "provider",
        "model",
    )
    return (
        set(item) == _ROW_FIELDS
        and all(_text(item.get(field)) for field in ("row_id", "ablation_kind", "axis_value", "execution_class", "runtime_id", "context_profile", "alignment_version", "cost_class"))
        and all(item.get(field) is None or _text(item.get(field)) for field in nullable_text)
        and item.get("ablation_kind") in {"context", "corpus", "tools"}
        and item.get("execution_class") in {"paper-full", "bounded-fixture"}
        and type(item.get("tools")) is list
        and tuple(item["tools"]) in {("read", "grep"), ("read", "bash")}
        and type(item.get("max_turns")) is int
        and item["max_turns"] > 0
        and type(item.get("segment_characters")) is int
        and item["segment_characters"] > 0
        and type(item.get("read_minimum_evidence_overlap")) is float
        and 0.0 < item["read_minimum_evidence_overlap"] <= 1.0
        and item.get("alignment_version") == "dci.paper-alignment/v1"
        and type(item.get("expected_artifact_schemas")) is list
        and tuple(item["expected_artifact_schemas"]) == _EXPECTED_ARTIFACT_SCHEMAS
        and item.get("executable_default") is False
    )


def _paper_row_valid(item: dict[str, object]) -> bool:
    kind = item["ablation_kind"]
    scope_id = (
        "browsecomp-plus.context-ablation.random100"
        if kind == "context"
        else "browsecomp-plus.analysis.n100"
    )
    try:
        scope = resolve_paper_experiment_scope(scope_id)
    except ValueError:
        return False
    common = (
        item["execution_class"] == "paper-full"
        and item["query_scope_id"] == scope_id
        and item["query_selected_ids_sha256"] == scope.selected_ids_sha256
        and item["query_fixture_id"] is None
        and item["corpus_manifest_id"] is None
        and item["corpus_manifest_sha256"] is None
        and item["cost_class"] == "paper-full"
        and item["max_turns"] == 300
        and _text(item["provider"])
        and _text(item["model"])
    )
    if not common:
        return False
    if kind == "context":
        return (
            item["runtime_id"] == "dci-agent-lite"
            and item["axis_value"] == item["context_profile"]
            and item["tools"] == ["read", "bash"]
            and item["provider"] == "openai"
            and item["model"] == "gpt-5.4-nano"
            and item["fineweb_selection_status"] == "not-applicable"
            and all(
                item[field] is None
                for field in (
                    "fineweb_source",
                    "fineweb_target_count",
                    "fineweb_revision",
                    "fineweb_selection_seed",
                    "fineweb_selection_algorithm",
                    "fineweb_selected_ids_sha256",
                )
            )
        )
    if kind == "tools":
        return (
            item["runtime_id"] == "dci-agent-lite"
            and item["axis_value"] == "-".join(item["tools"])
            and item["context_profile"] == "level4"
            and item["provider"] == "openai"
            and item["model"] == "gpt-5.4-nano"
            and item["fineweb_selection_status"] == "not-applicable"
            and all(
                item[field] is None
                for field in (
                    "fineweb_source",
                    "fineweb_target_count",
                    "fineweb_revision",
                    "fineweb_selection_seed",
                    "fineweb_selection_algorithm",
                    "fineweb_selected_ids_sha256",
                )
            )
        )
    unavailable = (
        "fineweb_revision",
        "fineweb_selection_seed",
        "fineweb_selection_algorithm",
        "fineweb_selected_ids_sha256",
    )
    return (
        item["runtime_id"] == "dci-agent-claude-code"
        and item["provider"] == "anthropic"
        and item["model"] == "claude-sonnet-4.6"
        and item["context_profile"] == "level4"
        and item["tools"] == ["read", "bash"]
        and item["fineweb_source"] == "HuggingFaceFW/fineweb"
        and item["fineweb_target_count"] in {100_000, 200_000, 400_000}
        and item["axis_value"] == str(item["fineweb_target_count"])
        and item["fineweb_selection_status"] == "paper-unreported"
        and all(item[field] is None for field in unavailable)
    )


def _bounded_row_valid(item: dict[str, object]) -> bool:
    manifest = _bounded_manifests().get(item["corpus_manifest_id"])
    fineweb_fields = (
        "fineweb_source",
        "fineweb_target_count",
        "fineweb_revision",
        "fineweb_selection_seed",
        "fineweb_selection_algorithm",
        "fineweb_selected_ids_sha256",
    )
    common = (
        item["execution_class"] == "bounded-fixture"
        and item["runtime_id"] == "asterion.dci.pi/v1"
        and item["query_scope_id"] is None
        and item["query_selected_ids_sha256"] is None
        and item["query_fixture_id"] == "browsecomp-plus.tiny/v1"
        and manifest is not None
        and item["corpus_manifest_sha256"] == manifest.identity_sha256
        and item["fineweb_selection_status"] == "not-applicable"
        and all(item[field] is None for field in fineweb_fields)
        and item["provider"] is None
        and item["model"] is None
        and item["cost_class"] == "bounded-tiny"
        and item["max_turns"] == 8
    )
    if not common:
        return False
    kind = item["ablation_kind"]
    if kind == "context":
        return (
            item["axis_value"] == item["context_profile"]
            and item["tools"] == ["read", "bash"]
            and item["corpus_manifest_id"] == "tiny.base/v1"
        )
    if kind == "tools":
        return (
            item["axis_value"] == "-".join(item["tools"])
            and item["context_profile"] == "level4"
            and item["corpus_manifest_id"] == "tiny.base/v1"
        )
    expected_manifest = {
        "base": "tiny.base/v1",
        "base-plus-one": "tiny.base-plus-one/v1",
        "base-plus-two": "tiny.base-plus-two/v1",
    }.get(item["axis_value"])
    return (
        expected_manifest is not None
        and item["corpus_manifest_id"] == expected_manifest
        and item["context_profile"] == "level4"
        and item["tools"] == ["read", "bash"]
    )


@lru_cache(maxsize=1)
def _matrix() -> Mapping[str, PaperAblationRow]:
    _validate_schema()
    payload = _load_json_resource("paper-ablation-matrix.json")
    rows = payload.get("rows")
    if (
        set(payload) != {"schema", "rows"}
        or payload.get("schema") != PAPER_ABLATION_SCHEMA
        or type(rows) is not list
        or len(rows) != 20
    ):
        raise RuntimeError("DCI paper ablation contract is invalid")
    parsed: dict[str, PaperAblationRow] = {}
    for item in rows:
        if type(item) is not dict or not _basic_row_valid(item):
            raise RuntimeError("DCI paper ablation contract is invalid")
        row_id = item["row_id"]
        if row_id in parsed:
            raise RuntimeError("DCI paper ablation contract is invalid")
        try:
            resolve_context_profile(item["context_profile"])
        except ValueError:
            raise RuntimeError("DCI paper ablation contract is invalid") from None
        if not (
            _paper_row_valid(item)
            if item["execution_class"] == "paper-full"
            else _bounded_row_valid(item)
        ):
            raise RuntimeError("DCI paper ablation contract is invalid")
        converted = dict(item)
        converted["tools"] = tuple(item["tools"])
        converted["expected_artifact_schemas"] = tuple(
            item["expected_artifact_schemas"]
        )
        parsed[row_id] = PaperAblationRow(
            **converted, identity_sha256=canonical_sha256(item)
        )
    if tuple(parsed) != _EXPECTED_ROWS:
        raise RuntimeError("DCI paper ablation contract is invalid")
    if len({row.identity_sha256 for row in parsed.values()}) != len(parsed):
        raise RuntimeError("DCI paper ablation contract is invalid")
    return MappingProxyType(parsed)


def paper_ablation_row_ids() -> tuple[str, ...]:
    return tuple(_matrix())


def resolve_paper_ablation_row(value: object) -> PaperAblationRow:
    if type(value) is not str or value not in _matrix():
        raise ValueError("DCI paper ablation row is invalid")
    return _matrix()[value]


def resolve_bounded_corpus_manifest(value: object) -> BoundedCorpusManifest:
    if type(value) is not str or value not in _bounded_manifests():
        raise ValueError("DCI bounded corpus manifest is invalid")
    return _bounded_manifests()[value]


def validate_paper_ablation_matrix() -> int:
    return len(_matrix())


def render_paper_ablation_matrix() -> str:
    payload = {
        "schema": PAPER_ABLATION_SCHEMA,
        "rows": [row.to_mapping() for row in _matrix().values()],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def paper_ablation_matrix_sha256() -> str:
    return canonical_sha256(
        {
            "schema": PAPER_ABLATION_SCHEMA,
            "rows": [row.to_mapping() for row in _matrix().values()],
        }
    )


def render_paper_ablation_command(row_id: object) -> str:
    row = resolve_paper_ablation_row(row_id)
    if row.execution_class == "paper-full":
        return f"# NON-EXECUTABLE paper-full row: {row.row_id}"
    return (
        f"asterion-dci benchmark --ablation-row {row.row_id} "
        f"--output-root outputs/asterion-dci-ablation/{row.row_id}"
    )


def require_af320_executable_ablation(
    row_id: object, *, benchmark_authorized: bool
) -> PaperAblationRow:
    row = resolve_paper_ablation_row(row_id)
    if row.execution_class == "paper-full":
        raise ValueError("DCI paper ablation row is not executable in AF-320")
    if benchmark_authorized is not True:
        raise ValueError("DCI bounded benchmark authorization is required")
    return row


def bounded_ablation_input_paths(row_id: object) -> tuple[Path, Path]:
    """Resolve one bounded row only to hash-verified installed resources."""

    row = resolve_paper_ablation_row(row_id)
    if row.execution_class != "bounded-fixture" or row.corpus_manifest_id is None:
        raise ValueError("DCI paper ablation row is not executable in AF-320")
    manifest = resolve_bounded_corpus_manifest(row.corpus_manifest_id)
    root = resources.files("asterion.dci.resources")
    dataset = Path(str(root.joinpath("paper-fixtures/qa.jsonl")))
    documents = tuple(Path(str(root.joinpath(item.resource))) for item in manifest.documents)
    corpus_parents = {document.parent for document in documents}
    if (
        len(corpus_parents) != 1
        or not dataset.is_file()
        or dataset.is_symlink()
        or any(not document.is_file() or document.is_symlink() for document in documents)
    ):
        raise RuntimeError("DCI paper ablation contract is invalid")
    corpus = next(iter(corpus_parents))
    if corpus.is_symlink() or not corpus.is_dir():
        raise RuntimeError("DCI paper ablation contract is invalid")
    expected_names = {document.name for document in documents}
    try:
        actual_names = {item.name for item in corpus.iterdir()}
    except OSError:
        raise RuntimeError("DCI paper ablation contract is invalid") from None
    if actual_names != expected_names:
        raise RuntimeError("DCI paper ablation contract is invalid")
    return dataset.resolve(strict=True), corpus.resolve(strict=True)


def bounded_ablation_resolution_registry_path() -> Path:
    """Resolve the installed tiny QA gold registry without CWD fallback."""

    root = resources.files("asterion.dci.resources")
    registry = Path(str(root.joinpath("paper-fixtures/gold/qa-registry.json")))
    manifest = registry.parent / "qa-manifest.json"
    if (
        not registry.is_file()
        or registry.is_symlink()
        or not manifest.is_file()
        or manifest.is_symlink()
    ):
        raise RuntimeError("DCI paper ablation contract is invalid")
    return registry.resolve(strict=True)
