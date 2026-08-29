"""Closed public evidence reduction for the bounded Prime Phase 1 probe."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from asterion.control.private_store import PrivateResultPublication


class PrimeBoundedLoopError(RuntimeError):
    """Raised when bounded-loop evidence is incomplete or malformed."""


class BoundedLoopPrivateResultStore:
    """One-run result publisher that never retains or exposes raw probe output."""

    def publish_application_result(
        self,
        *,
        action_id: str,
        provider_id: str,
        application_id: str,
        version: str,
        runtime_id: str,
        idempotency_key: str,
        run_id: str,
        result: object,
    ) -> PrivateResultPublication:
        del provider_id, application_id, version, runtime_id, idempotency_key, run_id, result
        try:
            return PrivateResultPublication(
                action_id=action_id,
                receipt_ref=f"bounded-receipt-{action_id}",
            )
        except ValueError:
            raise PrimeBoundedLoopError("Prime bounded loop result is invalid") from None


_REQUIRED_ASSERTIONS = frozenset(
    {
        "root_created",
        "application_receipted",
        "child_completed",
        "detach_attached",
        "checkpoint_recovered",
        "cancelled",
        "budget_limited",
        "public_redacted",
    }
)

_REQUIRED_ACTION_STATUSES = frozenset(
    {
        "application.invoke",
        "child.spawn",
        "checkpoint.create",
        "session.cancel",
        "budget.probe",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def derive_bounded_loop_causal_digests(
    identities: Mapping[str, object],
) -> dict[str, str]:
    """Hash the exact observed identity pair for every bounded operation.

    The public receipt never exposes event, command, or action IDs.  A digest is
    accepted only when both identities were observed for the one fixed operation
    class; callers cannot provide a precomputed hash instead.
    """
    if not isinstance(identities, Mapping) or set(identities) != _REQUIRED_ACTION_STATUSES:
        raise PrimeBoundedLoopError("Prime bounded loop causal identities are invalid")
    digests: dict[str, str] = {}
    for operation in sorted(_REQUIRED_ACTION_STATUSES):
        value = identities[operation]
        if (
            isinstance(value, (str, bytes))
            or not isinstance(value, Sequence)
            or len(value) != 2
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise PrimeBoundedLoopError(
                "Prime bounded loop causal identities are invalid"
            )
        digests[operation] = sha256(
            (operation + "\0" + value[0] + "\0" + value[1]).encode("utf-8")
        ).hexdigest()
    return digests


def reduce_native_probe_observation(
    *,
    session_events: Sequence[str],
    application_receipted: bool,
    child_completed: bool,
    detached_attached: bool,
    checkpoint_recovered: bool,
    cancelled: bool,
    budget_limited: bool,
    usage: Mapping[str, object],
    causal_identities: Mapping[str, object],
) -> dict[str, object]:
    """Reduce one fully observed native probe without accepting caller claims."""
    action_statuses = {
        "application.invoke": "succeeded" if application_receipted else "failed",
        "child.spawn": "succeeded" if child_completed else "failed",
        "checkpoint.create": "succeeded" if checkpoint_recovered else "failed",
        "session.cancel": "cancelled" if cancelled else "failed",
        "budget.probe": "rejected" if budget_limited else "failed",
    }
    assertions = derive_bounded_loop_assertions(
        session_events=session_events,
        action_statuses=action_statuses,
        detached_attached=detached_attached,
        public_redacted=True,
    )
    return reduce_bounded_loop_evidence(
        assertions,
        usage=usage,
        causal_digests=derive_bounded_loop_causal_digests(causal_identities),
    )


def assertions_from_native_probe_observation(
    *,
    session_events: Sequence[str],
    application_receipted: bool,
    child_completed: bool,
    detached_attached: bool,
    checkpoint_recovered: bool,
    cancelled: bool,
    budget_limited: bool,
) -> dict[str, bool]:
    return derive_bounded_loop_assertions(
        session_events=session_events,
        action_statuses={
            "application.invoke": "succeeded" if application_receipted else "failed",
            "child.spawn": "succeeded" if child_completed else "failed",
            "checkpoint.create": "succeeded" if checkpoint_recovered else "failed",
            "session.cancel": "cancelled" if cancelled else "failed",
            "budget.probe": "rejected" if budget_limited else "failed",
        },
        detached_attached=detached_attached,
        public_redacted=True,
    )


def derive_bounded_loop_assertions(
    *,
    session_events: Sequence[str],
    action_statuses: Mapping[str, str],
    detached_attached: bool,
    public_redacted: bool,
) -> dict[str, bool]:
    """Derive Phase 1 claims from closed control-plane facts.

    This deliberately accepts only the finite set of actions performed by the
    bounded probe.  A caller cannot supply an assertion independently of its
    corresponding event or action result.
    """
    if (
        isinstance(session_events, (str, bytes))
        or not isinstance(session_events, Sequence)
        or any(not isinstance(event, str) for event in session_events)
        or not isinstance(action_statuses, Mapping)
        or set(action_statuses) != _REQUIRED_ACTION_STATUSES
        or any(not isinstance(status, str) for status in action_statuses.values())
        or not isinstance(detached_attached, bool)
        or not isinstance(public_redacted, bool)
    ):
        raise PrimeBoundedLoopError("Prime bounded loop control facts are invalid")

    event_types = frozenset(session_events)
    return {
        "root_created": "session.created" in event_types,
        "application_receipted": action_statuses["application.invoke"] == "succeeded",
        "child_completed": action_statuses["child.spawn"] == "succeeded",
        "detach_attached": detached_attached,
        "checkpoint_recovered": (
            action_statuses["checkpoint.create"] == "succeeded"
            and "session.recovery-required" in event_types
        ),
        "cancelled": action_statuses["session.cancel"] == "cancelled",
        "budget_limited": action_statuses["budget.probe"] == "rejected",
        "public_redacted": public_redacted,
    }


def reduce_bounded_loop_evidence(
    assertions: Mapping[str, object],
    *,
    usage: Mapping[str, object],
    causal_digests: Mapping[str, object],
) -> dict[str, object]:
    """Return PASS only for the complete finite Phase 1 assertion set."""
    if (
        not isinstance(assertions, Mapping)
        or set(assertions) != _REQUIRED_ASSERTIONS
        or any(value is not True for value in assertions.values())
        or not isinstance(usage, Mapping)
        or set(usage) != {"aggregate_tokens"}
        or isinstance(usage["aggregate_tokens"], bool)
        or not isinstance(usage["aggregate_tokens"], int)
        or usage["aggregate_tokens"] < 0
        or not isinstance(causal_digests, Mapping)
        or set(causal_digests) != _REQUIRED_ACTION_STATUSES
        or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in causal_digests.values()
        )
    ):
        raise PrimeBoundedLoopError("Prime bounded loop evidence is incomplete")
    return {
        "causal_digests": dict(causal_digests),
        "status": "PASS",
        "terminal": "completed",
        "usage": {"aggregate_tokens": usage["aggregate_tokens"]},
    }


def write_bounded_loop_receipt(
    root: Path,
    assertions: Mapping[str, object],
    *,
    usage: Mapping[str, object],
    causal_digests: Mapping[str, object],
) -> dict[str, object]:
    """Atomically persist the one public-safe bounded-loop receipt."""
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise PrimeBoundedLoopError("Prime bounded loop receipt root is invalid")
    receipt = reduce_bounded_loop_evidence(
        assertions, usage=usage, causal_digests=causal_digests
    )
    target = root / "bounded-loop-receipt.json"
    temporary = root / ".bounded-loop-receipt.tmp"
    if target.exists() or temporary.exists():
        raise PrimeBoundedLoopError("Prime bounded loop receipt is unavailable")
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise PrimeBoundedLoopError("Prime bounded loop receipt is unavailable") from None
    return receipt
