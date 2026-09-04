"""Application-host P1 completion supervisor; it never executes inspected code.

Private attestations are an application-host boundary, not cryptographic or OS
isolation.  The untrusted worker cannot mint a public completion.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Literal, cast

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
_MAX_SOURCE_BYTES = 16 * 1024
_SEAL = object()
__all__ = (
    "IpythonHostCompletion",
    "IpythonHostExpectedIdentity",
    "IpythonHostSupervisor",
    "IpythonHostSupervisorError",
    "inspect_answer_source",
)


class IpythonHostSupervisorError(ValueError):
    """A body-free rejection of untrusted or malformed completion evidence."""


@dataclass(frozen=True, repr=False)
class IpythonHostExpectedIdentity:
    assembly_id: str
    package_id: str
    implementation_id: str
    image_digest: str
    workload_id: str
    oracle_id: str

    def __repr__(self) -> str:
        return "IpythonHostExpectedIdentity(redacted)"


class IpythonHostCompletion:
    __slots__ = ("_digest",)

    def __init__(self, *, _seal: object, evidence_digest: str) -> None:
        if _seal is not _SEAL or not _valid_digest(evidence_digest):
            _invalid()
        self._digest = evidence_digest

    @property
    def status(self) -> Literal["PASS"]:
        return "PASS"

    @property
    def evidence_digest(self) -> str:
        return self._digest

    def __repr__(self) -> str:
        return "IpythonHostCompletion(PASS)"


@dataclass(frozen=True, repr=False)
class _Snapshot:
    issuer: object
    digest: str
    regular_file: bool
    oracle_passed: bool

    def __repr__(self) -> str:
        return "_Snapshot(redacted)"


@dataclass(frozen=True, repr=False)
class _Cell:
    issuer: object
    identity: IpythonHostExpectedIdentity
    digest: str
    model_digest: str
    request_count: int
    input_bytes: int
    output_bytes: int
    tools: tuple[str, ...]
    cancelled: bool

    def __repr__(self) -> str:
        return "_Cell(redacted)"


@dataclass(frozen=True, repr=False)
class _Oracle:
    issuer: object
    digest: str
    passed: bool

    def __repr__(self) -> str:
        return "_Oracle(redacted)"


def inspect_answer_source(source: object) -> bool:
    """Strict UTF-8 then data-only AST inspection; never compile/import/execute."""
    if type(source) is not bytes or not source or len(source) > _MAX_SOURCE_BYTES:
        return False
    try:
        module = ast.parse(source.decode("utf-8", "strict"), mode="exec")
    except (SyntaxError, UnicodeDecodeError, ValueError, TypeError):
        return False
    if len(module.body) != 1 or type(module.body[0]) is not ast.FunctionDef:
        return False
    function = module.body[0]
    args = function.args
    if (
        function.name != "answer"
        or function.decorator_list
        or args.posonlyargs
        or args.args
        or args.vararg is not None
        or args.kwonlyargs
        or args.kwarg is not None
        or args.defaults
        or args.kw_defaults
        or not _is_int(function.returns)
        or len(function.body) != 1
        or type(function.body[0]) is not ast.Return
    ):
        return False
    value = function.body[0].value
    return (
        type(value) is ast.Constant and type(value.value) is int and value.value == 42
    )


class IpythonHostSupervisor:
    """The only public PASS path, in fixed causal order."""

    def __init__(self, expected_identity: object) -> None:
        if not _valid_identity(expected_identity):
            _invalid()
        self._expected = cast(IpythonHostExpectedIdentity, expected_identity)
        self._issuer = object()
        self._initial: _Snapshot | None = None
        self._cell: _Cell | None = None
        self._post: _Snapshot | None = None
        self._revoked = self._cleanup = self._absence = False
        self._stages: list[str] = []

    # Private producer hooks for future Docker/broker adapters, not public
    # generic receipt/snapshot APIs.
    def _attest_snapshot(self, source: object, *, is_regular_file: object) -> _Snapshot:
        if (
            type(source) is not bytes
            or type(is_regular_file) is not bool
            or len(source) > _MAX_SOURCE_BYTES
        ):
            _invalid()
        data = cast(bytes, source)
        return _Snapshot(
            self._issuer,
            _sha256(data),
            cast(bool, is_regular_file),
            inspect_answer_source(data),
        )

    def _attest_oracle(self, source: object) -> _Oracle:
        if type(source) is not bytes or len(source) > _MAX_SOURCE_BYTES:
            _invalid()
        data = cast(bytes, source)
        return _Oracle(self._issuer, _sha256(data), inspect_answer_source(data))

    def _attest_brokered_cell(
        self,
        *,
        identity: object,
        cell: object,
        bounded_model_digest: object,
        request_count: object,
        input_bytes: object,
        output_bytes: object,
        cancelled: object = False,
    ) -> _Cell:
        if (
            not _valid_identity(identity)
            or type(cell) is not bytes
            or not cell
            or len(cell) > _MAX_SOURCE_BYTES
            or not _valid_digest(bounded_model_digest)
            or type(request_count) is not int
            or request_count != 1
            or type(input_bytes) is not int
            or input_bytes <= 0
            or type(output_bytes) is not int
            or output_bytes <= 0
            or type(cancelled) is not bool
        ):
            _invalid()
        return _Cell(
            self._issuer,
            cast(IpythonHostExpectedIdentity, identity),
            _sha256(cast(bytes, cell)),
            cast(str, bounded_model_digest),
            cast(int, request_count),
            cast(int, input_bytes),
            cast(int, output_bytes),
            ("ipython",),
            cast(bool, cancelled),
        )

    def record_initial_snapshot(self, snapshot: object) -> None:
        if self._initial is not None or not _valid_snapshot(snapshot, self._issuer):
            _invalid()
        attestation = cast(_Snapshot, snapshot)
        if not attestation.regular_file or attestation.oracle_passed:
            _invalid()
        self._initial = attestation
        self._stages.append("initial-daemon-snapshot-and-failed-host-ast")

    def record_brokered_cell(self, receipt: object) -> None:
        if (
            self._initial is None
            or self._cell is not None
            or not _valid_cell(receipt, self._issuer)
        ):
            _invalid()
        attestation = cast(_Cell, receipt)
        if attestation.cancelled or attestation.identity != self._expected:
            _invalid()
        self._cell = attestation
        self._stages.append("genuine-brokered-ipython-cell")

    def record_post_snapshot(self, snapshot: object) -> None:
        if (
            self._cell is None
            or self._post is not None
            or not _valid_snapshot(snapshot, self._issuer)
        ):
            _invalid()
        attestation = cast(_Snapshot, snapshot)
        initial = cast(_Snapshot, self._initial)
        if not attestation.regular_file or attestation.digest == initial.digest:
            _invalid()
        self._post = attestation
        self._stages.append("changed-post-daemon-snapshot")

    def record_broker_revoked(self, receipt: object) -> None:
        if self._post is None or self._revoked or receipt is not self._cell:
            _invalid()
        self._revoked = True
        self._stages.append("broker-revoked-and-quiescent")

    def record_cleanup(
        self, *, cleanup_verified: object, absence_verified: object
    ) -> None:
        if (
            not self._revoked
            or self._cleanup
            or type(cleanup_verified) is not bool
            or type(absence_verified) is not bool
            or cleanup_verified is not True
            or absence_verified is not True
        ):
            _invalid()
        self._cleanup = self._absence = True
        self._stages.append("cleanup-and-absence-verified")

    def complete(self, final_oracle: object) -> IpythonHostCompletion:
        if (
            not self._cleanup
            or not self._absence
            or not _valid_oracle(final_oracle, self._issuer)
        ):
            _invalid()
        attestation = cast(_Oracle, final_oracle)
        post = cast(_Snapshot, self._post)
        if not attestation.passed or attestation.digest != post.digest:
            _invalid()
        initial = cast(_Snapshot, self._initial)
        cell = cast(_Cell, self._cell)
        post = cast(_Snapshot, self._post)
        oracle = attestation
        self._stages.append("final-host-ast-success")
        evidence = {
            "version": "prime-ipython-host-evidence/v1",
            "identity": (
                self._expected.assembly_id,
                self._expected.package_id,
                self._expected.implementation_id,
                self._expected.image_digest,
                self._expected.workload_id,
                self._expected.oracle_id,
            ),
            "model": (
                cell.model_digest,
                cell.digest,
                cell.request_count,
                cell.input_bytes,
                cell.output_bytes,
                cell.tools,
                cell.cancelled,
            ),
            "snapshots": (
                initial.digest,
                initial.regular_file,
                initial.oracle_passed,
                post.digest,
                post.regular_file,
            ),
            "oracle": (oracle.digest, oracle.passed),
            "cleanup": (self._revoked, self._cleanup, self._absence),
            "stages": tuple(self._stages),
        }
        return IpythonHostCompletion(
            _seal=_SEAL,
            evidence_digest=_sha256(
                json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode(
                    "ascii"
                )
            ),
        )


def _valid_snapshot(value: object, issuer: object) -> bool:
    return (
        type(value) is _Snapshot
        and value.issuer is issuer
        and _valid_digest(value.digest)
        and type(value.regular_file) is bool
        and type(value.oracle_passed) is bool
    )


def _valid_cell(value: object, issuer: object) -> bool:
    if type(value) is not _Cell or value.issuer is not issuer:
        return False
    tools = value.tools
    return (
        _valid_identity(value.identity)
        and _valid_digest(value.digest)
        and _valid_digest(value.model_digest)
        and type(value.request_count) is int
        and value.request_count == 1
        and type(value.input_bytes) is int
        and value.input_bytes > 0
        and type(value.output_bytes) is int
        and value.output_bytes > 0
        and type(tools) is tuple
        and len(tools) == 1
        and type(tools[0]) is str
        and tools[0] == "ipython"
        and type(value.cancelled) is bool
    )


def _valid_oracle(value: object, issuer: object) -> bool:
    return (
        type(value) is _Oracle
        and value.issuer is issuer
        and _valid_digest(value.digest)
        and type(value.passed) is bool
    )


def _valid_identity(value: object) -> bool:
    return (
        type(value) is IpythonHostExpectedIdentity
        and all(
            _valid_identifier(part)
            for part in (
                value.assembly_id,
                value.package_id,
                value.implementation_id,
                value.workload_id,
                value.oracle_id,
            )
        )
        and _valid_digest(value.image_digest)
    )


def _is_int(node: ast.expr | None) -> bool:
    return node is None or (type(node) is ast.Name and node.id == "int")


def _sha256(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _invalid() -> None:
    raise IpythonHostSupervisorError("ipython host completion is invalid")
