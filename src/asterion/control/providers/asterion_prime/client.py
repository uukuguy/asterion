"""Selected native Asterion Prime control and session-context adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import NoReturn

from asterion.agents.prime.backend import PrimeAttachment
from asterion.agents.prime.state import PrimeBackendIdentity, PrimeBackendSnapshot
from asterion.control.authority import RemainingBudget
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.session_context import (
    SessionContextCommand,
    SessionContextReceipt,
)


_ERROR_MESSAGE = "Asterion Prime control plane is unavailable"
_CANCELLED_MESSAGE = "Asterion Prime control plane operation was cancelled"


class AsterionPrimeControlError(RuntimeError):
    """Fixed public-safe failure from the native Prime control adapter."""


class AsterionPrimeControlPlaneClient:
    """Delegate both public control surfaces to one live backend attachment."""

    def __init__(
        self,
        *,
        manifest: ControlPlaneManifest,
        attachment: PrimeAttachment,
        identity: PrimeBackendIdentity,
        authority_revision: int,
    ) -> None:
        failed = False
        try:
            if (
                type(manifest) is not ControlPlaneManifest
                or type(attachment) is not PrimeAttachment
                or type(identity) is not PrimeBackendIdentity
                or type(authority_revision) is not int
                or authority_revision < 1
            ):
                raise TypeError
            snapshot = attachment.snapshot()
            if (
                type(snapshot) is not PrimeBackendSnapshot
                or snapshot.identity != identity
                or snapshot.authority_revision != authority_revision
            ):
                raise ValueError
        except Exception:
            failed = True
        if failed:
            _raise_control_error()
        self._manifest = manifest
        self._attachment = attachment
        self._identity = identity
        self._authority_revision = authority_revision
        self._closed = False
        self._close_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return (
            "AsterionPrimeControlPlaneClient("
            f"control_plane_id={self._manifest.control_plane_id!r}, "
            f"version={self._manifest.version!r}, closed={self._closed!r})"
        )

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        cancelled = False
        failed = False
        try:
            self._require_open()
            if type(command) is not ControlCommand:
                raise TypeError
            self._validate_identity(
                command.session_id,
                self._identity.generation,
                command.authority_revision,
            )
            await self._attachment.accept_control(command)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            _raise_cancelled()
        if failed:
            _raise_control_error()

    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]:
        failed = False
        try:
            self._require_open()
            if cursor is not None:
                if type(cursor) is not EventCursor:
                    raise TypeError
                self._validate_identity(
                    self._identity.session_id,
                    cursor.generation,
                    self._authority_revision,
                )
        except Exception:
            failed = True
        if failed:
            _raise_control_error()
        return self._iterate_events(cursor)

    async def _iterate_events(
        self, cursor: EventCursor | None
    ) -> AsyncIterator[ControlEvent]:
        cancelled = False
        failed = False
        try:
            self._require_open()
            sequence = 0 if cursor is None else cursor.sequence
            events = self._attachment.replay_events(sequence)
            expected = sequence + 1
            for wrapped in events:
                event = ControlEvent.from_mapping(wrapped.event.to_mapping())
                self._validate_identity(
                    event.session_id,
                    event.generation,
                    self._authority_revision,
                )
                if wrapped.cursor != expected or event.sequence != expected:
                    raise ValueError
                expected += 1
                yield event
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            _raise_cancelled()
        if failed:
            _raise_control_error()

    async def execute_session_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        receipt: SessionContextReceipt | None = None
        cancelled = False
        failed = False
        try:
            self._require_open()
            if type(command) is not SessionContextCommand:
                raise TypeError
            self._validate_identity(
                command.session_id,
                command.generation,
                command.authority_revision,
            )
            received = await self._attachment.execute_context(command)
            if type(received) is not SessionContextReceipt:
                raise TypeError
            receipt = SessionContextReceipt.from_mapping(received.to_mapping())
            if (
                receipt.command_id != command.command_id
                or receipt.session_id != command.session_id
                or receipt.generation != command.generation
                or receipt.operation != command.operation
            ):
                raise ValueError
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            _raise_cancelled()
        if failed or receipt is None:
            _raise_control_error()
        return receipt

    async def cancel_session_context(self, command_id: str) -> None:
        cancelled = False
        failed = False
        try:
            self._require_open()
            await self._attachment.cancel_context(command_id)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            _raise_cancelled()
        if failed:
            _raise_control_error()

    async def sync_authority_snapshot(self, budget: RemainingBudget) -> None:
        cancelled = False
        failed = False
        try:
            self._require_open()
            if type(budget) is not RemainingBudget:
                raise TypeError
            self._attachment.sync_authority_snapshot(
                budget,
                authority_revision=self._authority_revision,
            )
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            _raise_cancelled()
        if failed:
            _raise_control_error()

    async def close(self) -> None:
        cancelled = False
        failed = False
        try:
            async with self._close_lock:
                if self._closed:
                    return
                self._closed = True
                await self._attachment.close()
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            _raise_cancelled()
        if failed:
            _raise_control_error()

    def _require_open(self) -> None:
        if self._closed:
            raise AsterionPrimeControlError(_ERROR_MESSAGE)

    def _validate_identity(
        self,
        session_id: str,
        generation: int,
        authority_revision: int,
    ) -> None:
        if (
            session_id != self._identity.session_id
            or generation != self._identity.generation
            or authority_revision != self._authority_revision
        ):
            raise AsterionPrimeControlError(_ERROR_MESSAGE)


def _raise_control_error() -> NoReturn:
    raise AsterionPrimeControlError(_ERROR_MESSAGE) from None


def _raise_cancelled() -> NoReturn:
    raise asyncio.CancelledError(_CANCELLED_MESSAGE) from None


__all__ = (
    "AsterionPrimeControlError",
    "AsterionPrimeControlPlaneClient",
)
