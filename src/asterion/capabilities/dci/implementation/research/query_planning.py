"""DCI-owned, private query-planning prompt contracts for Bright trials."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


BASELINE_QUERY_PLAN = "dci.query-plan/baseline/v1"
DECOMPOSED_QUERY_PLAN = "dci.query-plan/decomposed/v1"
_MAX_PROMPT_BYTES = 64 * 1024


class QueryPlanningError(ValueError):
    """Raised when a query-planning contract or private prompt is unsafe."""


@dataclass(frozen=True, slots=True)
class QueryPlanningContract:
    """One closed DCI query-planning change, without public prompt contents."""

    contract_id: str
    _append_system_prompt: str = field(repr=False, compare=False)

    def public_identity(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "contract_sha256": query_planning_contract_sha256(self),
        }


_BASELINE_CONTRACT = QueryPlanningContract(
    contract_id=BASELINE_QUERY_PLAN,
    _append_system_prompt="",
)
_DECOMPOSED_CONTRACT = QueryPlanningContract(
    contract_id=DECOMPOSED_QUERY_PLAN,
    _append_system_prompt=(
        "BRIGHT QUERY-PLANNING VARIANT (follow exactly):\n"
        "Before retrieval, identify the question's entities, concepts, relationships, "
        "and constraints. Form complementary subqueries for those components.\n"
        "Run a separate search round for each complementary subquery, using only the "
        "existing local Grep/Bash tools. Do not use web search and do not spawn "
        "subagents.\n"
        "Merge the candidate documents from all rounds, deduplicate them, validate "
        "their direct relevance to the question, and rerank the remaining documents.\n"
        "Preserve the existing output format: list only directly relevant documents, "
        "ranked by relevance, with a maximum 20 documents.\n"
    ),
)
_CONTRACTS = {
    BASELINE_QUERY_PLAN: _BASELINE_CONTRACT,
    DECOMPOSED_QUERY_PLAN: _DECOMPOSED_CONTRACT,
}


def resolve_query_planning_contract(value: object) -> QueryPlanningContract:
    """Resolve an exact pre-registered query-planning contract."""

    if type(value) is not str or value not in _CONTRACTS:
        raise QueryPlanningError("DCI query-planning contract is invalid")
    return _CONTRACTS[value]


def query_planning_contract_sha256(contract: QueryPlanningContract) -> str:
    """Return an opaque identity for one exact contract, not its prompt body."""

    expected = _exact_contract(contract)
    append_bytes = expected._append_system_prompt.encode("utf-8")
    if len(append_bytes) > _MAX_PROMPT_BYTES:
        raise QueryPlanningError("DCI query-planning contract is invalid")
    encoded = json.dumps(
        {
            "append_system_prompt_sha256": hashlib.sha256(append_bytes).hexdigest(),
            "contract_id": expected.contract_id,
            "schema": "asterion.dci.query-planning-contract/v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_query_planning_public_identity(
    value: object,
) -> dict[str, str] | None:
    """Accept only the candidate's closed public identity, or baseline absence."""

    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "contract_id",
        "contract_sha256",
    }:
        raise QueryPlanningError("DCI query-planning identity is invalid")
    contract_id = value.get("contract_id")
    contract_sha256 = value.get("contract_sha256")
    if type(contract_id) is not str or type(contract_sha256) is not str:
        raise QueryPlanningError("DCI query-planning identity is invalid")
    contract = resolve_query_planning_contract(contract_id)
    if (
        contract is _BASELINE_CONTRACT
        or contract_sha256 != query_planning_contract_sha256(contract)
    ):
        raise QueryPlanningError("DCI query-planning identity is invalid")
    return contract.public_identity()


def validate_query_planning_prompt_binding(
    identity: object,
    prompt_file: Path | None,
) -> dict[str, str] | None:
    """Close a candidate identity over its exact private append prompt."""

    public = validate_query_planning_public_identity(identity)
    if public is None:
        if prompt_file is not None and _is_candidate_prompt_file(prompt_file):
            raise QueryPlanningError("DCI query-planning identity is invalid")
        return None
    validate_materialized_query_planning_prompt(public["contract_id"], prompt_file)
    return public


def materialize_query_planning_prompt(contract_id: str, root: Path) -> Path:
    """Write the candidate append prompt below one operator-owned private root."""

    contract = resolve_query_planning_contract(contract_id)
    if contract is _BASELINE_CONTRACT:
        raise QueryPlanningError("DCI baseline query plan has no prompt override")
    contents = contract._append_system_prompt.encode("utf-8")
    if not contents or len(contents) > _MAX_PROMPT_BYTES:
        raise QueryPlanningError("DCI query-planning prompt is invalid")
    name = _prompt_name(contract)
    root_fd = _open_private_root(root)
    try:
        try:
            existing = _read_private_prompt(root_fd, name)
        except FileNotFoundError:
            _write_private_prompt(root_fd, name, contents)
        else:
            if existing != contents:
                raise QueryPlanningError("DCI query-planning prompt conflicts")
        if _read_private_prompt(root_fd, name) != contents:
            raise QueryPlanningError("DCI query-planning prompt conflicts")
    except QueryPlanningError:
        raise
    except Exception as error:
        raise QueryPlanningError("DCI query-planning prompt is invalid") from error
    finally:
        os.close(root_fd)
    return Path(root) / name


