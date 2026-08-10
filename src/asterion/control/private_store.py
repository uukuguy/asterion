"""Provider-neutral private content and result store contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from asterion.control.protocol import MEDIA_TYPE, OPAQUE_ID
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


MAX_PRIVATE_TEXT_BYTES = 1024 * 1024


class PrivateStoreError(ValueError):
    """Raised when private store values violate the public-safe contract."""


class PrivateContentResolver(Protocol):
    """Host-owned resolver for private text references."""

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        """Resolve a private text reference without exposing the body."""
        ...


class PrivateAttachmentResolver(Protocol):
    """Host-owned resolver for verified private attachment bytes."""

    def resolve_bytes(
        self,
        reference: str,
        *,
        expected_media_type: str,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
    ) -> bytes:
        """Resolve exact bytes without exposing the attachment body."""
        ...


@dataclass(frozen=True, repr=False)
class PrivateResultPublication:
    """Public-safe projection of a privately stored application result."""

    action_id: str
    receipt_ref: str
    artifact_ids: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action_id, str)
            or OPAQUE_ID.fullmatch(self.action_id) is None
            or not isinstance(self.receipt_ref, str)
            or OPAQUE_ID.fullmatch(self.receipt_ref) is None
            or type(self.artifact_ids) is not tuple
            or type(self.media_types) is not tuple
            or not is_sorted_unique_scalar_strings(list(self.artifact_ids))
            or not is_sorted_unique_scalar_strings(list(self.media_types))
            or any(OPAQUE_ID.fullmatch(value) is None for value in self.artifact_ids)
            or any(MEDIA_TYPE.fullmatch(value) is None for value in self.media_types)
        ):
            raise PrivateStoreError("private result publication is invalid")

    def __repr__(self) -> str:
        return (
            "PrivateResultPublication("
            f"artifact_count={len(self.artifact_ids)}, "
            f"media_type_count={len(self.media_types)})"
        )


class PrivateResultStore(Protocol):
    """Host-owned publisher for private raw application results."""

    def publish_application_result(
        self,
        *,
        action_id: str,
        provider_id: str,
        application_id: str,
        version: str,
        runtime_id: str,
        idempotency_key: str,
        run_id: str,
        result: object,
    ) -> PrivateResultPublication:
        """Store private raw result and return its public-safe receipt projection."""
        ...


def validate_private_result_publication(
    value: object,
) -> PrivateResultPublication:
    """Return one immutable public-safe result projection."""

    if isinstance(value, PrivateResultPublication):
        return value
    if (
        not isinstance(value, Mapping)
        or set(value) != {"action_id", "receipt_ref", "artifact_ids", "media_types"}
    ):
        raise PrivateStoreError("private result publication is invalid")
    try:
        action_id = value["action_id"]
        receipt_ref = value["receipt_ref"]
        artifact_ids = tuple(value["artifact_ids"])  # type: ignore[arg-type]
        media_types = tuple(value["media_types"])  # type: ignore[arg-type]
        if (
            not isinstance(action_id, str)
            or not isinstance(receipt_ref, str)
            or any(not isinstance(item, str) for item in artifact_ids)
            or any(not isinstance(item, str) for item in media_types)
        ):
            raise TypeError
        return PrivateResultPublication(
            action_id=action_id,
            receipt_ref=receipt_ref,
            artifact_ids=artifact_ids,
            media_types=media_types,
        )
    except (KeyError, TypeError, ValueError):
        raise PrivateStoreError("private result publication is invalid") from None
