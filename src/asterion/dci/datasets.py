"""Strict, deterministic dataset and prompt helpers for Asterion DCI batches."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from asterion.dci.pi_rpc import FINAL_ANSWER_RECOVERY_PROMPT


class DatasetError(ValueError):
    """Safe public error for malformed or ambiguous benchmark input."""


BENCHMARK_PROMPT_CONTRACT = "dci.benchmark-prompt/v1"


_ALLOWED_FIELDS = frozenset({"query_id", "query", "answer", "gold_docs", "gold_ids"})
_BRIGHT_SOURCE_FIELDS = frozenset(
    {
        "answer",
        "excluded_ids",
        "gold_ids",
        "gold_ids_long",
        "id",
        "query",
        "query_id",
        "reasoning",
    }
)
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_AGGREGATE_RESERVED = frozenset(
    {
        "analysis",
        "analysis.json",
        "analysis.jsonl",
        "analysis.md",
        "analysis_figures",
        ".asterion-dci-batch.lock",
        ".inputs",
        "batch-state.json",
        "config",
        "config.json",
        "results",
        "results.jsonl",
        "summary",
        "summary.json",
    }
)
_WINDOWS_INVALID = frozenset('<>:"|?*')
_DISALLOWED_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})
_PORTABLE_COMPONENT_MAX_UTF8_BYTES = 255
_PORTABLE_COMPONENT_MAX_UTF16_UNITS = 255


@dataclass(frozen=True, slots=True)
class BenchmarkRow:
    """One validated source-order dataset row with immutable collection fields."""

    query_id: str
    query: str
    answer: str | tuple[str, ...] | None = None
    gold_docs: tuple[str, ...] | None = None
    gold_ids: tuple[str, ...] | None = None

    @property
    def is_ir(self) -> bool:
        return self.gold_docs is not None or self.gold_ids is not None

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"query_id": self.query_id, "query": self.query}
        for name in ("answer", "gold_docs", "gold_ids"):
            field = getattr(self, name)
            if field is not None:
                value[name] = list(field) if isinstance(field, tuple) else field
        return value


def _require_nonempty_string(value: Any, *, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise DatasetError(f"DCI dataset {field} must be a non-empty string")
    if any(unicodedata.category(character) == "Cs" for character in value):
        raise DatasetError(f"DCI dataset {field} must contain Unicode scalar values")
    return value


def _optional_string(value: Any, *, field: str) -> str | None:
    if value is None:
        raise DatasetError(f"DCI dataset {field} must be a non-empty string")
    return _require_nonempty_string(value, field=field)


def _document_list(value: Any, *, field: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise DatasetError(f"DCI dataset {field} must be a non-empty string list")
    documents = tuple(_require_nonempty_string(item, field=field) for item in value)
    return documents


def _is_noncharacter(character: str) -> bool:
    codepoint = ord(character)
    return 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFE == 0xFFFE


def _contains_unsafe_scalar(value: str) -> bool:
    return any(
        unicodedata.category(character) in _DISALLOWED_UNICODE_CATEGORIES
        or character in {"\u2028", "\u2029"}
        or _is_noncharacter(character)
        for character in value
    )


def _validate_portable_characters(value: str) -> None:
    if _contains_unsafe_scalar(value) or any(
        character in "/\\" or character in _WINDOWS_INVALID for character in value
    ):
        raise DatasetError("DCI dataset query ID is not portable")


def _validate_portable_component_length(value: str) -> None:
    try:
        utf8_length = len(value.encode("utf-8"))
        utf16_units = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise DatasetError("DCI dataset query ID is not portable") from error
    if (
        utf8_length > _PORTABLE_COMPONENT_MAX_UTF8_BYTES
        or utf16_units > _PORTABLE_COMPONENT_MAX_UTF16_UNITS
    ):
        raise DatasetError("DCI dataset query ID is too long")


def _natural_digit_identity(match: re.Match[str]) -> str:
    digits = match.group(0)
    significant = digits.lstrip("0") or "0"
    return f"#{len(significant)}:{significant}#"


def portable_query_id_key(query_id: str) -> str:
    """Validate an ID and return its reusable portable collision identity."""

    query_id = _require_nonempty_string(query_id, field="query ID")
    if query_id in {".", ".."} or query_id[-1] in {".", " "}:
        raise DatasetError("DCI dataset query ID is not portable")
    _validate_portable_characters(query_id)
    _validate_portable_component_length(query_id)

    portable = unicodedata.normalize("NFKC", query_id)
    if portable in {".", ".."} or portable[-1] in {".", " "}:
        raise DatasetError("DCI dataset query ID is not portable")
    _validate_portable_characters(portable)
    _validate_portable_component_length(portable)
    normalized = portable.casefold()
    reserved_stem = normalized.split(".", 1)[0].upper()
    if reserved_stem in _WINDOWS_RESERVED or normalized in _AGGREGATE_RESERVED:
        raise DatasetError("DCI dataset query ID is reserved")

    return re.sub(r"[0-9]+", _natural_digit_identity, normalized)


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DatasetError("DCI dataset JSON contains duplicate keys")
        value[key] = item
    return value


def _row_from_value(value: Any) -> BenchmarkRow:
    if type(value) is not dict:
        raise DatasetError("DCI dataset row must be an object")
    unknown = set(value).difference(_ALLOWED_FIELDS)
    if unknown:
        raise DatasetError("DCI dataset row contains unsupported fields")

    query_id = _require_nonempty_string(value.get("query_id"), field="query ID")
    query = _require_nonempty_string(value.get("query"), field="query")
    answer: str | tuple[str, ...] | None = None
    if "answer" in value:
        raw_answer = value["answer"]
        answer = (
            _document_list(raw_answer, field="answer")
            if type(raw_answer) is list
            else _optional_string(raw_answer, field="answer")
        )
    has_gold_docs = "gold_docs" in value
    has_gold_ids = "gold_ids" in value
    gold_docs = (
        _document_list(value["gold_docs"], field="gold_docs") if has_gold_docs else None
    )
    gold_ids = (
        _document_list(value["gold_ids"], field="gold_ids") if has_gold_ids else None
    )
    gold_alias_count = int(has_gold_docs) + int(has_gold_ids)
    if answer is not None:
        if gold_alias_count:
            raise DatasetError("DCI QA dataset row cannot contain IR gold documents")
    elif gold_alias_count != 1:
        raise DatasetError("DCI IR dataset row requires exactly one gold alias")
    portable_query_id_key(query_id)
    return BenchmarkRow(
        query_id=query_id,
        query=query,
        answer=answer,
        gold_docs=gold_docs,
        gold_ids=gold_ids,
    )


def load_benchmark_rows(path: Path) -> tuple[BenchmarkRow, ...]:
    """Read one no-follow regular-file snapshot and parse its exact bytes."""

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise DatasetError("DCI benchmark dataset is invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return load_benchmark_rows_bytes(raw)
    except DatasetError:
        raise
    except (OSError, UnicodeError) as error:
        raise DatasetError("DCI benchmark dataset is invalid") from error


def load_benchmark_rows_bytes(raw: bytes) -> tuple[BenchmarkRow, ...]:
    """Parse one immutable strict UTF-8 JSONL snapshot in source order."""

    try:
        text = raw.decode("utf-8", errors="strict")
        rows: list[BenchmarkRow] = []
        identities: set[str] = set()
        # JSONL records are separated only by physical LF bytes.  Python's
        # splitlines() also treats U+2028/U+2029 as record boundaries, which
        # would silently reinterpret otherwise valid JSON string content.
        for line_number, line in enumerate(text.split("\n"), start=1):
            if line.endswith("\r"):
                line = line[:-1]
            if not line.strip():
                continue
            try:
                value = json.loads(
                    line, object_pairs_hook=_object_without_duplicate_keys
                )
                row = _row_from_value(value)
            except (json.JSONDecodeError, DatasetError) as error:
                raise DatasetError(
                    f"DCI benchmark dataset is invalid at line {line_number}"
                ) from error
            identity = portable_query_id_key(row.query_id)
            if identity in identities:
                raise DatasetError(
                    f"DCI benchmark dataset has colliding query ID at line {line_number}"
                )
            identities.add(identity)
            rows.append(row)
    except DatasetError:
        raise
    except (OSError, UnicodeError) as error:
        raise DatasetError("DCI benchmark dataset is invalid") from error
    if not rows:
        raise DatasetError("DCI benchmark dataset is empty")
    return tuple(rows)


def load_beir_benchmark_rows_bytes(
    raw: bytes, *, expected_count: int | None = None
) -> tuple[BenchmarkRow, ...]:
    """Normalize the published DCI-Bench BEIR JSONL shape into IR rows."""

    if expected_count is not None and (
        type(expected_count) is not int or expected_count <= 0
    ):
        raise DatasetError("DCI BEIR source count must be a positive integer")
    try:
        text = raw.decode("utf-8", errors="strict")
        rows: list[BenchmarkRow] = []
        identities: set[str] = set()
        document_identities: dict[str, str] = {}
        for line_number, line in enumerate(text.split("\n"), start=1):
            if line.endswith("\r"):
                line = line[:-1]
            if not line.strip():
                continue
            value = json.loads(line, object_pairs_hook=_object_without_duplicate_keys)
            if type(value) is not dict or set(value) != {
                "query_id",
                "query",
                "answer",
                "gold_ids",
            }:
                raise DatasetError("DCI BEIR row has invalid fields")
            query_id = _require_nonempty_string(value["query_id"], field="query ID")
            query = _require_nonempty_string(value["query"], field="query")
            if value["answer"] != "":
                raise DatasetError("DCI BEIR answer placeholder must be empty")
            gold_ids = _document_list(value["gold_ids"], field="gold_ids")
            if len(gold_ids) != len(set(gold_ids)):
                raise DatasetError("DCI BEIR gold document IDs must be unique")
            for document_id in gold_ids:
                path = PurePosixPath(document_id)
                if (
                    path.is_absolute()
                    or len(path.parts) != 1
                    or document_id in {".", ".."}
                    or not document_id.endswith(".txt")
                    or _contains_unsafe_scalar(document_id)
                    or "\\" in document_id
                ):
                    raise DatasetError("DCI BEIR gold document ID is invalid")
                try:
                    document_identity = portable_query_id_key(document_id)
                except DatasetError as error:
                    raise DatasetError("DCI BEIR gold document ID is invalid") from error
                prior = document_identities.setdefault(document_identity, document_id)
                if prior != document_id:
                    raise DatasetError("DCI BEIR gold document IDs collide")
            identity = portable_query_id_key(query_id)
            if identity in identities:
                raise DatasetError("DCI BEIR dataset has colliding query ID")
            identities.add(identity)
            rows.append(
                BenchmarkRow(
                    query_id=query_id,
                    query=query,
                    gold_ids=gold_ids,
                )
            )
    except DatasetError as error:
        if "BEIR" in str(error):
            raise
        raise DatasetError("DCI BEIR dataset is invalid") from error
    except (json.JSONDecodeError, UnicodeError, TypeError) as error:
        raise DatasetError("DCI BEIR dataset is invalid") from error
    if not rows:
        raise DatasetError("DCI BEIR dataset is empty")
    if expected_count is not None and len(rows) != expected_count:
        raise DatasetError("DCI BEIR source count does not match")
    return tuple(rows)


def load_bright_benchmark_rows_bytes(
    raw: bytes, *, expected_count: int | None = None
) -> tuple[BenchmarkRow, ...]:
    """Normalize the published DCI-Bench BRIGHT source shape into IR rows."""

    if expected_count is not None and (
        type(expected_count) is not int or expected_count <= 0
    ):
        raise DatasetError("DCI BRIGHT source count must be a positive integer")
    try:
        text = raw.decode("utf-8", errors="strict")
        rows: list[BenchmarkRow] = []
        identities: set[str] = set()
        for line in text.split("\n"):
            if line.endswith("\r"):
                line = line[:-1]
            if not line.strip():
                continue
            value = json.loads(line, object_pairs_hook=_object_without_duplicate_keys)
            if type(value) is not dict or set(value) != _BRIGHT_SOURCE_FIELDS:
                raise DatasetError("DCI BRIGHT row has invalid fields")
            raw_query_id = value["query_id"]
            if type(raw_query_id) is str:
                query_id = _require_nonempty_string(raw_query_id, field="query ID")
            elif type(raw_query_id) is int:
                query_id = str(raw_query_id)
            else:
                raise DatasetError("DCI BRIGHT query ID is invalid")
            query = _require_nonempty_string(value["query"], field="query")
            for field in ("answer", "id", "reasoning"):
                _require_nonempty_string(value[field], field=field)
            for field in ("excluded_ids", "gold_ids_long"):
                _document_list(value[field], field=field)
            gold_ids = _document_list(value["gold_ids"], field="gold_ids")
            identity = portable_query_id_key(query_id)
            if identity in identities:
                raise DatasetError("DCI BRIGHT dataset has colliding query ID")
            identities.add(identity)
            rows.append(
                BenchmarkRow(
                    query_id=query_id,
                    query=query,
                    gold_ids=gold_ids,
                )
            )
    except DatasetError as error:
        if "BRIGHT" in str(error):
            raise
        raise DatasetError("DCI BRIGHT dataset is invalid") from error
    except (json.JSONDecodeError, UnicodeError, TypeError) as error:
        raise DatasetError("DCI BRIGHT dataset is invalid") from error
    if not rows:
        raise DatasetError("DCI BRIGHT dataset is empty")
    if expected_count is not None and len(rows) != expected_count:
        raise DatasetError("DCI BRIGHT source count does not match")
    return tuple(rows)


def validate_beir_corpus(corpus: Path, rows: tuple[BenchmarkRow, ...]) -> Path:
    """Verify a no-follow corpus directory and every referenced regular document."""

    identity = canonical_input_identity(corpus)
    descriptor = -1
    try:
        if stat.S_ISLNK(os.lstat(identity).st_mode):
            raise DatasetError("DCI BEIR corpus is invalid")
        resolved = identity.resolve(strict=True)
        descriptor = os.open(
            "/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        for component in resolved.parts[1:]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        referenced = sorted(
            {document_id for row in rows for document_id in (row.gold_ids or ())}
        )
        if not referenced:
            raise DatasetError("DCI BEIR corpus is invalid")
        for document_id in referenced:
            document_descriptor = os.open(
                document_id,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            try:
                if not stat.S_ISREG(os.fstat(document_descriptor).st_mode):
                    raise DatasetError("DCI BEIR corpus is invalid")
            finally:
                os.close(document_descriptor)
    except DatasetError:
        raise
    except OSError as error:
        raise DatasetError("DCI BEIR corpus is invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return identity


def load_beir_benchmark_rows(
    path: Path, *, expected_count: int | None = None
) -> tuple[BenchmarkRow, ...]:
    """Read one no-follow BEIR source snapshot and normalize it strictly."""

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise DatasetError("DCI BEIR dataset is invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except DatasetError:
        raise
    except OSError as error:
        raise DatasetError("DCI BEIR dataset is invalid") from error
    return load_beir_benchmark_rows_bytes(raw, expected_count=expected_count)


def read_jsonl(path: Path) -> tuple[BenchmarkRow, ...]:
    """Source-compatible name for the strict Asterion dataset loader."""

    return load_benchmark_rows(path)


def parse_retrieved_documents(result_text: str) -> list[str]:
    if type(result_text) is not str:
        raise DatasetError("DCI retrieval result must be a string")
    normalized = result_text.replace("\\n", "\n")
    section = re.search(
        r"Relevant Documents.*?(1\..*?)(?:\n\n|\Z)", normalized, re.DOTALL
    )
    if section is None:
        return []
    paths: list[str] = []
    for raw_line in section.group(1).splitlines():
        line = re.sub(r"^[\d]+\.\s*", "", raw_line.strip())
        line = re.sub(r"^[-*]\s*", "", line).strip()
        if line and not line.startswith("("):
            paths.append(line)
    return paths


def parse_retrieved_docs(result_text: str) -> list[str]:
    return parse_retrieved_documents(result_text)


def normalize_retrieved_path(path: str, corpus_dir: Path | None) -> str:
    if type(path) is not str or not path:
        raise DatasetError("DCI retrieved path must be a non-empty string")
    normalized = path.replace("\\", "/")
    normalized = re.sub(r"^\.?/+", "", normalized)
    if corpus_dir is not None:
        prefix = str(corpus_dir).replace("\\", "/").rstrip("/")
        if normalized.startswith(prefix + "/"):
            return normalized[len(prefix) + 1 :]
    return normalized.rsplit("/", 1)[-1]


def canonical_input_identity(path: Path) -> Path:
    """Return a lexical absolute input identity without touching the filesystem."""

    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _safe_corpus_identity(path: Path) -> Path:
    identity = canonical_input_identity(path)
    if _contains_unsafe_scalar(str(identity)):
        raise DatasetError("DCI prompt corpus identity is invalid")
    return identity


def build_benchmark_prompt(query: str, corpus_dir: Path) -> str:
    query = _require_nonempty_string(query, field="query")
    corpus = _safe_corpus_identity(corpus_dir)
    return (
        "Answer the following question. "
        f"The answer is contained in the corpus directory at @{corpus}. "
        "**Do Not use web search!** Use ripgrep (rg) instead of grep for fast searching. "
        "After using tools, always finish with a non-empty textual final answer.\n\n"
        "QUESTION:\n"
        f"{query}\n"
    )


def build_qa_prompt(query: str, corpus_dir: Path) -> str:
    return build_benchmark_prompt(query, corpus_dir)


def build_ir_prompt(
    query: str, corpus_dir: Path, corpus_hint: str | None = None
) -> str:
    query = _require_nonempty_string(query, field="query")
    corpus = _safe_corpus_identity(corpus_dir)
    if corpus_hint is not None and type(corpus_hint) is not str:
        raise DatasetError("DCI corpus_hint must be a string")
    if corpus_hint is not None and any(
        unicodedata.category(character) == "Cs" for character in corpus_hint
    ):
        raise DatasetError("DCI corpus_hint must contain Unicode scalar values")
    corpus_hint_section = f"CORPUS STRUCTURE:\n{corpus_hint}\n\n" if corpus_hint else ""
    return (
        f"You are a careful research assistant. Answer the question below using ONLY documents in @{corpus}.\n"
        "Do not use online search or any external tools beyond Grep and Bash.\n\n"
        f"Question:\n{query}\n\n"
        f"{corpus_hint_section}"
        "SEARCH STRATEGY (follow exactly):\n"
        "1. Use Grep/Bash ONLY — do NOT use the Agent tool, spawn subagents, or browse the web.\n"
        "2. Run multiple Grep/Bash searches IN PARALLEL within a single response to save time.\n"
        "3. Use diverse, targeted keywords to maximize recall before drawing conclusions.\n"
        "4. After each round, reflect on gaps and launch follow-up searches to cover missing angles.\n"
        "5. Do NOT stop after finding a few documents — exhaust all plausible search angles.\n\n"
        "RETRIEVAL INSTRUCTIONS:\n"
        "- Both recall AND precision matter equally — the output is evaluated with NDCG, which penalizes both missing relevant documents and including irrelevant ones.\n"
        "- Find EVERY document that is genuinely relevant. Missing a gold document hurts recall.\n"
        "- Read each candidate document carefully before including it. Including an irrelevant document hurts precision.\n"
        "- A document is relevant only if it directly addresses the question or provides essential supporting evidence for the answer. Do NOT include tangential or loosely related documents.\n\n"
        "RANKING INSTRUCTIONS:\n"
        "- Rank the final list by relevance: the most directly useful document for answering the question goes first. Ranking quality affects NDCG score.\n\n"
        "Your response MUST follow this exact format:\n"
        "Relevant Documents (ranked by relevance, most relevant first; maximum 20):\n"
        "1. {corpus}/path/to/doc1.txt\n"
        "2. {corpus}/path/to/doc2.txt\n"
        "3. {corpus}/path/to/doc3.txt\n"
        "(use full relative paths from the working directory; list at most 20 documents; omit any document that is not directly relevant)\n\n"
        "Explanation: {step-by-step reasoning with inline citations, e.g. [{corpus}/relative_path]}\n"
        "Exact Answer: {concise final answer only}\n"
        "Confidence: {0–100%; use below 50% if evidence is weak, ambiguous, or missing}\n"
    )


BENCHMARK_PROMPT_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema": BENCHMARK_PROMPT_CONTRACT,
            "qa": build_benchmark_prompt(
                "__DCI_QUERY__", Path("/__dci_prompt_contract_corpus__")
            ),
            "ir": build_ir_prompt(
                "__DCI_QUERY__",
                Path("/__dci_prompt_contract_corpus__"),
                "__DCI_CORPUS_HINT__",
            ),
            "final_answer_recovery": FINAL_ANSWER_RECOVERY_PROMPT,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
).hexdigest()


__all__ = [
    "BenchmarkRow",
    "BENCHMARK_PROMPT_CONTRACT",
    "BENCHMARK_PROMPT_CONTRACT_SHA256",
    "DatasetError",
    "build_benchmark_prompt",
    "build_ir_prompt",
    "build_qa_prompt",
    "canonical_input_identity",
    "load_benchmark_rows",
    "load_benchmark_rows_bytes",
    "load_beir_benchmark_rows",
    "load_beir_benchmark_rows_bytes",
    "load_bright_benchmark_rows_bytes",
    "normalize_retrieved_path",
    "parse_retrieved_docs",
    "parse_retrieved_documents",
    "portable_query_id_key",
    "read_jsonl",
]
