"""Host-owned resolution of client private values."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_MEDIA_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
)
_PURPOSES = frozenset(
    {"interactive-render", "headless-final", "extension-ui-response", "private-export"}
)
_MAX_CLOCK_MS = (1 << 63) - 1


class ClientPrivateValueError(ValueError):
    """Raised without exposing private value details."""


@dataclass(frozen=True, repr=False)
class ClientAccess:
    client_id: str
    session_id: str
    authority_revision: int
    purposes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            _OPAQUE_ID.fullmatch(self.client_id) is None
            or _OPAQUE_ID.fullmatch(self.session_id) is None
            or isinstance(self.authority_revision, bool)
            or not isinstance(self.authority_revision, int)
            or self.authority_revision < 1
            or not isinstance(self.purposes, tuple)
            or not self.purposes
            or tuple(sorted(set(self.purposes))) != self.purposes
            or any(purpose not in _PURPOSES for purpose in self.purposes)
        ):
            raise ClientPrivateValueError("client private access is invalid")


@dataclass(frozen=True, repr=False)
class PrivateValueDescriptor:
    reference: str
    kind: str
    media_type: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            _OPAQUE_ID.fullmatch(self.reference) is None
            or _IDENTIFIER.fullmatch(self.kind) is None
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
            or isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size < 0
            or not isinstance(self.sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
        ):
            raise ClientPrivateValueError("private value descriptor is invalid")


class ClientPrivateValueBackend(Protocol):
    def describe(self, reference: str) -> PrivateValueDescriptor:
        ...

    def read(self, reference: str, *, max_bytes: int) -> bytes:
        ...


class _CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool:
        ...


class ClientPrivateValueService:
    """Resolve one descriptor-bound private value under explicit client access."""

    def __init__(
        self,
        *,
        access: ClientAccess,
        backend: ClientPrivateValueBackend,
        clock_ms: Callable[[], int],
        authority_revision_source: Callable[[], int],
        cancellation_signal: _CancellationSignal | None = None,
    ) -> None:
        _cancellation_signal_value(
            cancellation_signal, error_message="client private service is invalid"
        )
        if (
            not isinstance(access, ClientAccess)
            or not callable(getattr(backend, "describe", None))
            or not callable(getattr(backend, "read", None))
            or not callable(clock_ms)
            or not callable(authority_revision_source)
        ):
            raise ClientPrivateValueError("client private service is invalid")
        self._access = access
        self._backend = backend
        self._clock_ms = clock_ms
        self._authority_revision_source = authority_revision_source
        self._cancellation_signal = cancellation_signal

    @property
    def access(self) -> ClientAccess:
        return self._access

    def validate_export_access(
        self, *, authority_revision: int, expires_at_ms: int
    ) -> None:
        """Check export authority freshness without resolving a private value."""

        now = self._current_clock_ms()
        try:
            live_authority_revision = self._authority_revision_source()
        except asyncio.CancelledError:
            raise ClientPrivateValueError("private value access is denied") from None
        except Exception:
            raise ClientPrivateValueError("private value access is denied") from None
        if (
            "private-export" not in self._access.purposes
            or isinstance(authority_revision, bool)
            or not isinstance(authority_revision, int)
            or authority_revision != self._access.authority_revision
            or isinstance(expires_at_ms, bool)
            or not isinstance(expires_at_ms, int)
            or expires_at_ms < now
            or isinstance(live_authority_revision, bool)
            or not isinstance(live_authority_revision, int)
            or live_authority_revision != self._access.authority_revision
            or _cancellation_signal_value(
                self._cancellation_signal,
                error_message="private value access is denied",
            )
        ):
            raise ClientPrivateValueError("private value access is denied")

    def describe_for_export(
        self,
        reference: str,
        *,
        max_bytes: int,
        deadline_ms: int,
        authority_revision: int,
        expires_at_ms: int,
    ) -> PrivateValueDescriptor:
        """Describe a private export value before any export body is read."""

        self._validate_request(
            reference=reference,
            purpose="private-export",
            max_bytes=max_bytes,
            deadline_ms=deadline_ms,
            authority_revision=authority_revision,
            expires_at_ms=expires_at_ms,
        )
        try:
            descriptor = self._backend.describe(reference)
            self._validate_descriptor(reference, descriptor, max_bytes)
        except ClientPrivateValueError:
            raise
        except asyncio.CancelledError:
            raise ClientPrivateValueError("private value is unavailable") from None
        except Exception:
            raise ClientPrivateValueError("private value is unavailable") from None
        return descriptor

    def resolve_bytes(
        self,
        reference: str,
        *,
        purpose: str,
        max_bytes: int,
        deadline_ms: int,
        authority_revision: int | None = None,
        expires_at_ms: int | None = None,
    ) -> bytes:
        self._validate_request(
            reference=reference,
            purpose=purpose,
            max_bytes=max_bytes,
            deadline_ms=deadline_ms,
            authority_revision=authority_revision,
            expires_at_ms=expires_at_ms,
        )
        try:
            before = self._backend.describe(reference)
            self._validate_descriptor(reference, before, max_bytes)
            body = self._backend.read(reference, max_bytes=max_bytes)
            after = self._backend.describe(reference)
        except ClientPrivateValueError:
            raise
        except asyncio.CancelledError:
            raise ClientPrivateValueError("private value is unavailable") from None
        except Exception:
            raise ClientPrivateValueError("private value is unavailable") from None
        if (
            not isinstance(body, bytes)
            or len(body) != before.size
            or len(body) > max_bytes
            or hashlib.sha256(body).hexdigest() != before.sha256
            or after != before
        ):
            raise ClientPrivateValueError("private value integrity is invalid")
        self._validate_request(
            reference=reference,
            purpose=purpose,
            max_bytes=max_bytes,
            deadline_ms=deadline_ms,
            authority_revision=authority_revision,
            expires_at_ms=expires_at_ms,
        )
        return bytes(body)

    def resolve_text(self, reference: str, **kwargs: object) -> str:
        body = self.resolve_bytes(reference, **kwargs)  # type: ignore[arg-type]
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            raise ClientPrivateValueError("private value text is invalid") from None

    def _validate_request(
        self,
        *,
        reference: str,
        purpose: str,
        max_bytes: int,
        deadline_ms: int,
        authority_revision: int | None,
        expires_at_ms: int | None,
    ) -> None:
        now = self._current_clock_ms()
        try:
            live_authority_revision = self._authority_revision_source()
        except asyncio.CancelledError:
            raise ClientPrivateValueError("private value access is denied") from None
        except Exception:
            raise ClientPrivateValueError("private value access is denied") from None
        if (
            _OPAQUE_ID.fullmatch(reference) is None
            or purpose not in _PURPOSES
            or purpose not in self._access.purposes
            or isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or max_bytes < 1
            or isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or deadline_ms < now
            or (expires_at_ms is not None and (isinstance(expires_at_ms, bool) or not isinstance(expires_at_ms, int) or expires_at_ms < now))
            or isinstance(live_authority_revision, bool)
            or not isinstance(live_authority_revision, int)
            or live_authority_revision != self._access.authority_revision
            or (authority_revision is not None and authority_revision != live_authority_revision)
            or _cancellation_signal_value(
                self._cancellation_signal,
                error_message="private value access is denied",
            )
        ):
            raise ClientPrivateValueError("private value access is denied")

    def _current_clock_ms(self) -> int:
        try:
            now = self._clock_ms()
        except asyncio.CancelledError:
            raise ClientPrivateValueError("private value access is denied") from None
        except Exception:
            raise ClientPrivateValueError("private value access is denied") from None
        if (
            isinstance(now, bool)
            or not isinstance(now, int)
            or now < 0
            or now > _MAX_CLOCK_MS
        ):
            raise ClientPrivateValueError("private value access is denied")
        return now

    @staticmethod
    def _validate_descriptor(
        reference: str, descriptor: object, max_bytes: int
    ) -> None:
        if (
            not isinstance(descriptor, PrivateValueDescriptor)
            or descriptor.reference != reference
            or descriptor.size > max_bytes
        ):
            raise ClientPrivateValueError("private value descriptor is invalid")


def _cancellation_signal_value(
    cancellation_signal: _CancellationSignal | None, *, error_message: str
) -> bool:
    if cancellation_signal is None:
        return False
    try:
        cancelled = cancellation_signal.cancelled
    except asyncio.CancelledError:
        raise ClientPrivateValueError(error_message) from None
    except Exception:
        raise ClientPrivateValueError(error_message) from None
    if type(cancelled) is not bool:
        raise ClientPrivateValueError(error_message)
    return cancelled
