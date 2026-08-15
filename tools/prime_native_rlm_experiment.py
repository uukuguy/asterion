"""Pure preparation boundary for one bounded native Prime RLM experiment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from types import MappingProxyType
from typing import Awaitable, Callable

from asterion.control.authority import AuthorityEnvelope, BudgetUsage
from asterion.immutable import RedactedImmutableMapping
from tools.verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority


_MAX_COST_MICROS = 500_000
_MAX_DEADLINE_MS = 600_000
_MODEL_KEY = "ASTERION_PRIME_EXPERIMENT_MODEL"


class PrimeRlmExperimentError(RuntimeError):
    """Raised with a public-safe native RLM experiment preparation failure."""


@dataclass(frozen=True, repr=False)
class NativeRlmExperimentLimits:
    cost_micros: int
    deadline_ms: int


@dataclass(frozen=True, repr=False)
class NativeRlmModelSelection:
    provider: str
    model: str
    credential_env: str


@dataclass(frozen=True, repr=False)
class NativeRlmDaemonPlan:
    argv: tuple[str, ...]
    environ: Mapping[str, str]
    socket_path: Path

    def __repr__(self) -> str:
        return "NativeRlmDaemonPlan(argv=<redacted>, environ=<redacted>)"


@dataclass(frozen=True, repr=False)
class NativeRlmExperimentReservation:
    authority: AuthorityEnvelope
    limits: NativeRlmExperimentLimits
    configuration_digest: str
    consumed: bool = False

    def consume(self) -> NativeRlmExperimentReservation:
        if self.consumed:
            raise PrimeRlmExperimentError("Native RLM experiment reservation is inactive")
        return replace(self, consumed=True)


@dataclass(frozen=True, repr=False)
class NativeRlmProbeResult:
    terminal: str
    child_started: bool
    message_delivered: bool
    child_deleted: bool
    usage: BudgetUsage


ProbeRunner = Callable[[NativeRlmExperimentReservation], Awaitable[NativeRlmProbeResult]]


def resolve_native_rlm_model(environ: Mapping[str, str]) -> NativeRlmModelSelection:
    """Resolve the sole model/provider pairing authorized for this first probe."""
    if not isinstance(environ, Mapping) or environ.get(_MODEL_KEY) != "deepseek-v4-flash":
        raise PrimeRlmExperimentError("Native RLM experiment model is invalid")
    return NativeRlmModelSelection("deepseek", "deepseek-v4-flash", "DEEPSEEK_API_KEY")


def build_native_rlm_daemon_plan(
    node_executable: Path,
    runtime_entry: Path,
    socket_path: Path,
    selection: NativeRlmModelSelection,
    environ: Mapping[str, str],
) -> NativeRlmDaemonPlan:
    """Build the exact direct daemon invocation without starting it."""
    if (
        not all(isinstance(value, Path) for value in (node_executable, runtime_entry, socket_path))
        or not isinstance(selection, NativeRlmModelSelection)
    ):
        raise PrimeRlmExperimentError("Native RLM daemon plan is invalid")
    environment = build_native_rlm_daemon_environment(
        environ, credential_env=selection.credential_env
    )
    return NativeRlmDaemonPlan(
        (
            str(node_executable), str(runtime_entry), "--mode", "daemon", "--daemon-socket",
            str(socket_path), "--provider", selection.provider, "--model", selection.model,
        ),
        environment,
        socket_path,
    )


async def start_native_rlm_daemon(
    plan: NativeRlmDaemonPlan,
    *,
    launcher: Callable[[NativeRlmDaemonPlan], Awaitable[object]],
    timeout_seconds: float,
) -> object:
    """Start one owned daemon and wait only for its designated socket."""
    if not isinstance(plan, NativeRlmDaemonPlan) or not callable(launcher) or timeout_seconds <= 0:
        raise PrimeRlmExperimentError("Native RLM daemon launch is invalid")
    process = await launcher(plan)
    deadline = time.monotonic() + timeout_seconds
    while not plan.socket_path.exists():
        if getattr(process, "returncode", None) is not None or time.monotonic() >= deadline:
            raise PrimeRlmExperimentError("Native RLM daemon did not become ready")
        await asyncio.sleep(0.01)
    return process


def build_native_rlm_daemon_environment(
    environ: Mapping[str, str], *, credential_env: str
) -> Mapping[str, str]:
    """Forward the sole selected credential to the owned Prime daemon."""
    try:
        if (
            not isinstance(environ, Mapping)
            or not isinstance(credential_env, str)
            or not credential_env
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items())
            or credential_env not in environ
        ):
            raise ValueError
        values = {
            key: environ[key]
            for key in ("HOME", "PATH", credential_env)
            if key in environ
        }
        if "HOME" not in values or "PATH" not in values:
            raise ValueError
        return RedactedImmutableMapping(values)
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM daemon environment is invalid") from None


def prepare_native_rlm_experiment(
    authority_path: Path,
    *,
    max_cost_micros: int,
    deadline_ms: int,
    environ: Mapping[str, str],
    now_ms: int | None = None,
) -> NativeRlmExperimentReservation:
    """Validate all non-executing admission inputs without reading process state."""
    try:
        if (
            not isinstance(authority_path, Path)
            or not isinstance(environ, Mapping)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items())
            or isinstance(max_cost_micros, bool)
            or not isinstance(max_cost_micros, int)
            or max_cost_micros < 1
            or max_cost_micros > _MAX_COST_MICROS
            or isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or deadline_ms < 1
            or deadline_ms > _MAX_DEADLINE_MS
        ):
            raise ValueError
        model = environ.get(_MODEL_KEY)
        if not isinstance(model, str) or not model:
            raise ValueError
        authority = load_bounded_rlm_authority(
            authority_path, max_cost_micros=max_cost_micros, now_ms=now_ms
        )
        if authority.max_action_deadline_ms > deadline_ms:
            raise ValueError
        digest = sha256(b"asterion.prime.native-rlm\0" + model.encode()).hexdigest()
        return NativeRlmExperimentReservation(
            authority=authority,
            limits=NativeRlmExperimentLimits(max_cost_micros, deadline_ms),
            configuration_digest=digest,
        )
    except (PrimeVerificationError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM experiment authorization is invalid") from None


def write_native_rlm_experiment_receipt(
    root: Path,
    reservation: NativeRlmExperimentReservation,
    *,
    terminal: str,
    child_started: bool,
    message_delivered: bool,
    child_deleted: bool,
    usage: BudgetUsage,
) -> Mapping[str, object]:
    """Atomically write a private, public-safe observation for one reservation."""
    if (
        not isinstance(root, Path)
        or not root.is_dir()
        or not isinstance(reservation, NativeRlmExperimentReservation)
        or not reservation.consumed
        or terminal not in {"completed", "failed", "cancelled", "uncertain"}
        or not all(isinstance(value, bool) for value in (child_started, message_delivered, child_deleted))
        or not isinstance(usage, BudgetUsage)
    ):
        raise PrimeRlmExperimentError("Native RLM experiment receipt is invalid")
    complete = child_started and message_delivered and child_deleted
    in_budget = usage.cost_micros <= reservation.limits.cost_micros
    status = "PASS" if terminal == "completed" and complete and in_budget else "uncertain"
    payload = {
        "format": "asterion.prime-native-rlm-receipt/v1",
        "authority_id": reservation.authority.authority_id,
        "authority_revision": reservation.authority.revision,
        "configuration_digest": reservation.configuration_digest,
        "terminal": terminal,
        "child_started": child_started,
        "message_delivered": message_delivered,
        "child_deleted": child_deleted,
        "usage": vars(usage),
        "status": status,
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".native-rlm-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, root / "native-rlm-experiment-receipt.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return MappingProxyType(
        {
            "format": payload["format"],
            "configuration_digest": reservation.configuration_digest,
            "status": status,
            "terminal": terminal,
            "child_started": child_started,
            "message_delivered": message_delivered,
            "child_deleted": child_deleted,
            "usage": MappingProxyType(dict(vars(usage))),
        }
    )


async def run_native_rlm_experiment(
    reservation: NativeRlmExperimentReservation,
    runner: ProbeRunner,
) -> Mapping[str, object]:
    """Consume a reservation once and classify an injected native probe result."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not callable(runner):
        raise PrimeRlmExperimentError("Native RLM experiment runner is invalid")
    consumed = reservation.consume()
    try:
        async with asyncio.timeout(consumed.limits.deadline_ms / 1000):
            result = await runner(consumed)
    except TimeoutError:
        return MappingProxyType({"status": "uncertain", "terminal": "uncertain"})
    if not isinstance(result, NativeRlmProbeResult) or not isinstance(result.usage, BudgetUsage):
        raise PrimeRlmExperimentError("Native RLM experiment result is invalid")
    complete = result.child_started and result.message_delivered and result.child_deleted
    in_budget = result.usage.cost_micros <= consumed.limits.cost_micros
    status = "PASS" if result.terminal == "completed" and complete and in_budget else "External-limited"
    return MappingProxyType({"status": status, "terminal": result.terminal})
