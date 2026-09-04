"""Host-only P1 completion reduction for the fixed IPython coding task.

The worker is untrusted.  This module accepts only facts collected by the
application host and never accepts launcher output, process exits, or frames.
The syntax oracle parses bytes but does not import, compile, or run them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Literal


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
_MAX_SOURCE_BYTES = 16 * 1024

__all__ = (
    "IpythonHostCompletion",
    "IpythonHostCompletionInputs",
    "IpythonHostModelReceipt",
    "IpythonHostOracleObservation",
    "IpythonHostSupervisorError",
    "IpythonHostWorkspaceSnapshot",
    "inspect_answer_source",
    "mint_ipython_host_completion",
)


class IpythonHostSupervisorError(ValueError):
    """Raised without source, cell, prompt, or worker-output details."""


@dataclass(frozen=True, repr=False)
class IpythonHostOracleObservation:
    """A data-only host AST result, bound to the inspected source digest."""

    source_digest: str
    passed: bool

    def __repr__(self) -> str:
        return "IpythonHostOracleObservation(redacted)"


@dataclass(frozen=True, repr=False)
class IpythonHostModelReceipt:
    """The host's bounded-model receipt, after the broker has been revoked."""

    session_id: str
    run_id: str
    worker_id: str
    challenge_digest: str
    bounded_model_digest: str
    sent_cell_digest: str
    request_count: int
    input_bytes: int
    output_bytes: int
    status: Literal["revoked"]

    def __repr__(self) -> str:
        return "IpythonHostModelReceipt(redacted)"


@dataclass(frozen=True, repr=False)
class IpythonHostWorkspaceSnapshot:
    """A daemon-attested digest of the sole fixed workspace file."""

    source_digest: str
    locked: bool

    def __repr__(self) -> str:
        return "IpythonHostWorkspaceSnapshot(redacted)"


@dataclass(frozen=True, repr=False)
class IpythonHostCompletionInputs:
    """Only host-attested evidence admitted by the P1 completion reducer."""

    model_receipt: IpythonHostModelReceipt
    pre_snapshot: IpythonHostWorkspaceSnapshot
    post_snapshot: IpythonHostWorkspaceSnapshot
    oracle: IpythonHostOracleObservation
    tool_names: tuple[str, ...]
    cleanup_verified: bool
    absence_verified: bool

    def __repr__(self) -> str:
        return "IpythonHostCompletionInputs(redacted)"


@dataclass(frozen=True)
class IpythonHostCompletion:
    """Body-free public result minted exclusively by this host reducer."""

    status: Literal["PASS"]
    evidence_digest: str


def inspect_answer_source(source: object) -> IpythonHostOracleObservation:
    """Statically recognize exactly ``def answer() -> int: return 42``.

    Parsing is deliberately bounded and treats every malformed or non-byte
    value as a failed host observation.  It never loads or executes the code.
    """

    data = source if type(source) is bytes else b""
    digest = _sha256(data)
    if type(source) is not bytes or not data or len(data) > _MAX_SOURCE_BYTES:
        return IpythonHostOracleObservation(digest, False)
    try:
        module = ast.parse(data, mode="exec")
    except (SyntaxError, ValueError, TypeError):
        return IpythonHostOracleObservation(digest, False)
    return IpythonHostOracleObservation(digest, _is_fixed_answer_module(module))


def mint_ipython_host_completion(inputs: object) -> IpythonHostCompletion:
    """Mint P1 PASS only when every causally relevant host fact is present."""

    if type(inputs) is not IpythonHostCompletionInputs:
        raise IpythonHostSupervisorError("ipython host completion is invalid")
    _validate_completion_inputs(inputs)
    return IpythonHostCompletion("PASS", _evidence_digest(inputs))


def _is_fixed_answer_module(module: ast.Module) -> bool:
    if len(module.body) != 1 or type(module.body[0]) is not ast.FunctionDef:
        return False
    function = module.body[0]
    arguments = function.args
    if (
        function.name != "answer"
        or function.decorator_list
        or arguments.posonlyargs
        or arguments.args
        or arguments.vararg is not None
        or arguments.kwonlyargs
        or arguments.kwarg is not None
        or arguments.defaults
        or arguments.kw_defaults
        or not _is_int_annotation(function.returns)
        or len(function.body) != 1
        or type(function.body[0]) is not ast.Return
    ):
        return False
    returned = function.body[0].value
    return type(returned) is ast.Constant and type(returned.value) is int and returned.value == 42


def _is_int_annotation(node: ast.expr | None) -> bool:
    return node is None or (type(node) is ast.Name and node.id == "int")


def _validate_completion_inputs(inputs: IpythonHostCompletionInputs) -> None:
    receipt = inputs.model_receipt
    pre, post, oracle = inputs.pre_snapshot, inputs.post_snapshot, inputs.oracle
    if (
        type(receipt) is not IpythonHostModelReceipt
        or type(pre) is not IpythonHostWorkspaceSnapshot
        or type(post) is not IpythonHostWorkspaceSnapshot
        or type(oracle) is not IpythonHostOracleObservation
        or inputs.tool_names != ("ipython",)
        or inputs.cleanup_verified is not True
        or inputs.absence_verified is not True
        or pre.locked is not True
        or type(post.locked) is not bool
        or oracle.passed is not True
        or pre.source_digest == post.source_digest
        or post.source_digest != oracle.source_digest
        or receipt.sent_cell_digest != oracle.source_digest
    ):
        raise IpythonHostSupervisorError("ipython host completion is invalid")
    if (
        receipt.status != "revoked"
        or type(receipt.request_count) is not int
        or receipt.request_count != 1
        or type(receipt.input_bytes) is not int
        or receipt.input_bytes <= 0
        or type(receipt.output_bytes) is not int
        or receipt.output_bytes <= 0
        or not all(_valid_identifier(value) for value in (receipt.session_id, receipt.run_id, receipt.worker_id))
        or not all(
            _valid_digest(value)
            for value in (
                receipt.challenge_digest,
                receipt.bounded_model_digest,
                receipt.sent_cell_digest,
                pre.source_digest,
                post.source_digest,
                oracle.source_digest,
            )
        )
    ):
        raise IpythonHostSupervisorError("ipython host completion is invalid")


def _evidence_digest(inputs: IpythonHostCompletionInputs) -> str:
    receipt = inputs.model_receipt
    canonical = json.dumps(
        (
            receipt.session_id,
            receipt.run_id,
            receipt.worker_id,
            receipt.challenge_digest,
            receipt.bounded_model_digest,
            receipt.sent_cell_digest,
            inputs.pre_snapshot.source_digest,
            inputs.post_snapshot.source_digest,
        ),
        separators=(",", ":"),
    ).encode("ascii")
    return _sha256(canonical)


def _sha256(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None
