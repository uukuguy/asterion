"""Exact implementation binding for native Prime P6 continual-improvement."""

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


PACKAGE_REF = CapabilityPackageRef("prime-continual-improvement-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.continual-improvement", "1.0.0")
P6_INPUT_PRESET = "fixed-continual-improvement"
P6_ARTIFACT_ID = "prime.p6-native.receipt"
P6_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p6-native-receipt+json"


def create_prime_continual_improvement_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-continual-improvement-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF,
                PrimeNativeReceiptImplementation(
                    CAPABILITY_REF,
                    P6_INPUT_PRESET,
                    P6_ARTIFACT_ID,
                    P6_RECEIPT_MEDIA_TYPE,
                    "p6-native",
                    120_000,
                ),
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "PACKAGE_REF",
    "P6_ARTIFACT_ID",
    "P6_INPUT_PRESET",
    "P6_RECEIPT_MEDIA_TYPE",
    "create_prime_continual_improvement_native_package",
)
