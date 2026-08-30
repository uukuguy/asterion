"""Asynchronous client edge for the native control provider."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import NoReturn

from asterion.control.authority import RemainingBudget
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)
from asterion.control.providers.native.controller import (
    NativeController,
    NativeControllerError,
)
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeTurnRequest,
    NativeTurnResult,
)
from asterion.control.providers.native.store import NativeStoreError


class NativeControlError(RuntimeError):
    """Raised when native client transport cannot safely continue."""

    def __init__(self, *_: object) -> None:
        super().__init__("native control is unavailable")
        self.__cause__ = None
        self.__context__ = None


def _raise_control_error() -> NoReturn:
    try:
        raise NativeControlError from None
    except NativeControlError as error:
        error.__context__ = None
        raise


class NativeControlPlaneClient:
    """Provider-neutral async control client backed by one native controller."""

    def __init__(
        self,
        *,
        manifest: ControlPlaneManifest,
        controller: NativeController,
        max_turns_per_poll: int,
        max_events_per_poll: int,
    ) -> None:
        try:
            if type(manifest) is not ControlPlaneManifest:
                raise NativeControlError
            if type(controller) is not NativeController:
                raise NativeControlError
            _require_positive_safe_integer(max_turns_per_poll)
            _require_positive_safe_integer(max_events_per_poll)
            self._manifest = manifest
            self._controller = controller
            self._max_turns_per_poll = max_turns_per_poll
            self._max_events_per_poll = max_events_per_poll
            self._lock = asyncio.Lock()
            self._closed = False
        except NativeControlError:
            _raise_control_error()
        except Exception:
            _raise_control_error()

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        if type(command) is not ControlCommand:
            _raise_control_error()
        async with self._lock:
            self._require_open()
            try:
                await self._controller.accept(command)
            except (NativeControllerError, NativeStoreError):
                _raise_control_error()
            except Exception:
                _raise_control_error()

    def events(
        self, cursor: EventCursor | None = None
    ) -> AsyncIterator[ControlEvent]:
        if cursor is not None and type(cursor) is not EventCursor:
            _raise_control_error()
        self._require_open()
        return self._iterate(cursor)

    async def sync_authority_snapshot(self, budget: RemainingBudget) -> None:
        if type(budget) is not RemainingBudget:
            _raise_control_error()
        async with self._lock:
            self._require_open()
            try:
                self._controller.sync_authority(budget)
            except (NativeControllerError, NativeStoreError):
                _raise_control_error()
            except Exception:
                _raise_control_error()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            try:
                self._controller.close()
            except (NativeControllerError, NativeStoreError):
                _raise_control_error()
            except Exception:
                _raise_control_error()
            self._closed = True

    async def _iterate(
        self, cursor: EventCursor | None
    ) -> AsyncIterator[ControlEvent]:
        current_cursor = cursor
        yielded = 0
        turns_started = 0
        while yielded < self._max_events_per_poll:
            suffix = await self._snapshot_events(current_cursor)
            if suffix:
                for event in suffix:
                    async with self._lock:
                        self._require_open()
                    if yielded >= self._max_events_per_poll:
                        return
                    yield event
                    yielded += 1
                    current_cursor = EventCursor(event.generation, event.sequence)
                continue

            if turns_started >= self._max_turns_per_poll:
                return
            request = await self._begin_turn()
            if request is None:
                return
            turns_started += 1

            if await self._commit_budget_limited_if_needed(request):
                continue

            result: NativeTurnResult | None = None
            failed = False
            try:
                result = await self._controller.execute_turn(request)
            except (NativeControllerError, NativeStoreError):
                failed = True
            except Exception:
                failed = True
            if failed:
                await self._commit_failed_turn_or_discard_cancelled(
                    request, "native-turn-failed"
                )
                continue
            assert result is not None
            await self._commit_result_or_recover(request, result)

    async def _snapshot_events(
        self, cursor: EventCursor | None
    ) -> tuple[ControlEvent, ...]:
        async with self._lock:
            self._require_open()
            try:
                return self._controller.replay_events(cursor)
            except (NativeControllerError, NativeStoreError):
                _raise_control_error()
            except Exception:
                _raise_control_error()

    async def _begin_turn(self) -> NativeTurnRequest | None:
        async with self._lock:
            self._require_open()
            try:
                request = self._controller.begin_ready_turn()
            except (NativeControllerError, NativeStoreError):
                _raise_control_error()
            except Exception:
                _raise_control_error()
            if request is not None and type(request) is not NativeTurnRequest:
                _raise_control_error()
            return request

    async def _commit_budget_limited_if_needed(
        self, request: NativeTurnRequest
    ) -> bool:
        async with self._lock:
            self._require_open()
            try:
                if not self._controller.turn_is_budget_limited(request):
                    return False
                self._controller.commit_budget_limited_turn(request)
                return True
            except (NativeControllerError, NativeStoreError):
                _raise_control_error()
            except Exception:
                _raise_control_error()

    async def _commit_result_or_recover(
        self, request: NativeTurnRequest, result: NativeTurnResult
    ) -> None:
        async with self._lock:
            self._require_open()
            if self._discardable_fenced_terminal(request):
                return
            if self._controller.state.pending_turn != request:
                _raise_control_error()
            try:
                self._controller.commit_turn(request, result)
            except (NativeControllerError, NativeStoreError):
                self._fail_pending_turn(request, "native-turn-result-invalid")
            except Exception:
                self._fail_pending_turn(request, "native-turn-result-invalid")

    async def _commit_failed_turn_or_discard_cancelled(
        self, request: NativeTurnRequest, reason_code: str
    ) -> None:
        async with self._lock:
            self._require_open()
            if self._discardable_fenced_terminal(request):
                return
            if self._controller.state.pending_turn != request:
                _raise_control_error()
            self._fail_pending_turn(request, reason_code)

    def _fail_pending_turn(
        self, request: NativeTurnRequest, reason_code: str
    ) -> None:
        try:
            self._controller.fail_turn(request, reason_code)
        except (NativeControllerError, NativeStoreError):
            _raise_control_error()
        except Exception:
            _raise_control_error()

    def _discardable_fenced_terminal(self, request: NativeTurnRequest) -> bool:
        state = self._controller.state
        return (
            state.pending_turn is None
            and state.terminal_event_id is not None
            and request.turn_id in state.fenced_turn_ids
            and request.turn_id not in state.committed_turn_digests
            and request.turn_id not in state.recovery_required_turn_ids
        )

    def _require_open(self) -> None:
        if self._closed:
            _raise_control_error()


def _require_positive_safe_integer(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeControlError
