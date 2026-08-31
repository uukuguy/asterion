"""Explicitly authorized, dormant Native bounded-turn boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from asterion.control.protocol import OPAQUE_ID
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeTurnRequest,
    NativeTurnResult,
)


_CONSUMED_RESERVATION_IDS: set[str] = set()


class NativeBoundedTurnError(ValueError):
    """Raised with a public-safe error before a bounded turn can proceed."""

    def __init__(self, *_: object) -> None:
        super().__init__("native bounded turn is unavailable")
        self.__cause__ = None
        self.__context__ = None


@dataclass(frozen=True, repr=False)
class NativeBoundedReservation:
    reservation_id: str
    provider_digest: str
    model_digest: str
    max_turns: int
    max_cost_micros: int
    deadline_ms: int


class NativeBoundedTurnHost(Protocol):
    async def execute(
        self,
        reservation: NativeBoundedReservation,
        request: NativeTurnRequest,
    ) -> NativeTurnResult: ...


class BoundedNativeTurnAdapter:
    """One reservation-bound adapter suitable for explicit factory injection."""

    adapter_id = "native.bounded-turn/v1"

    def __init__(
        self,
        reservation: NativeBoundedReservation,
        host: NativeBoundedTurnHost,
    ) -> None:
        if type(reservation) is not NativeBoundedReservation or not _valid_reservation(
            reservation
        ):
            raise NativeBoundedTurnError
        self._reservation = reservation
        self._host = host

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        return await run_bounded_native_turn(self._reservation, self._host, request)


async def run_bounded_native_turn(
    reservation: NativeBoundedReservation | None,
    host: NativeBoundedTurnHost,
    request: NativeTurnRequest,
) -> NativeTurnResult:
    if type(reservation) is not NativeBoundedReservation or not _valid_reservation(
        reservation
    ):
        raise NativeBoundedTurnError
    if type(request) is not NativeTurnRequest:
        raise NativeBoundedTurnError
    if reservation.reservation_id in _CONSUMED_RESERVATION_IDS:
        raise NativeBoundedTurnError
    _CONSUMED_RESERVATION_IDS.add(reservation.reservation_id)
    execute = getattr(host, "execute", None)
    if not callable(execute):
        raise NativeBoundedTurnError
    try:
        result = await execute(reservation, request)
    except Exception:
        raise NativeBoundedTurnError from None
    if (
        type(result) is not NativeTurnResult
        or result.turn_id != request.turn_id
        or result.usage.cost_micros > reservation.max_cost_micros
    ):
        raise NativeBoundedTurnError
    return result


def _valid_reservation(reservation: NativeBoundedReservation) -> bool:
    return (
        OPAQUE_ID.fullmatch(reservation.reservation_id) is not None
        and _sha256(reservation.provider_digest)
        and _sha256(reservation.model_digest)
        and all(
            type(value) is int and 0 < value <= MAX_SAFE_JSON_INTEGER
            for value in (
                reservation.max_turns,
                reservation.max_cost_micros,
                reservation.deadline_ms,
            )
        )
    )


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
