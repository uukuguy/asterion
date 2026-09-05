"""Opaque authority-local custody for Prime P1 unavailable receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import threading
from types import MappingProxyType
from typing import Any, NoReturn, SupportsIndex
from weakref import WeakKeyDictionary

_RECEIPT_KEY = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]{0,127}\Z")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RECEIPT_DOMAIN = b"asterion.prime-p1-authority-receipt/v1\0"
_NOT_CREATED_DOMAIN = _RECEIPT_DOMAIN + b"not-created\0"


class _AuthorityReceiptIssuer:
    """One-use, deliberately capability-free private receipt-key custody."""

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "AuthorityReceiptIssuer(redacted)"

    def __reduce__(self) -> str | tuple[Any, ...]:
        raise TypeError("authority receipt issuer is unavailable")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> str | tuple[Any, ...]:
        raise TypeError("authority receipt issuer is unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class _AuthorityTerminalBinding:
    session_id: str
    run_id: str
    request_contract_sha256: str
    application_request_sha256: str
    production_resource_set_sha256: str

    def __repr__(self) -> str:
        return "AuthorityTerminalBinding(redacted)"


@dataclass(frozen=True, slots=True, repr=False)
class _UnavailableReceiptMaterial:
    authority_version: str
    authority_executable_sha256: str
    operator_config_binding_hmac_sha256: str
    receipt_key_id: str
    assembly_sha256: str
    package_manifest_sha256: str
    source_sha256: str
    build_input_sha256: str
    image_config_digest: str
    workload_sha256: str
    starter_sha256: str
    oracle_sha256: str
    seccomp_sha256: str

    def __repr__(self) -> str:
        return "UnavailableReceiptMaterial(redacted)"


@dataclass(frozen=True, slots=True, repr=False)
class _IssuedAuthorityReceipt:
    """A signed immutable unavailable terminal, not a signing capability."""

    _binding: _AuthorityTerminalBinding
    _payload: Mapping[str, object]
    _consumption_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )
    _consumed: bool = field(default=False, init=False, repr=False, compare=False)

    def __repr__(self) -> str:
        return "IssuedAuthorityReceipt(redacted)"

    def __reduce__(self) -> str | tuple[Any, ...]:
        raise TypeError("authority receipt is unavailable")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> str | tuple[Any, ...]:
        raise TypeError("authority receipt is unavailable")


_ISSUER_KEYS: WeakKeyDictionary[_AuthorityReceiptIssuer, bytes] = WeakKeyDictionary()


def _new_authority_receipt_issuer(receipt_key_hex: str) -> _AuthorityReceiptIssuer:
    """Create private key custody; no generic signing operation is exposed."""
    if type(receipt_key_hex) is not str or _RECEIPT_KEY.fullmatch(receipt_key_hex) is None:
        _unavailable()
    issuer = _AuthorityReceiptIssuer()
    _ISSUER_KEYS[issuer] = bytes.fromhex(receipt_key_hex)
    return issuer


def _issue_unavailable_receipt(
    issuer: _AuthorityReceiptIssuer,
    binding: _AuthorityTerminalBinding,
    material: _UnavailableReceiptMaterial,
) -> _IssuedAuthorityReceipt:
    """Consume private custody to create the sole authority-unavailable receipt."""
    if type(issuer) is not _AuthorityReceiptIssuer:
        _unavailable()
    try:
        key = _ISSUER_KEYS.pop(issuer)
    except KeyError:
        _unavailable()
    try:
        if type(binding) is not _AuthorityTerminalBinding or type(material) is not _UnavailableReceiptMaterial:
            _unavailable()
        if not _valid_binding(binding) or not _valid_material(material):
            _unavailable()
        unsigned = _unavailable_payload(binding, material)
        digest = hashlib.sha256(_RECEIPT_DOMAIN + _json(unsigned)).hexdigest()
        signed = {**unsigned, "evidence_id": "prime-p1-" + digest, "receipt_sha256": digest}
        payload = {
            **signed,
            "receipt_hmac_sha256": hmac.new(
                key, _RECEIPT_DOMAIN + _json(signed), "sha256"
            ).hexdigest(),
        }
        return _IssuedAuthorityReceipt(binding, _freeze(payload))
    except (TypeError, ValueError, UnicodeError):
        pass
    _unavailable()


def _consume_issued_unavailable_receipt(
    receipt: _IssuedAuthorityReceipt, binding: _AuthorityTerminalBinding
) -> Mapping[str, object]:
    """Atomically consume a receipt for its exact reserved binding object."""
    if (
        type(receipt) is not _IssuedAuthorityReceipt
        or type(binding) is not _AuthorityTerminalBinding
    ):
        _unavailable()
    with receipt._consumption_lock:
        if receipt._binding is not binding or receipt._consumed:
            _unavailable()
        object.__setattr__(receipt, "_consumed", True)
        return receipt._payload


def _unavailable_payload(
    binding: _AuthorityTerminalBinding, material: _UnavailableReceiptMaterial
) -> dict[str, object]:
    return {
        "format": "asterion.prime-p1-authority-receipt/v1",
        "status": "UNAVAILABLE", "reason_code": "unavailable", "run_id": binding.run_id,
        "session_id": binding.session_id,
        "request_contract_sha256": binding.request_contract_sha256,
        "application_request_sha256": binding.application_request_sha256,
        "authority": {
            "authority_version": material.authority_version,
            "authority_executable_sha256": material.authority_executable_sha256,
            "operator_config_binding_hmac_sha256": material.operator_config_binding_hmac_sha256,
            "production_resource_set_sha256": binding.production_resource_set_sha256,
            "receipt_key_id": material.receipt_key_id,
        },
        "identity": {
            "provider_id": "prime-agent", "application_id": "prime.ipython-coding",
            "application_version": "1.0.0", "assembly_ref": "prime.ipython-coding@1.0.0",
            "assembly_sha256": material.assembly_sha256, "package_ref": "prime-agent@1.0.0",
            "package_manifest_sha256": material.package_manifest_sha256,
            "implementation_ref": "prime.ipython-coding@1.0.0", "runtime_id": "prime.agent",
            "prime_sdk_ref": "prime-agent@0.7.1", "source_sha256": material.source_sha256,
            "build_input_sha256": material.build_input_sha256,
            "image_config_digest": material.image_config_digest, "workload_sha256": material.workload_sha256,
            "starter_sha256": material.starter_sha256, "oracle_sha256": material.oracle_sha256,
            "seccomp_sha256": material.seccomp_sha256,
        },
        "model_accounting": {
            "request_count": 0, "input_bytes": 0, "output_bytes": 0,
            "provider_reported_input_tokens": 0, "provider_reported_output_tokens": 0,
            "charged_cost_microunits": 0, "cost_basis": "reserved-ceiling",
            "max_requests": 0, "max_input_bytes": 0, "max_output_bytes": 0,
            "max_input_tokens": 0, "max_output_tokens": 0, "max_cost_microunits": 0,
            "deadline_milliseconds": 0, "request_sha256": _not_created("request"),
            "response_sha256": _not_created("response"),
            "broker_receipt_sha256": _not_created("broker-receipt"), "transport_reaped": False,
        },
        "worker_evidence": {
            "worker_count": 0, "container_id_sha256": _not_created("container"),
            "model_tool_calls": 0, "ipython_tool_calls": 0,
            "sent_cell_sha256": _not_created("sent-cell"),
            "initial_workspace_sha256": _not_created("initial-workspace"),
            "post_workspace_sha256": _not_created("post-workspace"),
            "initial_oracle_passed": False, "final_oracle_passed": False,
            "mutation_after_model_response": False, "broker_quiesced": False,
            "container_removed": False, "daemon_absence_verified": False,
        },
        "causal_evidence": {
            "event_count": 1, "first_sequence": 1, "last_sequence": 1,
            "event_chain_sha256": _not_created("event-chain"),
            "result_projection_sha256": _not_created("result-projection"),
        },
    }


def _valid_binding(value: _AuthorityTerminalBinding) -> bool:
    return (
        _sha256(value.session_id) and type(value.run_id) is str
        and _RUN_ID.fullmatch(value.run_id) is not None
        and all(_sha256(item) for item in (
            value.request_contract_sha256, value.application_request_sha256,
            value.production_resource_set_sha256,
        ))
    )


def _valid_material(value: _UnavailableReceiptMaterial) -> bool:
    return (
        type(value.authority_version) is str and bool(value.authority_version)
        and type(value.receipt_key_id) is str and bool(value.receipt_key_id)
        and type(value.image_config_digest) is str
        and _IMAGE_DIGEST.fullmatch(value.image_config_digest) is not None
        and all(_sha256(item) for item in (
            value.authority_executable_sha256, value.operator_config_binding_hmac_sha256,
            value.assembly_sha256, value.package_manifest_sha256, value.source_sha256,
            value.build_input_sha256, value.workload_sha256, value.starter_sha256,
            value.oracle_sha256, value.seccomp_sha256,
        ))
    )


def _sha256(value: object) -> bool:
    return type(value) is str and _RECEIPT_KEY.fullmatch(value) is not None


def _not_created(name: str) -> str:
    return hashlib.sha256(_NOT_CREATED_DOMAIN + name.encode("ascii")).hexdigest()


def _freeze(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({
        name: _freeze(item) if isinstance(item, Mapping) else item
        for name, item in value.items()
    })


def _json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")


def _unavailable() -> NoReturn:
    raise ValueError("prime P1 authority receipt is unavailable") from None
