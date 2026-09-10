"""Exact factory for the selected native Asterion Prime control provider."""

from __future__ import annotations

import json
from importlib import resources

from asterion.agents.prime.backend import PrimeSessionBackend
from asterion.agents.prime.state import PrimeBackendIdentity, PrimeBackendSnapshot
from asterion.agents.prime.store import private_root_identity
from asterion.control.authority import AuthorityEnvelope
from asterion.control.factory import (
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryContext,
    ControlPlaneFactoryError,
)
from asterion.control.host import ControlPlaneManifest
from asterion.control.protocol import (
    CONTROL_COMMAND_TYPES,
    CONTROL_EVENT_TYPES,
    OPAQUE_ID,
)
from asterion.control.providers.asterion_prime.client import (
    AsterionPrimeControlPlaneClient,
)
from asterion.control.session_context import SESSION_CONTEXT_CAPABILITY


ASTERION_PRIME_CONTROL_PLANE_ID = "asterion.prime-control"
ASTERION_PRIME_CONTROL_PLANE_VERSION = "1.0.0"
ASTERION_PRIME_SESSION_BACKEND_SERVICE = "prime.session-backend"

_CHECKPOINT_VERSION = "1.0.0"
_CAPABILITIES = (
    "checkpointing",
    "event-replay",
    "session-lifecycle",
    SESSION_CONTEXT_CAPABILITY,
)
_COMPATIBILITY_IDS = (
    "asterion.agent-control/v1",
    "asterion.session-context/v1",
)
_CONTINUATION_MEDIA_TYPE = "application/vnd.asterion.prime-continuation"
_REQUIRED_OPTIONS = frozenset({"generation", "session_id"})
_ERROR_MESSAGE = "Asterion Prime control plane is unavailable"


def asterion_prime_control_plane_binding() -> ControlPlaneFactoryBinding:
    manifest = _packaged_manifest()
    return ControlPlaneFactoryBinding(
        control_plane_id=manifest.control_plane_id,
        version=manifest.version,
        commands=manifest.commands,
        events=manifest.events,
        capabilities=manifest.capabilities,
        continuation_media_type=manifest.continuation_media_type,
        checkpoint_version=manifest.checkpoint_version,
        compatibility_ids=manifest.compatibility_ids,
        factory=build_asterion_prime_control_plane_client,
    )


def build_asterion_prime_control_plane_client(
    context: ControlPlaneFactoryContext,
) -> AsterionPrimeControlPlaneClient:
    try:
        manifest = _packaged_manifest()
        if (
            type(context) is not ControlPlaneFactoryContext
            or context.control_plane_id != ASTERION_PRIME_CONTROL_PLANE_ID
            or context.control_plane_version != ASTERION_PRIME_CONTROL_PLANE_VERSION
            or frozenset(context.options) != _REQUIRED_OPTIONS
        ):
            raise ValueError
        session_id = context.options["session_id"]
        generation_text = context.options["generation"]
        if (
            OPAQUE_ID.fullmatch(session_id) is None
            or not generation_text.isascii()
            or not generation_text.isdecimal()
            or generation_text.startswith("0")
        ):
            raise ValueError
        generation = int(generation_text)
        authority = context.authority
        backend = context.host_services.get(ASTERION_PRIME_SESSION_BACKEND_SERVICE)
        if (
            type(authority) is not AuthorityEnvelope
            or authority.cancelled
            or ASTERION_PRIME_SESSION_BACKEND_SERVICE
            not in authority.host_service_grants
            or type(backend) is not PrimeSessionBackend
        ):
            raise ValueError
        identity = backend.identity
        snapshot = backend.snapshot()
        if (
            type(identity) is not PrimeBackendIdentity
            or type(snapshot) is not PrimeBackendSnapshot
            or snapshot.identity != identity
            or snapshot.authority_revision != authority.revision
            or session_id != identity.session_id
            or generation != identity.generation
            or context.system_id != identity.application_id
            or context.system_version != identity.application_version
            or private_root_identity(context.private_root)
            != identity.private_root_identity
            or getattr(backend, "_authority_id", None) != authority.authority_id
            or not any(
                grant.provider_id == identity.provider_id
                and grant.application_id == identity.application_id
                and grant.version == identity.application_version
                and grant.runtime_id == identity.runtime_id
                for grant in authority.allowed_portfolio
            )
        ):
            raise ValueError
        attachment = backend.attach(identity)
        return AsterionPrimeControlPlaneClient(
            manifest=manifest,
            attachment=attachment,
            identity=identity,
            authority_revision=authority.revision,
        )
    except Exception:
        pass
    raise ControlPlaneFactoryError(_ERROR_MESSAGE) from None


def _packaged_manifest() -> ControlPlaneManifest:
    manifest: ControlPlaneManifest | None = None
    try:
        body = (
            resources.files("asterion.control.providers.asterion_prime")
            .joinpath("resources/control-plane.json")
            .read_text(encoding="utf-8")
        )
        manifest = ControlPlaneManifest.from_mapping(json.loads(body))
    except Exception:
        pass
    if manifest is None or (
        manifest.control_plane_id != ASTERION_PRIME_CONTROL_PLANE_ID
        or manifest.version != ASTERION_PRIME_CONTROL_PLANE_VERSION
        or manifest.commands != tuple(sorted(CONTROL_COMMAND_TYPES))
        or manifest.events != tuple(sorted(CONTROL_EVENT_TYPES))
        or manifest.capabilities != _CAPABILITIES
        or manifest.continuation_media_type != _CONTINUATION_MEDIA_TYPE
        or manifest.checkpoint_version != _CHECKPOINT_VERSION
        or manifest.compatibility_ids != _COMPATIBILITY_IDS
    ):
        raise ControlPlaneFactoryError(_ERROR_MESSAGE)
    return manifest


__all__ = (
    "ASTERION_PRIME_CONTROL_PLANE_ID",
    "ASTERION_PRIME_CONTROL_PLANE_VERSION",
    "ASTERION_PRIME_SESSION_BACKEND_SERVICE",
    "asterion_prime_control_plane_binding",
    "build_asterion_prime_control_plane_client",
)
