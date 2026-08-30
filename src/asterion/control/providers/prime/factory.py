"""Exact factory for the private Prime control-plane provider."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from types import MappingProxyType
from typing import IO, TypeGuard, cast

from asterion.control.authority import AuthorityEnvelope
from asterion.control.ecosystem import (
    EcosystemPortfolio,
    EcosystemPrivateResource,
    EcosystemPrivateSourceStore,
)
from asterion.control.ecosystem_materialization import (
    EcosystemProjection,
    SealedEcosystemMaterializer,
)
from asterion.control.factory import (
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryContext,
    ControlPlaneFactoryError,
)
from asterion.control.host import ControlPlaneClient, ControlPlaneManifest
from asterion.control.protocol import OPAQUE_ID
from asterion.control.providers.prime.client import (
    PrimeControlPlaneClient,
    PrimeSidecarTransport,
)
from asterion.control.providers.prime.ecosystem import (
    McpCredentialRefresh,
    PrimeEcosystemService,
)
from asterion.control.providers.prime.operation import (
    PrimeOperationClient,
    PrimeOperationError,
)
from asterion.control.providers.prime.operation_host import (
    PrimeManagedOperationTransport,
    PrimeOperationHostError,
    PrimeOperationHostServer,
)
from asterion.control.private_store import (
    PrivateAttachmentResolver,
    PrivateContentResolver,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
    PrimeSidecarProcessError,
)
from asterion.operation.protocol import OperationReceipt, OperationTransaction


PRIME_CONTROL_PLANE_ID = "prime.gateway"
PRIME_CONTROL_PLANE_VERSION = "0.1.0"
PRIME_CHECKPOINT_VERSION = "1.0.0"
# Prime native RLM remains disabled; child admission is host-owned.
PRIME_NATIVE_RLM_MAX_DEPTH = 0
PRIME_COMPATIBILITY_IDS = (
    "asterion.agent-control/v1",
    "asterion.session-context/v1",
    "prime-agent.daemon/v7",
    "prime-agent.schema/v14",
)

_COMMANDS = (
    "action.resolve",
    "checkpoint.request",
    "input.submit",
    "session.attach",
    "session.cancel",
    "session.create",
    "session.detach",
    "session.pause",
    "session.resume",
)
_EVENTS = (
    "action.proposed",
    "budget.reported",
    "checkpoint.created",
    "fault.raised",
    "goal.updated",
    "session.budget-limited",
    "session.cancelled",
    "session.completed",
    "session.created",
    "session.failed",
    "session.paused",
    "session.recovery-required",
    "session.running",
)
_CAPABILITIES = (
    "action-proposals",
    "checkpointing",
    "client-observations-v1",
    "ecosystem.portfolio",
    "event-replay",
    "operations-v1",
    "session-lifecycle",
    "session.context-v1",
)
_CONTINUATION_MEDIA_TYPE = "application/vnd.asterion.control-capsule"
_ECOSYSTEM_SOURCE_STORE_SERVICE = "ecosystem-source-store"
_ECOSYSTEM_MATERIALIZER_SERVICE = "ecosystem-materializer"
_MCP_CREDENTIAL_REFRESH_SERVICE = "mcp-credential-refresh"
_PRIVATE_CONTENT_SERVICE = "private-content"
_PRIVATE_ATTACHMENT_SERVICE = "private-attachments"
_OPERATION_DISPATCHER_SERVICE = "operation-dispatcher"
_REQUIRED_OPTIONS = frozenset(
    {
        "agent_dir",
        "artifact_lock_path",
        "authority_id",
        "expected_runtime_build_id",
        "gateway_root",
        "generation",
        "max_continuations",
        "max_controller_tokens",
        "max_turns",
        "model",
        "node_executable",
        "prime_socket_path",
        "prime_source_root",
        "provider",
        "session_dir",
        "session_id",
        "sidecar_entry",
        "timeout_ms",
        "workspace",
    }
)

ProcessFactory = Callable[[PrimeSidecarLaunchOptions], object]


class _OperationDispatcherSnapshot:
    """Stable, identity-bound view of one operator-owned dispatcher."""

    def __init__(
        self,
        *,
        session_id: str,
        generation: int,
        authority_id: str,
        authority_revision: int,
        execute: Callable[[OperationTransaction], Awaitable[OperationReceipt]],
        cancel: Callable[..., Awaitable[OperationReceipt]],
        reconcile: Callable[[OperationTransaction], Awaitable[OperationReceipt]],
    ) -> None:
        self._session_id = session_id
        self._generation = generation
        self._authority_id = authority_id
        self._authority_revision = authority_revision
        self._execute = execute
        self._cancel = cancel
        self._reconcile = reconcile

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def authority_id(self) -> str:
        return self._authority_id

    @property
    def authority_revision(self) -> int:
        return self._authority_revision

    async def execute(self, transaction: OperationTransaction) -> OperationReceipt:
        return await self._execute(transaction)

    async def cancel(
        self, operation_id: str, *, authority_revision: int
    ) -> OperationReceipt:
        return await self._cancel(operation_id, authority_revision=authority_revision)

    async def reconcile(self, transaction: OperationTransaction) -> OperationReceipt:
        return await self._reconcile(transaction)


class _DeferredPrimeSidecarTransport:
    """Permit all selected-service binding to finish before process creation."""

    def __init__(self) -> None:
        self._process: PrimeSidecarTransport | None = None

    def bind(self, process: object) -> None:
        try:
            request = object.__getattribute__(process, "request")
            events = object.__getattribute__(process, "events")
            close = object.__getattribute__(process, "close")
        except Exception:
            raise PrimeSidecarProcessError() from None
        if not all(callable(value) for value in (request, events, close)):
            raise PrimeSidecarProcessError()
        self._process = cast(PrimeSidecarTransport, process)

    @property
    def pid(self) -> int | None:
        process = self._process
        if process is None:
            return None
        try:
            value = object.__getattribute__(process, "pid")
        except AttributeError:
            return None
        except Exception:
            return None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        return await self._bound().request(envelope)

    def events(
        self, envelope: Mapping[str, object]
    ) -> AsyncIterator[Mapping[str, object]]:
        return self._bound().events(envelope)

    async def close(self) -> None:
        await self._bound().close()

    def _bound(self) -> PrimeSidecarTransport:
        if self._process is None:
            raise RuntimeError
        return self._process


class _EcosystemSourceStoreSnapshot:
    def __init__(
        self,
        private_resource: Callable[[str], EcosystemPrivateResource],
        open_file: Callable[[str, str], AbstractContextManager[IO[bytes]]],
    ) -> None:
        self._private_resource = private_resource
        self._open_file = open_file

    def private_resource(self, resource_id: str) -> EcosystemPrivateResource:
        return self._private_resource(resource_id)

    def open_file(
        self, resource_id: str, relative_path: str
    ) -> AbstractContextManager[IO[bytes]]:
        return self._open_file(resource_id, relative_path)


class _EcosystemMaterializerSnapshot(SealedEcosystemMaterializer):
    def __init__(
        self,
        materialize: Callable[
            [EcosystemPortfolio, EcosystemPrivateSourceStore],
            EcosystemProjection,
        ],
        close: Callable[[EcosystemProjection], None],
    ) -> None:
        self._materialize = materialize
        self._close = close

    def materialize(
        self,
        portfolio: EcosystemPortfolio,
        store: EcosystemPrivateSourceStore,
    ) -> EcosystemProjection:
        return self._materialize(portfolio, store)

    def close(self, projection: EcosystemProjection) -> None:
        self._close(projection)


class _McpCredentialRefreshSnapshot:
    def __init__(self, refresh: Callable[[str, str], str]) -> None:
        self._refresh = refresh

    def refresh(self, lease_id: str, challenge_digest: str) -> str:
        return self._refresh(lease_id, challenge_digest)


def derive_prime_child_control_options(
    parent_options: Mapping[str, str],
    *,
    child_root: Path,
    child_session_id: str,
    child_authority: AuthorityEnvelope,
    generation: int,
) -> Mapping[str, str]:
    """Return the Prime options for one host-admitted child session."""

    if (
        not isinstance(child_root, Path)
        or not isinstance(child_session_id, str)
        or OPAQUE_ID.fullmatch(child_session_id) is None
        or not isinstance(child_authority, AuthorityEnvelope)
    ):
        raise ValueError("Prime child control options are invalid")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise ValueError("Prime child control options are invalid")
    try:
        parent_controller_tokens = _positive_integer_option(
            parent_options, "max_controller_tokens"
        )
        parent_timeout_ms = _positive_integer_option(parent_options, "timeout_ms")
        controller_tokens = min(
            parent_controller_tokens, child_authority.budget_limit.controller_tokens
        )
        timeout_ms = min(parent_timeout_ms, child_authority.max_action_deadline_ms)
        if controller_tokens < 1 or timeout_ms < 1:
            raise ValueError
        options = dict(parent_options)
    except Exception:
        raise ValueError("Prime child control options are invalid")
    options.update(
        {
            "agent_dir": str(child_root / "agent"),
            "authority_id": child_authority.authority_id,
            "gateway_root": str(child_root / "gateway"),
            "generation": str(generation),
            "max_controller_tokens": str(controller_tokens),
            "session_dir": str(child_root / "session"),
            "session_id": child_session_id,
            "timeout_ms": str(timeout_ms),
        }
    )
    return MappingProxyType(options)


def prime_control_plane_binding() -> ControlPlaneFactoryBinding:
    return ControlPlaneFactoryBinding(
        control_plane_id=PRIME_CONTROL_PLANE_ID,
        version=PRIME_CONTROL_PLANE_VERSION,
        commands=_COMMANDS,
        events=_EVENTS,
        capabilities=_CAPABILITIES,
        continuation_media_type=_CONTINUATION_MEDIA_TYPE,
        checkpoint_version=PRIME_CHECKPOINT_VERSION,
        compatibility_ids=PRIME_COMPATIBILITY_IDS,
        factory=build_prime_control_plane_client,
    )


def build_prime_control_plane_client(
    context: ControlPlaneFactoryContext,
    *,
    process_factory: ProcessFactory = PrimeSidecarProcess,
) -> ControlPlaneClient:
    try:
        _validate_context_identity(context)
        if context.options.get("execution_domain") != "trusted-local":
            raise ControlPlaneFactoryError("Prime control plane requires trusted-local")
        missing = _REQUIRED_OPTIONS.difference(context.options)
        if missing:
            raise ControlPlaneFactoryError("Prime control plane options are invalid")
        authority = context.authority
        if authority is None:
            raise ControlPlaneFactoryError("Prime authority snapshot is unavailable")
        dispatcher = _snapshot_operation_dispatcher(context, authority)
        manifest = prime_control_plane_binding().manifest
        ecosystem_services = None
        if "ecosystem.portfolio" in manifest.capabilities:
            ecosystem_services = _require_ecosystem_services(context.host_services)
        resolver = context.host_services.get(_PRIVATE_CONTENT_SERVICE)
        if not _is_private_content_resolver(resolver):
            raise ControlPlaneFactoryError(
                "Prime private content service is unavailable"
            )
        attachment_resolver = context.host_services.get(_PRIVATE_ATTACHMENT_SERVICE)
        if not _is_private_attachment_resolver(attachment_resolver):
            raise ControlPlaneFactoryError(
                "Prime private attachment service is unavailable"
            )
        node_executable = _path_option(context.options, "node_executable")
        sidecar_entry = _path_option(context.options, "sidecar_entry")
        operation_host = PrimeOperationHostServer(
            dispatcher=dispatcher,
            private_root=context.private_root,
            token=secrets.token_hex(32),
            request_timeout=_positive_integer_option(context.options, "timeout_ms")
            / 1000,
        )
        launch_options = PrimeSidecarLaunchOptions(
            node_executable=node_executable,
            sidecar_entry=sidecar_entry,
            private_descriptor=_private_descriptor(
                context, operation_host=operation_host.descriptor
            ),
            environ=os.environ,
        )
        deferred = _DeferredPrimeSidecarTransport()
        transport = PrimeManagedOperationTransport(
            process=deferred,
            callback=operation_host,
        )
        client = PrimeControlPlaneClient(
            process=transport,
            private_content=resolver,
            private_attachments=attachment_resolver,
            manifest=manifest,
        )
        if ecosystem_services is not None:
            source_store, materializer, credential_refresh = ecosystem_services
            service = PrimeEcosystemService(
                client,
                materializer,
                source_store,
                authority_id=authority.authority_id,
                authority_revision=authority.revision,
            )
            client.bind_ecosystem_service(service, credential_refresh)
        process = process_factory(launch_options)
        deferred.bind(process)
        operation_client = PrimeOperationClient(transport)
        client.bind_operation_client(operation_client)
        return client
    except ControlPlaneFactoryError:
        raise
    except (
        OSError,
        PrimeOperationHostError,
        PrimeOperationError,
        RuntimeError,
        TypeError,
        ValueError,
        PrimeSidecarProcessError,
    ):
        raise ControlPlaneFactoryError("Prime control plane is unavailable") from None


def prime_control_plane_manifest() -> ControlPlaneManifest:
    return prime_control_plane_binding().manifest


def _validate_context_identity(context: ControlPlaneFactoryContext) -> None:
    if (
        not isinstance(context, ControlPlaneFactoryContext)
        or context.control_plane_id != PRIME_CONTROL_PLANE_ID
        or context.control_plane_version != PRIME_CONTROL_PLANE_VERSION
    ):
        raise ControlPlaneFactoryError("Prime control plane identity is invalid")


def _is_private_content_resolver(value: object) -> TypeGuard[PrivateContentResolver]:
    return callable(getattr(value, "resolve_text", None))


def _is_private_attachment_resolver(
    value: object,
) -> TypeGuard[PrivateAttachmentResolver]:
    return callable(getattr(value, "resolve_bytes", None))


def _snapshot_operation_dispatcher(
    context: ControlPlaneFactoryContext,
    authority: AuthorityEnvelope,
) -> _OperationDispatcherSnapshot:
    try:
        expected_session_id = context.options["session_id"]
        expected_generation = _positive_integer_option(context.options, "generation")
        expected_authority_id = context.options["authority_id"]
        expected_authority_revision = authority.revision
        dispatcher = context.host_services.get(_OPERATION_DISPATCHER_SERVICE)
        session_id = object.__getattribute__(dispatcher, "session_id")
        generation = object.__getattribute__(dispatcher, "generation")
        authority_id = object.__getattribute__(dispatcher, "authority_id")
        authority_revision = object.__getattribute__(dispatcher, "authority_revision")
        execute = object.__getattribute__(dispatcher, "execute")
        cancel = object.__getattribute__(dispatcher, "cancel")
        reconcile = object.__getattribute__(dispatcher, "reconcile")
        if (
            not isinstance(session_id, str)
            or OPAQUE_ID.fullmatch(session_id) is None
            or type(generation) is not int
            or generation < 1
            or not isinstance(authority_id, str)
            or OPAQUE_ID.fullmatch(authority_id) is None
            or type(authority_revision) is not int
            or authority_revision < 1
            or not all(callable(value) for value in (execute, cancel, reconcile))
            or session_id != expected_session_id
            or generation != expected_generation
            or authority_id != expected_authority_id
            or authority_revision != expected_authority_revision
        ):
            raise ValueError
        return _OperationDispatcherSnapshot(
            session_id=session_id,
            generation=generation,
            authority_id=authority_id,
            authority_revision=authority_revision,
            execute=cast(
                Callable[[OperationTransaction], Awaitable[OperationReceipt]],
                execute,
            ),
            cancel=cast(Callable[..., Awaitable[OperationReceipt]], cancel),
            reconcile=cast(
                Callable[[OperationTransaction], Awaitable[OperationReceipt]],
                reconcile,
            ),
        )
    except Exception:
        raise ControlPlaneFactoryError(
            "Prime operation dispatcher is unavailable"
        ) from None


def _require_ecosystem_services(
    services: Mapping[str, object],
) -> tuple[
    EcosystemPrivateSourceStore,
    SealedEcosystemMaterializer,
    McpCredentialRefresh,
]:
    private_resource: object = None
    open_file: object = None
    materialize: object = None
    close: object = None
    refresh: object = None
    try:
        source_store = services.get(_ECOSYSTEM_SOURCE_STORE_SERVICE)
        materializer = services.get(_ECOSYSTEM_MATERIALIZER_SERVICE)
        credential_refresh = services.get(_MCP_CREDENTIAL_REFRESH_SERVICE)
        private_resource = getattr(source_store, "private_resource", None)
        open_file = getattr(source_store, "open_file", None)
        materialize = getattr(materializer, "materialize", None)
        close = getattr(materializer, "close", None)
        refresh = getattr(credential_refresh, "refresh", None)
        valid = (
            callable(private_resource)
            and callable(open_file)
            and callable(materialize)
            and callable(close)
            and callable(refresh)
        )
    except Exception:
        valid = False
    if not valid:
        raise ControlPlaneFactoryError("Prime ecosystem host service is unavailable")
    return (
        _EcosystemSourceStoreSnapshot(
            cast(Callable[[str], EcosystemPrivateResource], private_resource),
            cast(
                Callable[[str, str], AbstractContextManager[IO[bytes]]],
                open_file,
            ),
        ),
        _EcosystemMaterializerSnapshot(
            cast(
                Callable[
                    [EcosystemPortfolio, EcosystemPrivateSourceStore],
                    EcosystemProjection,
                ],
                materialize,
            ),
            cast(Callable[[EcosystemProjection], None], close),
        ),
        _McpCredentialRefreshSnapshot(cast(Callable[[str, str], str], refresh)),
    )


def _path_option(options: Mapping[str, str], key: str) -> Path:
    return Path(options[key])


def _positive_integer_option(options: Mapping[str, str], key: str) -> int:
    try:
        value = int(options[key])
    except (KeyError, ValueError):
        raise ControlPlaneFactoryError(
            "Prime control plane options are invalid"
        ) from None
    if value < 1:
        raise ControlPlaneFactoryError("Prime control plane options are invalid")
    return value


def _private_descriptor(
    context: ControlPlaneFactoryContext,
    *,
    operation_host: Mapping[str, str],
) -> Mapping[str, object]:
    options = context.options
    authority = context.authority
    if authority is None or authority.authority_id != options["authority_id"]:
        raise ControlPlaneFactoryError("Prime authority snapshot is unavailable")
    resource_root = Path(__file__).resolve().parent / "resources"
    budget = authority.budget_limit
    return {
        "agentDir": str(_path_option(options, "agent_dir").resolve()),
        "artifactLockPath": str(_path_option(options, "artifact_lock_path").resolve()),
        "authorityId": options["authority_id"],
        "authorityRevision": authority.revision,
        "expectedRuntimeBuildId": options["expected_runtime_build_id"],
        "gatewayRoot": str(_path_option(options, "gateway_root").resolve()),
        "generation": _positive_integer_option(options, "generation"),
        "maxContinuations": _positive_integer_option(options, "max_continuations"),
        "maxControllerTokens": _positive_integer_option(
            options, "max_controller_tokens"
        ),
        "maxTurns": _positive_integer_option(options, "max_turns"),
        "model": options["model"],
        "operationHost": dict(operation_host),
        "portfolio": [
            {
                "kind": "application",
                "provider_id": grant.provider_id,
                "application_id": grant.application_id,
                "version": grant.version,
                "runtime_id": grant.runtime_id,
            }
            for grant in authority.allowed_portfolio
        ],
        "primeSocketPath": str(_path_option(options, "prime_socket_path").resolve()),
        "primeSourceRoot": str(_path_option(options, "prime_source_root").resolve()),
        "provider": options["provider"],
        "probeReady": False,
        "rlmMaxChildren": 0,
        "rlmMaxDepth": 0,
        "remainingBudget": {
            "controller_tokens": budget.controller_tokens,
            "application_tokens": budget.application_tokens,
            "child_tokens": budget.child_tokens,
            "aggregate_tokens": budget.aggregate_tokens,
            "cost_micros": budget.cost_micros,
            "deadline_ms": authority.max_action_deadline_ms,
        },
        "sessionDir": str(_path_option(options, "session_dir").resolve()),
        "sessionId": options["session_id"],
        "skillPath": str((resource_root / "skills" / "asterion-control").resolve()),
        "timeoutMs": _positive_integer_option(options, "timeout_ms"),
        "workspace": str(_path_option(options, "workspace").resolve()),
    }
