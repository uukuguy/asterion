"""Public projection identities for the fixed P6 acceptance product."""

from __future__ import annotations

from hashlib import sha256
import json

from asterion.control.harness import HarnessRevision, HarnessSnapshot


class ContinualImprovementAcceptanceError(ValueError):
    """Raised without disclosing Harness-private values."""


def _digest(value: object) -> str:
    return "sha256:" + sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def continual_improvement_snapshot_sha256(snapshot: object) -> str:
    """Return the canonical public projection digest for one Harness snapshot."""

    if type(snapshot) is not HarnessSnapshot:
        raise ContinualImprovementAcceptanceError("continual improvement acceptance is invalid")
    return _digest({
        "entries": [dict(entry.to_public_mapping()) for entry in snapshot.entries],
        "revision_id": snapshot.revision_id,
        "scope": dict(snapshot.scope.to_mapping()),
        "sequence": snapshot.sequence,
        "snapshot_id": snapshot.snapshot_id,
    })


def continual_improvement_revision_sha256(revision: object) -> str:
    """Return the canonical public projection digest for one Harness revision."""

    if type(revision) is not HarnessRevision:
        raise ContinualImprovementAcceptanceError("continual improvement acceptance is invalid")
    return _digest({
        "baseline_snapshot_id": revision.baseline_snapshot_id,
        "effect_digest": revision.effect_digest,
        "proposal_digest": revision.proposal_digest,
        "revision_id": revision.revision_id,
        "rollback_revision_id": revision.rollback_revision_id,
        "scope": dict(revision.scope.to_mapping()),
        "sequence": revision.sequence,
        "status": revision.status,
        "usage": dict(revision.usage),
    })
