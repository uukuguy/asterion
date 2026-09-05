"""Opaque authority-local custody for Prime P1 receipt material."""

from __future__ import annotations

import re
from typing import Any, SupportsIndex
from weakref import WeakKeyDictionary


_RECEIPT_KEY = re.compile(r"[0-9a-f]{64}\Z")


class _AuthorityReceiptIssuer:
    """Deliberately capability-free receipt issuer placeholder."""

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "AuthorityReceiptIssuer(redacted)"

    def __reduce__(self) -> str | tuple[Any, ...]:
        raise TypeError("authority receipt issuer is unavailable")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> str | tuple[Any, ...]:
        raise TypeError("authority receipt issuer is unavailable")


_ISSUER_KEYS: WeakKeyDictionary[_AuthorityReceiptIssuer, bytes] = WeakKeyDictionary()


def _new_authority_receipt_issuer(receipt_key_hex: str) -> _AuthorityReceiptIssuer:
    """Create private key custody; no receipt or signing operation exists yet."""
    if (
        type(receipt_key_hex) is not str
        or _RECEIPT_KEY.fullmatch(receipt_key_hex) is None
    ):
        raise ValueError
    issuer = _AuthorityReceiptIssuer()
    _ISSUER_KEYS[issuer] = bytes.fromhex(receipt_key_hex)
    return issuer
