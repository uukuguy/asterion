"""Exact factory for the private Prime control-plane provider."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Mapping
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
from asterion.control.private_store import (
    PrivateAttachmentResolver,
    PrivateContentResolver,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
    PrimeSidecarProcessError,
)


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
    "session-lifecycle",
    "session.context-v1",
)
_CONTINUATION_MEDIA_TYPE = "application/vnd.asterion.control-capsule"
_ECOSYSTEM_SOURCE_STORE_SERVICE = "ecosystem-source-store"
_ECOSYSTEM_MATERIALIZER_SERVICE = "ecosystem-materializer"
_MCP_CREDENTIAL_REFRESH_SERVICE = "mcp-credential-refresh"
_PRIVATE_CONTENT_SERVICE = "private-content"
_PRIVATE_ATTACHMENT_SERVICE = "private-attachments"
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


class _DeferredPrimeSidecarTransport:
    """Permit all selected-service binding to finish before process creation."""

    def __init__(self) -> None:
        self._process: PrimeSidecarTransport | None = None

    def bind(self, process: object) -> None:
        self._process = cast(PrimeSidecarTransport, process)

    async def request(
        self, envelope: Mapping[str, object]
    ) -> Mapping[str, object]:
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


class _EcosystemMaterializerSnapshot:
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
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
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
        manifest = prime_control_plane_binding().manifest
        ecosystem_services = None
        if "ecosystem.portfolio" in manifest.capabilities:
            ecosystem_services = _require_ecosystem_services(context.host_services)
        resolver = context.host_services.get(_PRIVATE_CONTENT_SERVICE)
        if not _is_private_content_resolver(resolver):
            raise ControlPlaneFactoryError("Prime private content service is unavailable")
        attachment_resolver = context.host_services.get(_PRIVATE_ATTACHMENT_SERVICE)
        if not _is_private_attachment_resolver(attachment_resolver):
            raise ControlPlaneFactoryError(
                "Prime private attachment service is unavailable"
            )
        launch_options = PrimeSidecarLaunchOptions(
            node_executable=_path_option(context.options, "node_executable"),
            sidecar_entry=_path_option(context.options, "sidecar_entry"),
            private_descriptor=_private_descriptor(context),
            environ=os.environ,
        )
        authority = context.authority
        if authority is None:
            raise ControlPlaneFactoryError("Prime authority snapshot is unavailable")
        transport = _DeferredPrimeSidecarTransport()
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
        transport.bind(process)
        return client
    except ControlPlaneFactoryError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, PrimeSidecarProcessError):
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


def _require_ecosystem_services(
    services: Mapping[str, object],
) -> tuple[
    EcosystemPrivateSourceStore,
    SealedEcosystemMaterializer,
    McpCredentialRefresh,
]:
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
        raise ControlPlaneFactoryError(
            "Prime ecosystem host service is unavailable"
        )
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
        raise ControlPlaneFactoryError("Prime control plane options are invalid") from None
    if value < 1:
        raise ControlPlaneFactoryError("Prime control plane options are invalid")
    return value


def _private_descriptor(context: ControlPlaneFactoryContext) -> Mapping[str, object]:
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
