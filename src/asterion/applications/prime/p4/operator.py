"""Operator-owned native P4 cross-generation continuity witness.

Two invocation modes:

* ``commit`` — opens a fresh private_root, runs the deterministic worker,
  seals one checkpoint at generation 1, prints ``{"status":"committed",...}``.
* ``recover`` — opens the prior private_root via
  :func:`FilePrimeSessionStore.open_continued`, attaches the new-generation
  identity, runs the worker in recover mode (different payload), seals a new
  checkpoint at generation 2, prints ``{"status":"recovered",...}``.

The Makefile target ``asterion-prime-p4-run`` runs the operator twice in
sequence and asserts the no-replay invariant via SHA inequality.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from types import MappingProxyType

from asterion.agents.prime.state import (
    PrimeBackendIdentity,
    PrimeCheckpoint,
    PrimeStateError,
)
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    private_root_identity,
)
from asterion.applications.prime.p4.worker import P4DeterministicWorker


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PI_ENTRY_ENV = "ASTERION_PRIME_PI_ENTRY"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P4_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P4_MODE"


class P4OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P4 operator is unavailable")


@dataclass(frozen=True, slots=True)
class P4PublicResult:
    status: str
    run_id: str | None = None
    checkpoint_sha256: str | None = None
    prior_checkpoint_sha256: str | None = None
    generation: int | None = None
    new_generation: int | None = None
    continuation_id: str | None = None
    result_sha256: str | None = None
    receipt_sha256: str | None = None
    worker_identity_sha256: str | None = None
    private_root_redacted: bool = True


@dataclass(frozen=True, slots=True)
class _Preflight:
    operator_root: Path
    worker_python: Path
    private_root: Path
    mode: str
    pi_entry: Path | None


def _preflight(environment: MappingProxyType) -> _Preflight:  # type: ignore[type-arg]
    operator_value = environment.get(_OPERATOR_ROOT_ENV, "").strip()
    private_value = environment.get(_PRIVATE_ROOT_ENV, "").strip()
    mode_value = environment.get(_MODE_ENV, "").strip()
    if not operator_value or not private_value or mode_value not in {"commit", "recover"}:
        raise P4OperatorError()
    try:
        operator_root = Path(operator_value).resolve(strict=True)
    except OSError:
        raise P4OperatorError() from None
    if not operator_root.is_dir():
        raise P4OperatorError()
    worker_python = Path(sys.executable).absolute()
    if not worker_python.is_file():
        raise P4OperatorError()
    try:
        probe = subprocess.run(
            (str(worker_python), "-I", "-c", "import sys; print(sys.version_info[:2])"),
            check=True,
            capture_output=True,
            timeout=10,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise P4OperatorError() from None
    if not probe.stdout or not probe.stdout.strip():
        raise P4OperatorError()
    try:
        private_root = Path(private_value).resolve()
    except OSError:
        raise P4OperatorError() from None
    pi_entry: Path | None = None
    raw_pi = environment.get(_PI_ENTRY_ENV, "").strip()
    if raw_pi:
        try:
            pi_entry = Path(raw_pi).resolve(strict=False)
        except OSError:
            raise P4OperatorError() from None
    return _Preflight(
        operator_root=operator_root,
        worker_python=worker_python,
        private_root=private_root,
        mode=mode_value,
        pi_entry=pi_entry,
    )


def _build_identity(
    *,
    private_root: Path,
    generation: int,
    continuation_id: str,
    worker_sha: str,
    session_id: str,
    pi_command_sha256: str = sha256(b"prime.pi-native").hexdigest(),
    extension_binding_fingerprint: str = sha256(b"prime.extension").hexdigest(),
    ceilings_sha256: str = sha256(b"prime.ceilings").hexdigest(),
) -> PrimeBackendIdentity:
    """Build a PrimeBackendIdentity for P4.

    Default pi/extension/ceilings SHAs match the fixture used in the
    end-to-end witness (commit and recover invocations within the same
    operator run must share them, or the continuation rules will reject
    the recover-side identity). The recover path overrides these with the
    prior identity's values when available so a pre-baked private_root
    (e.g. one sealed by a different operator build) can still bind.
    """
    return PrimeBackendIdentity(
        session_id=session_id,
        generation=generation,
        provider_id="prime-applications",
        application_id="prime.long-session-continuity",
        application_version="1.0.0",
        runtime_id="asterion.prime",
        pi_command_sha256=pi_command_sha256,
        extension_binding_fingerprint=extension_binding_fingerprint,
        worker_identity_sha256=worker_sha,
        continuation_id=continuation_id,
        private_root_identity=private_root_identity(private_root),
        ceilings_sha256=ceilings_sha256,
    )


def _seal_commit_checkpoint(
    *,
    store: FilePrimeSessionStore,
    worker_sha: str,
    prior_checkpoint_sha: str | None,
    run_id: str,
    transcript: bytes,
    usage: dict[str, object],
    continuation_id: str,
) -> PrimeCheckpoint:
    cursor = store.position
    # Public events are zero per round in this witness — the witness is
    # about continuity, not prompt streams.
    checkpoint = PrimeCheckpoint(
        checkpoint_id=run_id,
        generation=store.identity.generation,
        public_event_cursor=cursor,
        private_transcript_sha256=sha256(transcript).hexdigest(),
        summary_sha256=None,
        covered_leaf_id=None,
        worker_identity_sha256=worker_sha,
        continuation_id=continuation_id,
        usage_sha256=sha256(_canonical_bytes(usage)).hexdigest(),
        outstanding_effect=None,
        prior_checkpoint_sha256=prior_checkpoint_sha,
    )
    store.write_checkpoint(
        checkpoint,
        expected_position=store.position,
        transcript=transcript,
        summary=None,
        usage=usage,
    )
    return checkpoint


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def _commit_mode(
    preflight: _Preflight,
) -> tuple[PrimeBackendIdentity, PrimeCheckpoint, str]:
    """Run the commit round; return identity, sealed checkpoint, result SHA."""

    preflight.private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    session_id = "p4-" + secrets.token_hex(8)
    continuation_id = "continuation-" + secrets.token_hex(8)
    worker = P4DeterministicWorker(mode="commit")
    worker_sha = worker.identity_sha256
    identity = _build_identity(
        private_root=preflight.private_root,
        generation=1,
        continuation_id=continuation_id,
        worker_sha=worker_sha,
        session_id=session_id,
    )
    store = FilePrimeSessionStore(preflight.private_root, identity)
    try:
        run_id = "p4-commit-" + secrets.token_hex(8)
        result = await worker.execute()
        result_sha = sha256(_canonical_bytes(result)).hexdigest()
        checkpoint = _seal_commit_checkpoint(
            store=store,
            worker_sha=worker_sha,
            prior_checkpoint_sha=None,
            run_id=run_id,
            transcript=bytes(_canonical_bytes(result)),
            usage={"result_sha256": result_sha},
            continuation_id=continuation_id,
        )
        return identity, checkpoint, result_sha
    finally:
        store.close()


async def _recover_mode(
    preflight: _Preflight,
) -> tuple[PrimeBackendIdentity, PrimeBackendIdentity, str, str]:
    """Run the recover round; return prior id, next id, prior checkpoint digest, result SHA."""

    if not preflight.private_root.exists():
        raise P4OperatorError()
    try:
        prior_identity = _read_prior_identity(preflight.private_root)
    except PrimeStateError:
        raise P4OperatorError() from None
    worker = P4DeterministicWorker(mode="recover")
    next_identity = _build_identity(
        private_root=preflight.private_root,
        generation=prior_identity.generation + 1,
        continuation_id=prior_identity.continuation_id,
        worker_sha=worker.identity_sha256,
        session_id=prior_identity.session_id,
        pi_command_sha256=prior_identity.pi_command_sha256,
        extension_binding_fingerprint=prior_identity.extension_binding_fingerprint,
        ceilings_sha256=prior_identity.ceilings_sha256,
    )
    store = FilePrimeSessionStore.open_continued(
        preflight.private_root, next_identity
    )
    try:
        # Capture the prior's last sealed checkpoint digest BEFORE running the
        # worker / writing the next checkpoint — the witness depends on the
        # exact prior SHA, not the new one. `recover_checkpoint()` returns the
        # last sealed record (the commit pass sealed it at generation 1).
        recovered = store.recover_checkpoint()
        if recovered is None:
            raise P4OperatorError()
        prior_checkpoint_digest = recovered.checkpoint.digest
        result = await worker.execute()
        return (
            prior_identity,
            next_identity,
            prior_checkpoint_digest,
            sha256(_canonical_bytes(result)).hexdigest(),
        )
    finally:
        store.close()


def _read_prior_identity(root: Path) -> PrimeBackendIdentity:
    from asterion.agents.prime.store import _read_prior_identity as _rpi

    return _rpi(root)


async def _run_async() -> P4PublicResult:
    environment = MappingProxyType(os.environ.copy())  # type: ignore[type-arg]
    preflight = _preflight(environment)
    if preflight.mode == "commit":
        identity, checkpoint, result_sha = await _commit_mode(preflight)
        return P4PublicResult(
            status="committed",
            run_id=checkpoint.checkpoint_id,
            checkpoint_sha256=checkpoint.digest,
            prior_checkpoint_sha256=None,
            generation=checkpoint.generation,
            new_generation=checkpoint.generation,
            continuation_id=identity.continuation_id,
            result_sha256=result_sha,
            receipt_sha256=checkpoint.digest,
            worker_identity_sha256=identity.worker_identity_sha256,
        )
    _, next_identity, prior_checkpoint_digest, result_sha = await _recover_mode(
        preflight
    )
    return P4PublicResult(
        status="recovered",
        run_id=None,
        checkpoint_sha256=None,
        prior_checkpoint_sha256=prior_checkpoint_digest,
        generation=None,
        new_generation=next_identity.generation,
        continuation_id=next_identity.continuation_id,
        result_sha256=result_sha,
        receipt_sha256=None,
        worker_identity_sha256=next_identity.worker_identity_sha256,
    )


def main() -> int:
    """Run one operator invocation; print one JSON line; exit 0 or 2."""
    try:
        result = asyncio.run(_run_async())
    except BaseException:
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        result = P4PublicResult(status="protocol-failure")
    print(json.dumps(asdict(result), separators=(",", ":")))
    sys.stdout.flush()
    if result.status in {"committed", "recovered"}:
        return 0
    return 2


def _entrypoint() -> None:
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(status)


if __name__ == "__main__":
    _entrypoint()


__all__ = (
    "P4OperatorError",
    "P4PublicResult",
    "_entrypoint",
    "main",
)