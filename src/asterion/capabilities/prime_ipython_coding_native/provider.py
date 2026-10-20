"""Exact implementation binding for native Prime P1 coding."""

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


PACKAGE_REF = CapabilityPackageRef("prime-ipython-coding-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.ipython-coding", "1.0.0")
P1_INPUT_PRESET = "fixed-small-verification"
P1_ARTIFACT_ID = "prime.p1-native.receipt"
P1_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p1-native-receipt+json"


def create_prime_ipython_coding_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-ipython-coding-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF,
                PrimeNativeReceiptImplementation(
                    CAPABILITY_REF,
                    P1_ARTIFACT_ID,
                    P1_RECEIPT_MEDIA_TYPE,
                ),
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "P1_ARTIFACT_ID",
    "P1_INPUT_PRESET",
    "P1_RECEIPT_MEDIA_TYPE",
    "create_prime_ipython_coding_native_package",
)
