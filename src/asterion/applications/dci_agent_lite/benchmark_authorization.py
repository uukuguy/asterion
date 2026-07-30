"""Opaque process-local authorization for DCI benchmark execution."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
)
from asterion.benchmarks import (
    ApplicationRef,
    BenchmarkExecutionAuthorization,
)
from asterion.capability_packages import BenchmarkSuiteRef, CapabilitySourceLock


_RUN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class DciBenchmarkAuthorizationError(ValueError):
    """Raised when a DCI execution claim is absent, forged, or replayed."""


@dataclass(frozen=True, slots=True)
class DciBenchmarkExecutionAuthorization:
    instance_selector: str = field(repr=False)
    application_ref: ApplicationRef = field(repr=False)
    suite_ref: BenchmarkSuiteRef = field(repr=False)
    case_limit: int = field(repr=False)
    package_locks: tuple[CapabilitySourceLock, ...] = field(repr=False)
    evidence_root: Path = field(repr=False)
    run_id: str = field(repr=False)
    resume_run_id: str | None = field(repr=False)
    issuer_nonce: object = field(repr=False)
    claim_nonce: object = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_locks", tuple(self.package_locks))


class DciBenchmarkExecutionAuthorizer:
    """Issue and advance exact one-use claims for one selected instance."""

    def __init__(self, instance: DciBenchmarkInstance) -> None:
        if not isinstance(instance, DciBenchmarkInstance):
            _fail()
        self._instance = instance
        self._issuer_nonce = object()
        self._states: dict[
            object,
            tuple[DciBenchmarkExecutionAuthorization, str],
        ] = {}

    def issue(
        self,
        *,
        case_limit: int,
        package_locks: tuple[CapabilitySourceLock, ...],
        evidence_root: Path,
        resume_run_id: str | None,
    ) -> DciBenchmarkExecutionAuthorization:
        try:
            locks = tuple(package_locks)
            if (
                type(case_limit) is not int
                or case_limit < 1
                or not locks
                or not all(isinstance(lock, CapabilitySourceLock) for lock in locks)
                or not isinstance(evidence_root, Path)
                or not evidence_root.is_absolute()
                or (
                    resume_run_id is not None
                    and (
                        type(resume_run_id) is not str
                        or _RUN_ID.fullmatch(resume_run_id) is None
                    )
                )
            ):
                _fail()
            run_id = resume_run_id or f"run-{uuid.uuid4().hex}"
            claim_nonce = object()
            claim = DciBenchmarkExecutionAuthorization(
                instance_selector=self._instance.selector,
                application_ref=self._instance.application_ref,
                suite_ref=self._instance.suite_ref,
                case_limit=case_limit,
                package_locks=locks,
                evidence_root=evidence_root,
                run_id=run_id,
                resume_run_id=resume_run_id,
                issuer_nonce=self._issuer_nonce,
                claim_nonce=claim_nonce,
            )
            self._states[claim_nonce] = (claim, "issued")
            return claim
        except DciBenchmarkAuthorizationError:
            raise
        except Exception:
            _fail()

    def authorize_benchmark_execution(
        self,
        authorization: BenchmarkExecutionAuthorization,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int,
    ) -> str:
        claim = self._claim(authorization, expected_state="issued")
        if (
            application_ref != claim.application_ref
            or suite_ref != claim.suite_ref
            or case_limit != claim.case_limit
        ):
            _fail()
        self._states[claim.claim_nonce] = (claim, "planned")
        return claim.run_id

    def authorize_provider_loading(
        self,
        authorization: BenchmarkExecutionAuthorization,
        *,
        package_locks: tuple[CapabilitySourceLock, ...],
    ) -> DciBenchmarkExecutionAuthorization:
        claim = self._claim(authorization, expected_state="planned")
        if tuple(package_locks) != claim.package_locks:
            _fail()
        self._states[claim.claim_nonce] = (claim, "providers-loaded")
        return claim

    def authorize_run(
        self,
        authorization: BenchmarkExecutionAuthorization,
        *,
        run_id: str,
        evidence_root: Path,
    ) -> DciBenchmarkExecutionAuthorization:
        claim = self._claim(
            authorization,
            expected_state="providers-loaded",
        )
        if run_id != claim.run_id or evidence_root != claim.evidence_root:
            _fail()
        self._states[claim.claim_nonce] = (claim, "running")
        return claim

    def _claim(
        self,
        authorization: object,
        *,
        expected_state: str,
    ) -> DciBenchmarkExecutionAuthorization:
        if type(authorization) is not DciBenchmarkExecutionAuthorization:
            _fail()
        claim = authorization
        record = self._states.get(claim.claim_nonce)
        if (
            claim.issuer_nonce is not self._issuer_nonce
            or claim.instance_selector != self._instance.selector
            or claim.application_ref != self._instance.application_ref
            or claim.suite_ref != self._instance.suite_ref
            or type(claim.case_limit) is not int
            or claim.case_limit < 1
            or not claim.package_locks
            or not all(
                isinstance(lock, CapabilitySourceLock)
                for lock in claim.package_locks
            )
            or not isinstance(claim.evidence_root, Path)
            or not claim.evidence_root.is_absolute()
            or _RUN_ID.fullmatch(claim.run_id) is None
            or (
                claim.resume_run_id is not None
                and claim.resume_run_id != claim.run_id
            )
            or record is None
            or record[0] is not claim
            or record[1] != expected_state
        ):
            _fail()
        return claim


def _fail() -> None:
    raise DciBenchmarkAuthorizationError(
        "DCI benchmark authorization is invalid"
    ) from None


__all__ = (
    "DciBenchmarkAuthorizationError",
    "DciBenchmarkExecutionAuthorization",
    "DciBenchmarkExecutionAuthorizer",
)
