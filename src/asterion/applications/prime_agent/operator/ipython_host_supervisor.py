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
from typing import cast

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
_MAX_SOURCE_BYTES = 16 * 1024
_SEAL = object()
_SUPERVISOR_SEAL = object()
_ATTESTATION_VERSION = "prime-ipython-host-attestation/v1"
_ASSEMBLY_ID = "prime.ipython-coding@1.0.0"
_PACKAGE_ID = "prime-agent@1.0.0"
_IMPLEMENTATION_ID = "prime.ipython-coding@1.0.0"
_WORKLOAD_DIGEST = "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"
_ORACLE_DIGEST = "sha256:85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb"
_STARTER_DIGEST = "sha256:4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f"
_SOURCE_DIGEST = "sha256:486a083f857430c7d6a452ebf881d1b8c46063c128b51162ffdebef0c1f71c7a"
__all__ = (
    "IpythonHostExpectedIdentity",
    "IpythonHostSupervisor",
    "IpythonHostSupervisorError",
    "IpythonHostTrace",
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
    workload_digest: str
    oracle_digest: str
    starter_digest: str
    source_digest: str

    def __repr__(self) -> str:
        return "IpythonHostExpectedIdentity(redacted)"


class IpythonHostTrace:
    __slots__ = ("__digest",)

    def __init__(self, *, _seal: object, evidence_digest: str) -> None:
        if _seal is not _SEAL or not _valid_digest(evidence_digest):
            _invalid()
        object.__setattr__(self, "_IpythonHostTrace__digest", evidence_digest)

    def __setattr__(self, name: str, value: object) -> None:
        raise TypeError("ipython host completion is immutable")

    def __delattr__(self, name: str) -> None:
        raise TypeError("ipython host completion is immutable")

    @property
    def evidence_digest(self) -> str:
        return self.__digest

    def __repr__(self) -> str:
        return "IpythonHostTrace(redacted)"


@dataclass(frozen=True, repr=False)
class _Snapshot:
    issuer: object
    version: str
    stage: str
    sequence: int
    digest: str
    regular_file: bool
    oracle_passed: bool

    def __repr__(self) -> str:
        return "_Snapshot(redacted)"


@dataclass(frozen=True, repr=False)
class _Cell:
    issuer: object
    version: str
    stage: str
    sequence: int
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
    version: str
    stage: str
    sequence: int
    digest: str
    passed: bool

    def __repr__(self) -> str:
        return "_Oracle(redacted)"


@dataclass(frozen=True, repr=False)
class _Revocation:
    issuer: object
    version: str
    stage: str
    sequence: int
    session_id: str
    request_count: int
    input_bytes: int
    output_bytes: int

    def __repr__(self) -> str:
        return "_Revocation(redacted)"


@dataclass(frozen=True, repr=False)
class _Cleanup:
    issuer: object
    version: str
    stage: str
    sequence: int

    def __repr__(self) -> str:
        return "_Cleanup(redacted)"


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
    """Validates the fixed causal lifecycle and emits a body-free trace only."""

    def __init__(self, expected_identity: object, *, _seal: object = None) -> None:
        if _seal is not _SUPERVISOR_SEAL or not _valid_identity(expected_identity):
            _invalid()
        self._expected = cast(IpythonHostExpectedIdentity, expected_identity)
        self._issuer = object()
        self._initial: _Snapshot | None = None
        self._cell: _Cell | None = None
        self._post: _Snapshot | None = None
        self._revocation: _Revocation | None = None
        self._cleanup: _Cleanup | None = None
        self._cancelled = self._completed = False
        self._sequence = 0
        self._stages: list[str] = []

    # Private producer hooks for future Docker/broker adapters, not public
    # generic receipt/snapshot APIs.
    def cancel(self) -> None:
        """Latch host-observed cancellation; it can never be cleared."""
        self._require_active()
        self._cancelled = True

    def _attest_initial_snapshot(
        self, source: object, *, is_regular_file: object
    ) -> _Snapshot:
        self._require_stage(0)
        return self._make_snapshot(source, is_regular_file, "initial", 1)

    def _attest_post_snapshot(
        self, source: object, *, is_regular_file: object
    ) -> _Snapshot:
        self._require_stage(2)
        return self._make_snapshot(source, is_regular_file, "post", 3)

    def _make_snapshot(
        self, source: object, is_regular_file: object, stage: str, sequence: int
    ) -> _Snapshot:
        if (
            type(source) is not bytes
            or type(is_regular_file) is not bool
            or len(source) > _MAX_SOURCE_BYTES
        ):
            _invalid()
        data = cast(bytes, source)
        return _Snapshot(
            self._issuer,
            _ATTESTATION_VERSION,
            stage,
            sequence,
            _sha256(data),
            cast(bool, is_regular_file),
            inspect_answer_source(data),
        )

    def _attest_final_oracle(self, source: object) -> _Oracle:
        self._require_stage(5)
        if type(source) is not bytes or len(source) > _MAX_SOURCE_BYTES:
            _invalid()
        data = cast(bytes, source)
        return _Oracle(
            self._issuer, _ATTESTATION_VERSION, "final-oracle", 6,
            _sha256(data), inspect_answer_source(data),
        )

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
        self._require_stage(1)
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
        if cancelled:
            self._cancelled = True
            _invalid()
        return _Cell(
            self._issuer,
            _ATTESTATION_VERSION,
            "cell",
            2,
            cast(IpythonHostExpectedIdentity, identity),
            _sha256(cast(bytes, cell)),
            cast(str, bounded_model_digest),
            cast(int, request_count),
            cast(int, input_bytes),
            cast(int, output_bytes),
            ("ipython",),
            cast(bool, cancelled),
        )

    def _attest_broker_revocation(
        self, *, session_id: object = "host-attested", request_count: object = 1,
        input_bytes: object = 1, output_bytes: object = 1,
    ) -> _Revocation:
        self._require_stage(3)
        if (
            type(session_id) is not str or not session_id
            or type(request_count) is not int or request_count != 1
            or type(input_bytes) is not int or input_bytes <= 0
            or type(output_bytes) is not int or output_bytes <= 0
        ):
            _invalid()
        return _Revocation(
            self._issuer, _ATTESTATION_VERSION, "revocation", 4,
            cast(str, session_id), cast(int, request_count), cast(int, input_bytes),
            cast(int, output_bytes),
        )

    def _attest_cleanup_and_absence(self) -> _Cleanup:
        self._require_stage(4)
        return _Cleanup(self._issuer, _ATTESTATION_VERSION, "cleanup", 5)

    def record_initial_snapshot(self, snapshot: object) -> None:
        self._require_stage(0)
        if self._initial is not None or not _valid_snapshot(snapshot, self._issuer, "initial", 1):
            _invalid()
        attestation = cast(_Snapshot, snapshot)
        if (
            not attestation.regular_file
            or attestation.oracle_passed
            or attestation.digest != _STARTER_DIGEST
        ):
            _invalid()
        self._initial = attestation
        self._sequence = 1
        self._stages.append("initial-daemon-snapshot-and-failed-host-ast")

    def record_brokered_cell(self, receipt: object) -> None:
        self._require_stage(1)
        if self._cell is not None or not _valid_cell(receipt, self._issuer, "cell", 2):
            _invalid()
        attestation = cast(_Cell, receipt)
        if attestation.identity != self._expected:
            _invalid()
        if attestation.cancelled:
            self._cancelled = True
            _invalid()
        self._cell = attestation
        self._sequence = 2
        self._stages.append("genuine-brokered-ipython-cell")

    def record_post_snapshot(self, snapshot: object) -> None:
        self._require_stage(2)
        if self._post is not None or not _valid_snapshot(snapshot, self._issuer, "post", 3):
            _invalid()
        attestation = cast(_Snapshot, snapshot)
        initial = cast(_Snapshot, self._initial)
        if not attestation.regular_file or attestation.digest == initial.digest:
            _invalid()
        self._post = attestation
        self._sequence = 3
        self._stages.append("changed-post-daemon-snapshot")

    def record_broker_revoked(self, receipt: object) -> None:
        self._require_stage(3)
        if not _valid_revocation(receipt, self._issuer, 4):
            _invalid()
        self._revocation = cast(_Revocation, receipt)
        self._sequence = 4
        self._stages.append("broker-revoked-and-quiescent")

    def record_cleanup(self, receipt: object = None, **unused: object) -> None:
        self._require_stage(4)
        if unused or not _valid_cleanup(receipt, self._issuer, 5):
            _invalid()
        self._cleanup = cast(_Cleanup, receipt)
        self._sequence = 5
        self._stages.append("cleanup-and-absence-verified")

    def finalize_trace(self, final_oracle: object) -> IpythonHostTrace:
        self._require_stage(5)
        if not _valid_oracle(final_oracle, self._issuer, "final-oracle", 6):
            _invalid()
        attestation = cast(_Oracle, final_oracle)
        post = cast(_Snapshot, self._post)
        if not attestation.passed or attestation.digest != post.digest:
            _invalid()
        initial = cast(_Snapshot, self._initial)
        cell = cast(_Cell, self._cell)
        post = cast(_Snapshot, self._post)
        oracle = attestation
        revocation = cast(_Revocation, self._revocation)
        cleanup = cast(_Cleanup, self._cleanup)
        self._stages.append("final-host-ast-success")
        self._completed = True
        self._sequence = 6
        evidence = {
            "version": "prime-ipython-host-evidence/v1",
            "identity": (
                self._expected.assembly_id,
                self._expected.package_id,
                self._expected.implementation_id,
                self._expected.image_digest,
                self._expected.workload_digest,
                self._expected.oracle_digest,
                self._expected.starter_digest,
                self._expected.source_digest,
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
            "attestations": (
                (initial.version, initial.stage, initial.sequence),
                (cell.version, cell.stage, cell.sequence),
                (post.version, post.stage, post.sequence),
                (revocation.version, revocation.stage, revocation.sequence, revocation.session_id,
                 revocation.request_count, revocation.input_bytes, revocation.output_bytes),
                (cleanup.version, cleanup.stage, cleanup.sequence),
                (oracle.version, oracle.stage, oracle.sequence),
            ),
            "snapshots": (initial.digest, initial.regular_file, initial.oracle_passed, post.digest, post.regular_file),
            "oracle": (oracle.digest, oracle.passed),
            "cleanup": (True, True, True),
            "stages": tuple(self._stages),
        }
        return IpythonHostTrace(
            _seal=_SEAL,
            evidence_digest=_sha256(
                json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode(
                    "ascii"
                )
            ),
        )

    def _require_active(self) -> None:
        if self._cancelled or self._completed:
            _invalid()

    def _require_stage(self, expected: int) -> None:
        self._require_active()
        if self._sequence != expected:
            _invalid()


def _new_ipython_host_supervisor(expected_identity: object) -> IpythonHostSupervisor:
    """Private TCB factory; public construction cannot mint a completion."""
    return IpythonHostSupervisor(expected_identity, _seal=_SUPERVISOR_SEAL)


def _valid_snapshot(value: object, issuer: object, stage: str, sequence: int) -> bool:
    return (
        type(value) is _Snapshot
        and value.issuer is issuer
        and value.version == _ATTESTATION_VERSION
        and value.stage == stage
        and value.sequence == sequence
        and _valid_digest(value.digest)
        and type(value.regular_file) is bool
        and type(value.oracle_passed) is bool
    )


def _valid_cell(value: object, issuer: object, stage: str, sequence: int) -> bool:
    if type(value) is not _Cell or value.issuer is not issuer:
        return False
    tools = value.tools
    return (
        _valid_identity(value.identity)
        and value.version == _ATTESTATION_VERSION
        and value.stage == stage
        and value.sequence == sequence
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


def _valid_oracle(value: object, issuer: object, stage: str, sequence: int) -> bool:
    return (
        type(value) is _Oracle
        and value.issuer is issuer
        and value.version == _ATTESTATION_VERSION
        and value.stage == stage
        and value.sequence == sequence
        and _valid_digest(value.digest)
        and type(value.passed) is bool
    )


def _valid_identity(value: object) -> bool:
    return (
        type(value) is IpythonHostExpectedIdentity
        and type(value.assembly_id) is str
        and type(value.package_id) is str
        and type(value.implementation_id) is str
        and type(value.image_digest) is str
        and type(value.workload_digest) is str
        and type(value.oracle_digest) is str
        and type(value.starter_digest) is str
        and type(value.source_digest) is str
        and value.assembly_id == _ASSEMBLY_ID
        and value.package_id == _PACKAGE_ID
        and value.implementation_id == _IMPLEMENTATION_ID
        and _valid_digest(value.image_digest)
        and value.workload_digest == _WORKLOAD_DIGEST
        and value.oracle_digest == _ORACLE_DIGEST
        and value.starter_digest == _STARTER_DIGEST
        and value.source_digest == _SOURCE_DIGEST
    )


def _valid_revocation(value: object, issuer: object, sequence: int) -> bool:
    return (
        type(value) is _Revocation and value.issuer is issuer
        and value.version == _ATTESTATION_VERSION and value.stage == "revocation"
        and value.sequence == sequence and type(value.session_id) is str and bool(value.session_id)
        and type(value.request_count) is int and value.request_count == 1
        and type(value.input_bytes) is int and value.input_bytes > 0
        and type(value.output_bytes) is int and value.output_bytes > 0
    )


def _valid_cleanup(value: object, issuer: object, sequence: int) -> bool:
    return type(value) is _Cleanup and value.issuer is issuer and value.version == _ATTESTATION_VERSION and value.stage == "cleanup" and value.sequence == sequence


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
