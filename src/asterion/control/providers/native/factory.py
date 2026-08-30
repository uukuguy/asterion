"""Exact factory for the private native control-plane provider."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import cast

from asterion.control.authority import AuthorityEnvelope
from asterion.control.factory import (
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryContext,
    ControlPlaneFactoryError,
)
from asterion.control.host import ControlPlaneClient, ControlPlaneManifest
from asterion.control.protocol import CONTROL_COMMAND_TYPES, CONTROL_EVENT_TYPES, OPAQUE_ID
from asterion.control.providers.native.capsule import FileNativeCapsuleStore
from asterion.control.providers.native.client import NativeControlPlaneClient
from asterion.control.providers.native.controller import (
    NativeController,
    NativeControllerError,
)
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeTurnRequest,
    NativeTurnResult,
)
from asterion.control.providers.native.store import (
    FileNativeSessionStore,
    NativeRootIdentity,
    NativeSessionDirectory,
    NativeStoreError,
)
from asterion.control.providers.native.turn import NativeTurnAdapter


NATIVE_CONTROL_PLANE_ID = "asterion.native"
NATIVE_CONTROL_PLANE_VERSION = "0.1.0"
NATIVE_CHECKPOINT_VERSION = "1.0.0"
NATIVE_COMPATIBILITY_IDS = (
    "asterion.agent-control/v1",
    "asterion.native-controller/v1",
)

_NATIVE_PRIVATE_PROVIDER_ID = "native"
_NATIVE_TURN_ADAPTER_SERVICE = "native-turn-adapter"
_REQUIRED_OPTIONS = frozenset(
    {
        "generation",
        "max_capsule_bytes",
        "max_events_per_poll",
        "max_record_bytes",
        "max_total_private_bytes",
        "max_turns_per_poll",
        "session_id",
    }
)
_CAPABILITIES = (
    "action-proposals",
    "checkpointing",
    "event-replay",
    "session-lifecycle",
)
_CONTINUATION_MEDIA_TYPE = "application/vnd.asterion.native-capsule"


@dataclass(frozen=True, slots=True)
class _NativeFactoryContextSnapshot:
    system_id: str
    system_version: str
    private_root: Path


@dataclass(frozen=True, slots=True)
class _NativeFactoryOptions:
    session_id: str
    generation: int
    max_turns_per_poll: int
    max_events_per_poll: int
    max_record_bytes: int
    max_capsule_bytes: int
    max_total_private_bytes: int


@dataclass(frozen=True, slots=True)
class _NativeFactoryAuthority:
    authority_id: str
    revision: int


class _NativeTurnAdapterSnapshot:
    """Stable structural view of one injected native turn adapter."""

    def __init__(
        self,
        *,
        adapter_id: str,
        execute: Callable[[NativeTurnRequest], Awaitable[NativeTurnResult]],
    ) -> None:
        self._adapter_id = adapter_id
        self._execute = execute

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        return await self._execute(request)


def native_control_plane_binding() -> ControlPlaneFactoryBinding:
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
        factory=build_native_control_plane_client,
    )


def build_native_control_plane_client(
    context: ControlPlaneFactoryContext,
) -> ControlPlaneClient:
    owner: NativeSessionDirectory | None = None
    session_store: FileNativeSessionStore | None = None
    capsule_store: FileNativeCapsuleStore | None = None
    controller: NativeController | None = None
    try:
        identity = _validate_context_identity(context)
        options = _validate_options(context.options)
        authority = _validate_authority(context.authority)
        adapter = _snapshot_turn_adapter(context.host_services)
        manifest = native_control_plane_binding().manifest
        root_identity = _validate_private_root(identity.private_root)

        owner = NativeSessionDirectory.open(
            identity.private_root,
            options.session_id,
            options.max_total_private_bytes,
            expected_root_identity=root_identity,
        )
        session_store = FileNativeSessionStore(
            owner,
            max_record_bytes=options.max_record_bytes,
        )
        capsule_store = FileNativeCapsuleStore(
            owner,
            max_capsule_bytes=options.max_capsule_bytes,
        )
        controller = NativeController(
            owner=owner,
            session_store=session_store,
            capsule_store=capsule_store,
            turn_adapter=adapter,
            provider_id=_NATIVE_PRIVATE_PROVIDER_ID,
            provider_version=NATIVE_CONTROL_PLANE_VERSION,
            system_id=identity.system_id,
            system_version=identity.system_version,
            session_id=options.session_id,
            generation=options.generation,
            checkpoint_version=NATIVE_CHECKPOINT_VERSION,
            authority_id=authority.authority_id,
            authority_revision=authority.revision,
            event_id_factory=_opaque_id_factory("event"),
            turn_id_factory=_opaque_id_factory("turn"),
            capsule_id_factory=_opaque_id_factory("capsule"),
            clock=_utc_clock,
        )
        owner = None
        session_store = None
        capsule_store = None
        client = NativeControlPlaneClient(
            manifest=manifest,
            controller=controller,
            max_turns_per_poll=options.max_turns_per_poll,
            max_events_per_poll=options.max_events_per_poll,
        )
        controller = None
        return client
    except ControlPlaneFactoryError:
        _close_partial(controller, capsule_store, session_store, owner)
        raise
    except (NativeControllerError, NativeStoreError, OSError, RuntimeError, TypeError, ValueError):
        _close_partial(controller, capsule_store, session_store, owner)
        raise ControlPlaneFactoryError("Native control plane is unavailable") from None


def _packaged_manifest() -> ControlPlaneManifest:
    try:
        body = (
            resources.files("asterion.control.providers.native")
            .joinpath("resources/control-plane.json")
            .read_text(encoding="utf-8")
        )
        manifest = ControlPlaneManifest.from_mapping(json.loads(body))
    except Exception:
        raise ControlPlaneFactoryError(
            "Native control plane manifest is unavailable"
        ) from None
    if (
        manifest.control_plane_id != NATIVE_CONTROL_PLANE_ID
        or manifest.version != NATIVE_CONTROL_PLANE_VERSION
        or manifest.commands != tuple(sorted(CONTROL_COMMAND_TYPES))
        or manifest.events != tuple(sorted(CONTROL_EVENT_TYPES))
        or manifest.capabilities != _CAPABILITIES
        or manifest.continuation_media_type != _CONTINUATION_MEDIA_TYPE
        or manifest.checkpoint_version != NATIVE_CHECKPOINT_VERSION
        or manifest.compatibility_ids != NATIVE_COMPATIBILITY_IDS
    ):
        raise ControlPlaneFactoryError(
            "Native control plane manifest is unavailable"
        )
    return manifest


def _validate_context_identity(context: object) -> _NativeFactoryContextSnapshot:
    if (
        type(context) is not ControlPlaneFactoryContext
        or context.control_plane_id != NATIVE_CONTROL_PLANE_ID
        or context.control_plane_version != NATIVE_CONTROL_PLANE_VERSION
    ):
        raise ControlPlaneFactoryError("Native control plane identity is invalid")
    return _NativeFactoryContextSnapshot(
        system_id=context.system_id,
        system_version=context.system_version,
        private_root=context.private_root,
    )


def _validate_options(options: Mapping[str, str]) -> _NativeFactoryOptions:
    try:
        snapshot = dict(options)
    except Exception:
        raise ControlPlaneFactoryError(
            "Native control plane options are invalid"
        ) from None
    if frozenset(snapshot) != _REQUIRED_OPTIONS:
        raise ControlPlaneFactoryError("Native control plane options are invalid")
    session_id = snapshot["session_id"]
    if not isinstance(session_id, str) or OPAQUE_ID.fullmatch(session_id) is None:
        raise ControlPlaneFactoryError("Native control plane options are invalid")
    for key in _REQUIRED_OPTIONS - {"session_id"}:
        _positive_integer(snapshot, key)
    return _NativeFactoryOptions(
        session_id=session_id,
        generation=_positive_integer(snapshot, "generation"),
        max_turns_per_poll=_positive_integer(snapshot, "max_turns_per_poll"),
        max_events_per_poll=_positive_integer(snapshot, "max_events_per_poll"),
        max_record_bytes=_positive_integer(snapshot, "max_record_bytes"),
        max_capsule_bytes=_positive_integer(snapshot, "max_capsule_bytes"),
        max_total_private_bytes=_positive_integer(
            snapshot,
            "max_total_private_bytes",
        ),
    )


def _positive_integer(options: Mapping[str, str], key: str) -> int:
    try:
        raw = options[key]
    except KeyError:
        raise ControlPlaneFactoryError(
            "Native control plane options are invalid"
        ) from None
    if (
        not isinstance(raw, str)
        or not raw.isascii()
        or not raw.isdecimal()
        or raw.startswith("0")
    ):
        raise ControlPlaneFactoryError("Native control plane options are invalid")
    value = int(raw)
    if value < 1 or value > MAX_SAFE_JSON_INTEGER:
        raise ControlPlaneFactoryError("Native control plane options are invalid")
    return value


def _validate_authority(authority: object) -> _NativeFactoryAuthority:
    if (
        type(authority) is not AuthorityEnvelope
        or authority.cancelled
        or _NATIVE_TURN_ADAPTER_SERVICE not in authority.host_service_grants
    ):
        raise ControlPlaneFactoryError("Native authority snapshot is unavailable")
    return _NativeFactoryAuthority(
        authority_id=authority.authority_id,
        revision=authority.revision,
    )


def _validate_private_root(private_root: Path) -> NativeRootIdentity:
    try:
        result = private_root.stat(follow_symlinks=False)
    except OSError:
        raise ControlPlaneFactoryError("Native private root is unavailable") from None
    if (
        result.st_uid != os.geteuid()
        or stat.S_IMODE(result.st_mode) != 0o700
        or not stat.S_ISDIR(result.st_mode)
    ):
        raise ControlPlaneFactoryError("Native private root is unavailable")
    return NativeRootIdentity(result.st_dev, result.st_ino)


def _snapshot_turn_adapter(
    host_services: Mapping[str, object],
) -> NativeTurnAdapter:
    try:
        adapter = host_services.get(_NATIVE_TURN_ADAPTER_SERVICE)
        adapter_id = object.__getattribute__(adapter, "adapter_id")
        execute = object.__getattribute__(adapter, "execute")
    except Exception:
        raise ControlPlaneFactoryError(
            "Native turn adapter is unavailable"
        ) from None
    if not isinstance(adapter_id, str) or not adapter_id or not callable(execute):
        raise ControlPlaneFactoryError("Native turn adapter is unavailable")
    return cast(
        NativeTurnAdapter,
        _NativeTurnAdapterSnapshot(
            adapter_id=adapter_id,
            execute=cast(
                Callable[[NativeTurnRequest], Awaitable[NativeTurnResult]],
                execute,
            ),
        ),
    )


def _opaque_id_factory(prefix: str) -> Callable[[], str]:
    def factory() -> str:
        return f"{prefix}-{secrets.token_hex(16)}"

    return factory


def _utc_clock() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _close_partial(
    controller: NativeController | None,
    capsule_store: FileNativeCapsuleStore | None,
    session_store: FileNativeSessionStore | None,
    owner: NativeSessionDirectory | None,
) -> None:
    if controller is not None:
        try:
            controller.close()
        except Exception:
            pass
        return
    if capsule_store is not None:
        try:
            capsule_store.close()
        except Exception:
            pass
    if session_store is not None:
        try:
            session_store.close()
        except Exception:
            pass
    if owner is not None:
        try:
            owner.close()
        except Exception:
            pass


__all__ = (
    "NATIVE_CONTROL_PLANE_ID",
    "NATIVE_CONTROL_PLANE_VERSION",
    "build_native_control_plane_client",
    "native_control_plane_binding",
)