def validate_materialized_query_planning_prompt(
    contract_id: str,
    prompt_file: Path | None,
) -> None:
    """Require a candidate's pre-materialized exact private prompt file."""

    contract = resolve_query_planning_contract(contract_id)
    if contract is _BASELINE_CONTRACT:
        if prompt_file is not None:
            raise QueryPlanningError("DCI baseline query plan has no prompt override")
        return
    if not isinstance(prompt_file, Path) or not prompt_file.is_absolute():
        raise QueryPlanningError("DCI query-planning prompt is invalid")
    name = _prompt_name(contract)
    if prompt_file.name != name:
        raise QueryPlanningError("DCI query-planning prompt is invalid")
    expected = contract._append_system_prompt.encode("utf-8")
    root_fd = _open_private_root(prompt_file.parent)
    try:
        if _read_private_prompt(root_fd, name) != expected:
            raise QueryPlanningError("DCI query-planning prompt conflicts")
    except QueryPlanningError:
        raise
    except Exception as error:
        raise QueryPlanningError("DCI query-planning prompt is invalid") from error
    finally:
        os.close(root_fd)


def _is_candidate_prompt_file(path: Path) -> bool:
    if not isinstance(path, Path) or not path.is_absolute():
        return False
    try:
        validate_materialized_query_planning_prompt(DECOMPOSED_QUERY_PLAN, path)
    except QueryPlanningError:
        return False
    return True


def _exact_contract(value: object) -> QueryPlanningContract:
    if type(value) is not QueryPlanningContract:
        raise QueryPlanningError("DCI query-planning contract is invalid")
    expected = _CONTRACTS.get(value.contract_id)
    if (
        expected is None
        or value.contract_id != expected.contract_id
        or value._append_system_prompt != expected._append_system_prompt
    ):
        raise QueryPlanningError("DCI query-planning contract is invalid")
    return expected


def _prompt_name(contract: QueryPlanningContract) -> str:
    return f"query-planning-{query_planning_contract_sha256(contract)}.txt"


def _open_private_root(root: object) -> int:
    if not isinstance(root, Path) or not root.is_absolute():
        raise QueryPlanningError("DCI query-planning root is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(root.anchor, flags | nofollow)
        for component in root.parts[1:]:
            child = os.open(component, flags | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise QueryPlanningError("DCI query-planning root is invalid")
        return descriptor
    except QueryPlanningError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except Exception as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise QueryPlanningError("DCI query-planning root is invalid") from error


def _read_private_prompt(root_fd: int, name: str) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | os.O_NONBLOCK
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fd,
        )
        initial = os.fstat(descriptor)
        if (
            not stat.S_ISREG(initial.st_mode)
            or initial.st_uid != os.geteuid()
            or stat.S_IMODE(initial.st_mode) != 0o400
            or initial.st_size < 1
            or initial.st_size > _MAX_PROMPT_BYTES
        ):
            raise QueryPlanningError("DCI query-planning prompt is invalid")
        chunks: list[bytes] = []
        remaining = _MAX_PROMPT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        current = os.fstat(descriptor)
        final = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            len(value) > _MAX_PROMPT_BYTES
            or (initial.st_dev, initial.st_ino, initial.st_size)
            != (current.st_dev, current.st_ino, current.st_size)
            or (initial.st_dev, initial.st_ino)
            != (final.st_dev, final.st_ino)
        ):
            raise QueryPlanningError("DCI query-planning prompt changed")
        return value
    except QueryPlanningError:
        raise
    except FileNotFoundError:
        raise
    except Exception as error:
        raise QueryPlanningError("DCI query-planning prompt is invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_private_prompt(root_fd: int, name: str, contents: bytes) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o400,
            dir_fd=root_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise QueryPlanningError("DCI query-planning prompt is invalid")
        os.fchmod(descriptor, 0o400)
        offset = 0
        while offset < len(contents):
            written = os.write(descriptor, contents[offset:])
            if written <= 0:
                raise OSError("short private prompt write")
            offset += written
        os.fsync(descriptor)
    except QueryPlanningError:
        raise
    except Exception as error:
        raise QueryPlanningError("DCI query-planning prompt could not be written") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = (
    "BASELINE_QUERY_PLAN",
    "DECOMPOSED_QUERY_PLAN",
    "QueryPlanningContract",
    "QueryPlanningError",
    "materialize_query_planning_prompt",
    "query_planning_contract_sha256",
    "resolve_query_planning_contract",
    "validate_query_planning_prompt_binding",
    "validate_query_planning_public_identity",
    "validate_materialized_query_planning_prompt",
)
