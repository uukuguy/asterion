"""Operator-owned native P2 fixed-small verification."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from types import MappingProxyType
from collections.abc import Callable

from asterion.applications.first_party_packages import (
    create_prime_programmatic_long_context_native_package,
)
from asterion.applications.prime import create_prime_programmatic_long_context_provider
from asterion.applications.prime.p2.context_service import (
    P2ContextService,
    P2ContextServiceError,
)
from asterion.applications.prime.p2.oracle import P2Oracle, P2OracleError
from asterion.applications.prime.p2.receipt import (
    seal_cleanup_receipt,
    build_native_receipt,
)
from asterion.applications.prime.p2.runtime_binding import (
    P2_RUNTIME_OPTIONS,
    P2WorkerOwnerAdapter,
    build_p2_runtime,
)
from asterion.applications.prime.p2.worker import P2ContextServiceWorker
from asterion.applications.prime.p7 import live
from asterion.applications.provider import compose_installed_provider
from asterion.capabilities.prime_programmatic_long_context_native.host import (
    P2Finalization,
    P2PendingClassification,
    P2RetrievalCall,
    P2RetrievalReceipt as _HostRetrievalReceipt,
    P2RuntimeHostError,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
from asterion.runtime.host import CancellationSignal
from asterion.runner.composed import run_composed_application


_P2_CORPUS_ENV = "ASTERION_PRIME_P2_CORPUS"
_IPYTHON_VERSION = "9.17.1"


class P2OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P2 operator is unavailable")


@dataclass(frozen=True, slots=True)
class P2PublicResult:
    run_id: str
    status: str
    receipt_sha256: str | None = None


class P2OperatorResources:
    """Concrete host service owner over one preflighted worker."""

    def __init__(
        self,
        *,
        worker: P2ContextServiceWorker,
        worker_owner: P2WorkerOwnerAdapter,
        private_root: Path,
        run_id: str,
        cleanup_root: Callable[[], None] | None = None,
    ) -> None:
        self.worker = worker
        self.worker_owner = worker_owner
        self.private_root = private_root
        self.run_id = run_id
        self.oracle = P2Oracle(
            worker_identity=worker.identity_sha256,
            corpus_sha256=worker.corpus_sha256,
        )
        self._cleanup_root = cleanup_root

    def validate_runtime_services(
        self,
        *,
        ipython: object,
        oracle: object,
        extension: object,
        private_trace: object,
    ) -> None:
        if (
            ipython is not self.worker
            or oracle is not self.oracle
            or extension is not self.worker_owner
        ):
            raise P2OperatorError()
        self.worker_owner.validate_lifecycle()

    async def execute_retrieval(
        self,
        *,
        run_id: str,
        call: P2RetrievalCall,
        signal: CancellationSignal | None,
    ) -> _HostRetrievalReceipt:
        if run_id != self.run_id:
            raise P2RuntimeHostError("recovery-required")
        try:
            if call.operation == "retrieve":
                slice_ = self.worker.retrieve(bounds=call.bounds)
            else:
                raise P2OracleError()
        except P2ContextServiceError:
            raise P2RuntimeHostError("recovery-required") from None
        receipt = self.oracle.verify_retrieval(slice_=slice_)
        return _HostRetrievalReceipt(
            call_id=receipt.call_id,
            operation=receipt.operation,
            result_sha256=receipt.slice_sha256,
            bytes_returned=receipt.bytes_returned,
            input_tokens=0,
            output_tokens=0,
        )

    async def report_execution_stopped(
        self, *, run_id: str, pending_classification: P2PendingClassification
    ) -> None:
        return None

    async def wait_finalization(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P2Finalization:
        if run_id != self.run_id:
            raise P2RuntimeHostError("recovery-required")
        retrieval = self.oracle._retrieval
        if retrieval is None:
            raise P2RuntimeHostError("recovery-required")
        try:
            worker_cleanup = await self.worker_owner.close()
        except Exception:
            raise P2RuntimeHostError("recovery-required") from None
        result = self.oracle.verify_answer(answer_sha256=retrieval.slice_sha256)
        seal_cleanup_receipt(
            self.oracle,
            result,
            worker_cleanup,
            oracle_closed=True,
            worker_closed=True,
            bridge_closed=True,
            private_store_removed=True,
        )
        native = build_native_receipt(self.oracle, result, seal_cleanup_receipt.__wrapped__ if hasattr(seal_cleanup_receipt, '__wrapped__') else None)  # type: ignore[arg-type]
        # `seal_cleanup_receipt` mutates oracle._cleanup via closure;
        # we need to re-fetch the cleanup that was just sealed.
        cleanup = self.oracle._cleanup
        if cleanup is None:
            raise P2RuntimeHostError("recovery-required")
        native = build_native_receipt(self.oracle, result, cleanup)
        return P2Finalization(
            classification="completed", receipt_sha256=native.sha256()
        )

    async def close(self) -> None:
        try:
            await self.worker_owner.close()
        finally:
            if self._cleanup_root is not None:
                self._cleanup_root()


@dataclass(frozen=True, slots=True)
class _Preflight:
    operator_root: Path
    worker_python: Path
    corpus_path: Path


def _preflight(environment: MappingProxyType) -> _Preflight:  # type: ignore[type-arg]
    configured = environment.get(live.OPERATOR_ROOT_ENV, "").strip()
    if not configured:
        raise P2OperatorError()
    try:
        root = Path(configured).resolve(strict=True)
    except OSError:
        raise P2OperatorError() from None
    if not root.is_dir():
        raise P2OperatorError()
    worker = Path(sys.executable).absolute()
    if not worker.is_file():
        raise P2OperatorError()
    try:
        probe = subprocess.run(
            (
                str(worker),
                "-I",
                "-c",
                f"import IPython,sys; assert IPython.__version__ == {_IPYTHON_VERSION!r}",
            ),
            check=True,
            capture_output=True,
            timeout=10,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise P2OperatorError() from None
    if probe.stdout or probe.stderr:
        raise P2OperatorError()
    corpus_value = environment.get(_P2_CORPUS_ENV, "").strip()
    if not corpus_value:
        raise P2OperatorError()
    try:
        corpus = Path(corpus_value).resolve(strict=True)
    except OSError:
        raise P2OperatorError() from None
    if not corpus.is_file():
        raise P2OperatorError()
    return _Preflight(root, worker, corpus)


def _build_resources(preflight: _Preflight) -> P2OperatorResources:
    temporary = tempfile.TemporaryDirectory(prefix="asterion-native-p2-")
    root = Path(temporary.name).resolve()
    try:
        service = P2ContextService(preflight.corpus_path)
        worker = P2ContextServiceWorker(service)
        owner = P2WorkerOwnerAdapter(worker)
        run_id = "p2-" + secrets.token_hex(12)
        return P2OperatorResources(
            worker=worker,
            worker_owner=owner,
            private_root=root,
            run_id=run_id,
            cleanup_root=temporary.cleanup,
        )
    except BaseException:
        temporary.cleanup()
        raise P2OperatorError()


async def _run() -> P2PublicResult:
    environment = MappingProxyType(os.environ.copy())  # type: ignore[arg-type]
    preflight = _preflight(environment)
    resources = _build_resources(preflight)
    try:
        return await _invoke_composed(resources)
    finally:
        await resources.close()


async def _invoke_composed(resources: P2OperatorResources) -> P2PublicResult:
    package = create_prime_programmatic_long_context_native_package()
    provider = compose_installed_provider(
        create_prime_programmatic_long_context_provider(),
        runtime_factories=RuntimeFactoryRegistry(()),  # type: ignore[arg-type]
        installed_packages=(package,),
    )
    assembly = provider.applications[0].assemblies[0]
    host_services: MappingProxyType = MappingProxyType(  # type: ignore[assignment]
        {
            "prime.ipython": resources.worker,
            "prime.p2-oracle": resources.oracle,
            "prime.pi-extension": resources.worker_owner,
            "prime.private-trace": None,
            "prime.session-backend": resources,
        }
    )
    runtime = build_p2_runtime(
        RuntimeFactoryContext(
            "prime-applications",
            "prime.programmatic-long-context",
            "1.0.0",
            "asterion.prime",
            assembly.path,
            P2_RUNTIME_OPTIONS,
            host_services,
        )
    )
    run_result = await run_composed_application(
        assembly.plan,
        implementations=tuple(
            (item.capability_ref, item.implementation)
            for item in package.implementations
        ),
        runtime=runtime,
        run_id=resources.run_id,
        input_text="fixed-small-verification",
        host_services=host_services,
    )
    if not run_result.artifacts:
        return P2PublicResult(resources.run_id, "protocol-failure")
    artifact = run_result.artifacts[0]
    receipt_sha = artifact["value"]["receipt_sha256"]
    return P2PublicResult(
        run_id=resources.run_id,
        status="completed",
        receipt_sha256=receipt_sha,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        result = asyncio.run(_run())
    except BaseException:
        result = P2PublicResult("p2-unavailable", "protocol-failure")
    print(json.dumps(asdict(result), separators=(",", ":")))
    if result.status == "completed" and result.receipt_sha256 is not None:
        return 0
    return 2


__all__ = (
    "P2OperatorError",
    "P2OperatorResources",
    "P2PublicResult",
    "main",
)