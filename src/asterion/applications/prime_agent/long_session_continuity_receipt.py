"""Closed provider-free evidence for Prime long-session continuity."""

from __future__ import annotations

from dataclasses import dataclass
import re

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)


_RUNTIME_BUILD_ID = re.compile(r"[0-9a-z][0-9a-z._-]{0,127}")
_PUBLIC_REPORT_FIELDS = frozenset(
    {
        "format",
        "app_version",
        "daemon_protocol",
        "daemon_schema_revision",
        "fake_daemon",
        "model_credential_reads",
        "provider_operations",
        "runtime_build_id",
        "scenario_checks",
    }
)
_REQUIRED_CHECKS = {
    "prime-parity.session.fork-clone": frozenset(
        {"prime-fork-clone-roundtrip-passed", "source-resume-roundtrip-passed"}
    ),
    "prime-parity.session.persistence-naming": frozenset(
        {"prime-detach-attach-passed", "prime-name-roundtrip-passed"}
    ),
    "prime-parity.session.resume-delete": frozenset(
        {"prime-exact-delete-passed", "prime-resume-roundtrip-passed"}
    ),
    "prime-parity.session.tree-navigation": frozenset(
        {"prime-tree-navigation-roundtrip-passed", "tree-private-content-redaction-passed"}
    ),
}
_PROVIDER_FREE_SCENARIO_IDS = frozenset(
    {
        "prime-parity.session.delivery",
        "prime-parity.session.fork-clone",
        "prime-parity.session.persistence-naming",
        "prime-parity.session.resume-delete",
        "prime-parity.session.rich-attachments",
        "prime-parity.session.tree-navigation",
        "prime-parity.session.usage-status",
    }
)


class LongSessionContinuityReceiptError(ValueError):
    """Raised when continuity facts cannot support the fixed receipt."""


@dataclass(frozen=True, repr=False)
class LongSessionContinuityObservation:
    """Private normalized facts; session identities and content are omitted."""

    detached_reattached: bool
    name_persisted: bool
    source_resume_roundtrip: bool
    resume_delete_roundtrip: bool
    identity_separated: bool
    public_projection_redacted: bool

    def __repr__(self) -> str:
        return "LongSessionContinuityObservation(redacted)"


def long_session_continuity_observation_from_public_report(
    report: object,
) -> LongSessionContinuityObservation:
    """Convert only the exact real provider-free session report to private facts."""

    if (
        type(report) is not dict
        or frozenset(report) != _PUBLIC_REPORT_FIELDS
        or report["format"] != "asterion.prime-session-context-observation/v1"
        or report["app_version"] != "0.7.1"
        or report["daemon_protocol"] != 7
        or report["daemon_schema_revision"] != 14
        or report["fake_daemon"] is not False
        or report["model_credential_reads"] != 0
        or report["provider_operations"] != 0
        or type(report["runtime_build_id"]) is not str
        or _RUNTIME_BUILD_ID.fullmatch(report["runtime_build_id"]) is None
        or type(report["scenario_checks"]) is not dict
    ):
        raise LongSessionContinuityReceiptError(
            "long-session continuity receipt is invalid"
        )
    checks = report["scenario_checks"]
    if any(
        type(checks.get(scenario_id)) is not list
        or not required.issubset(checks[scenario_id])
        for scenario_id, required in _REQUIRED_CHECKS.items()
    ) or frozenset(checks) != _PROVIDER_FREE_SCENARIO_IDS or any(
        type(check_id) is not str
        for check_ids in checks.values()
        if type(check_ids) is list
        for check_id in check_ids
    ):
        raise LongSessionContinuityReceiptError(
            "long-session continuity receipt is invalid"
        )
    observation = LongSessionContinuityObservation(
        detached_reattached=True,
        name_persisted=True,
        source_resume_roundtrip=True,
        resume_delete_roundtrip=True,
        identity_separated=True,
        public_projection_redacted=True,
    )
    verify_long_session_continuity_receipt(observation)
    return observation


def verify_long_session_continuity_receipt(
    observation: object,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.PROVIDER_FREE,
) -> PrimeEvidenceReceipt:
    """Emit the sole provider-free receipt for one continuous Prime session."""

    if (
        type(observation) is not LongSessionContinuityObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.PROVIDER_FREE
        or observation.detached_reattached is not True
        or observation.name_persisted is not True
        or observation.source_resume_roundtrip is not True
        or observation.resume_delete_roundtrip is not True
        or observation.identity_separated is not True
        or observation.public_projection_redacted is not True
    ):
        raise LongSessionContinuityReceiptError(
            "long-session continuity receipt is invalid"
        )
    return validate_prime_evidence_receipt(
        PrimeEvidenceReceipt(
            scenario_id="prime.long-session-continuity/v1",
            level=PrimeEvidenceLevel.PROVIDER_FREE,
            status="PASS",
        )
    )
