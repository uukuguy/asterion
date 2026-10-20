"""Exact implementation binding for native Prime P2 programmatic long context."""

from __future__ import annotations

from pathlib import Path

from asterion.capability_sdk import (
    CapabilityImplementationBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)
from asterion.capabilities.prime_native_receipt import PrimeNativeReceiptImplementation


PACKAGE_REF = CapabilityPackageRef("prime-programmatic-long-context-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.programmatic-long-context", "1.0.0")
P2_INPUT_PRESET = "fixed-small-verification"
P2_ARTIFACT_ID = "prime.p2-native.receipt"
P2_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p2-native-receipt+json"
)


def create_prime_programmatic_long_context_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-programmatic-long-context-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF,
                PrimeNativeReceiptImplementation(
                    CAPABILITY_REF,
                    P2_ARTIFACT_ID,
                    P2_RECEIPT_MEDIA_TYPE,
                ),
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "P2_ARTIFACT_ID",
    "P2_INPUT_PRESET",
    "P2_RECEIPT_MEDIA_TYPE",
    "PACKAGE_REF",
    "create_prime_programmatic_long_context_native_package",
)