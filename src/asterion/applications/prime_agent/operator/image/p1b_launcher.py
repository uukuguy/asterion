#!/usr/bin/env python3
"""Development-only JSONL worker proving persistent IPython state for P1-B."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

try:  # Docker copies this sibling module beside the executable entrypoint.
    from .closed_worker import require_closed_worker
except ImportError:  # pragma: no cover - exercised by the image entrypoint.
    from closed_worker import require_closed_worker

if TYPE_CHECKING:
    from IPython.core.interactiveshell import InteractiveShell


PROTOCOL = "prime-p1-b-development-worker/v1"
_FRAME_LIMIT = 64 * 1024
_IDENTITY_KEYS = frozenset(("run_id", "session_id"))
_FIXTURE_DIRECTORY = "p1b-state"
_FIXTURE_NAME = "continuity.txt"
_FIXTURE_BYTES = b"p1b continuity fixture\n"


class _BoundedDiscard(io.TextIOBase):
    """Discard cell output while bounding the amount any cell can produce."""

    def __init__(self, limit: int = _FRAME_LIMIT) -> None:
        self._limit = limit
        self._written = 0

    def write(self, value: str) -> int:
        self._written += len(value.encode("utf-8", errors="replace"))
        if self._written > self._limit:
            raise RuntimeError("cell output limit exceeded")
        return len(value)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_frame(stdin: TextIO) -> dict[str, object] | None:
    raw = stdin.readline(_FRAME_LIMIT + 1)
    if raw == "":
        return None
    encoded = raw.encode("utf-8", errors="strict")
    if (
        len(encoded) > _FRAME_LIMIT
        or not raw.endswith("\n")
        or raw.count("\n") != 1
        or "\r" in raw
    ):
        raise ValueError("invalid frame")
    try:
        value = json.loads(
            raw[:-1], object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid frame") from error
    if type(value) is not dict or _canonical(value) != encoded[:-1]:
        raise ValueError("noncanonical frame")
    return value


def _reject_constant(value: str) -> object:
    raise ValueError(value)


def _identity(value: object) -> dict[str, str]:
    if type(value) is not dict or set(value) != _IDENTITY_KEYS:
        raise ValueError("invalid identity")
    if any(type(item) is not str or not item for item in value.values()):
        raise ValueError("invalid identity")
    return {key: value[key] for key in sorted(_IDENTITY_KEYS)}


def _require_request(
    value: Mapping[str, object], *, identity: Mapping[str, str] | None, sequence: int, kind: str
) -> dict[str, str] | None:
    expected = {"protocol", "identity", "sequence", "kind"}
    if kind == "cell.execute":
        expected.add("cell")
    if set(value) != expected or value.get("protocol") != PROTOCOL:
        raise ValueError("invalid request")
    request_identity = _identity(value.get("identity"))
    if identity is not None and request_identity != identity:
        raise ValueError("unexpected identity")
    if type(value.get("sequence")) is not int or value["sequence"] != sequence:
        raise ValueError("unexpected sequence")
    if value.get("kind") != kind:
        raise ValueError("unexpected kind")
    if kind == "cell.execute" and (type(value.get("cell")) is not str or not value["cell"]):
        raise ValueError("invalid cell")
    return request_identity if identity is None else None


def _emit(stdout: TextIO, value: Mapping[str, object]) -> None:
    raw = _canonical(value)
    if len(raw) + 1 > _FRAME_LIMIT:
        raise ValueError("oversized response")
    stdout.write(raw.decode("utf-8") + "\n")
    stdout.flush()


def _event(identity: Mapping[str, str], sequence: int, kind: str, **values: object) -> dict[str, object]:
    return {
        "identity": dict(identity),
        "kind": kind,
        "protocol": PROTOCOL,
        "sequence": sequence,
        **values,
    }


def _prepare_workspace(workspace: Path) -> Path:
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("invalid workspace")
    state = workspace / _FIXTURE_DIRECTORY
    if state.exists():
        raise ValueError("workspace state already exists")
    return state.resolve()


def _execute(shell: InteractiveShell, cell: str) -> None:
    discarded = _BoundedDiscard()
    with contextlib.redirect_stdout(discarded), contextlib.redirect_stderr(discarded):
        result = shell.run_cell(cell, store_history=False, silent=False)
    if result.error_before_exec is not None or result.error_in_exec is not None:
        raise RuntimeError("cell execution failed")


def _record_baseline(shell: InteractiveShell, state: Path) -> tuple[object, object]:
    namespace = shell.user_ns
    value = namespace.get("p1b_value")
    alias = namespace.get("P1BPath")
    function = namespace.get("p1b_answer")
    if (
        value != 41
        or alias is not Path
        or not callable(function)
        or function() != 42
        or Path.cwd().resolve() != state
        or Path(_FIXTURE_NAME).read_bytes() != _FIXTURE_BYTES
    ):
        raise RuntimeError("baseline rejected")
    return value, function


def _preserved(shell: InteractiveShell, state: Path, baseline: tuple[object, object]) -> dict[str, bool]:
    value, function = baseline
    namespace = shell.user_ns
    preserved = {
        "cwd": Path.cwd().resolve() == state,
        "file_bytes": _read_fixture() == _FIXTURE_BYTES,
        "function_behavior": _function_returns_42(namespace.get("p1b_answer")),
        "function_identity": namespace.get("p1b_answer") is function,
        "namespace_value": namespace.get("p1b_value") == value == 41,
        "path_alias": namespace.get("P1BPath") is Path,
    }
    if not all(preserved.values()):
        raise RuntimeError("continuity rejected")
    return preserved


def _read_fixture() -> bytes | None:
    try:
        return Path(_FIXTURE_NAME).read_bytes()
    except OSError:
        return None


def _function_returns_42(value: object) -> bool:
    try:
        return callable(value) and value() == 42
    except Exception:
        return False


def run_development_worker(*, workspace: Path, stdin: TextIO, stdout: TextIO) -> int:
    """Run one two-cell development session; return a safe process status."""
    identity: dict[str, str] | None = None
    output_sequence = 1
    original_cwd = Path.cwd()
    try:
        # No protocol witness may be emitted before the P1-A-equivalent gate.
        require_closed_worker()
        workspace = workspace.resolve()
        state = _prepare_workspace(workspace)
        os.chdir(workspace)
        from IPython.core.interactiveshell import InteractiveShell

        shell = InteractiveShell.instance()
        with contextlib.redirect_stdout(_BoundedDiscard()), contextlib.redirect_stderr(_BoundedDiscard()):
            shell.reset(new_session=True)

        first = _read_frame(stdin)
        if first is None:
            raise ValueError("unexpected EOF")
        identity = _require_request(first, identity=None, sequence=1, kind="cell.execute")
        assert identity is not None
        _execute(shell, first["cell"])
        baseline = _record_baseline(shell, state)
        _emit(stdout, _event(identity, output_sequence, "baseline.recorded", baseline_recorded=True, cell_count=1, kernel_generation=1, probe_count=6))
        output_sequence += 1

        second = _read_frame(stdin)
        if second is None:
            raise ValueError("unexpected EOF")
        _require_request(second, identity=identity, sequence=2, kind="cell.execute")
        preserved = _preserved(shell, state, baseline)
        _execute(shell, second["cell"])
        _emit(stdout, _event(identity, output_sequence, "continuity.verified", cell_count=2, kernel_generation=1, preserved=preserved, probe_count=12))
        output_sequence += 1

        finish = _read_frame(stdin)
        if finish is None:
            raise ValueError("unexpected EOF")
        _require_request(finish, identity=identity, sequence=3, kind="finish")
        _emit(stdout, _event(identity, output_sequence, "completed", cell_count=2, completed=True, kernel_generation=1, probe_count=12))
        return 0
    except Exception:
        if identity is not None:
            try:
                _emit(stdout, _event(identity, output_sequence, "failed", failure="protocol"))
            except Exception:
                pass
        return 1
    finally:
        try:
            os.chdir(original_cwd)
        except OSError:
            pass


def main() -> None:
    raise SystemExit(
        run_development_worker(workspace=Path("/workspace"), stdin=sys.stdin, stdout=sys.stdout)
    )


if __name__ == "__main__":
    main()
