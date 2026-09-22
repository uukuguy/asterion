"""Exact implementation binding for native Prime P3 recursive-workflow."""

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


PACKAGE_REF = CapabilityPackageRef("prime-recursive-workflow-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.recursive-workflow", "1.0.0")
P3_INPUT_PRESET = "fixed-recursive-workflow"
P3_ARTIFACT_ID = "prime.p3-native.receipt"
P3_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p3-native-receipt+json"
)


def create_prime_recursive_workflow_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-recursive-workflow-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(
            CapabilityImplementationBinding(
                CAPABILITY_REF,
                PrimeNativeReceiptImplementation(
                    CAPABILITY_REF,
                    P3_INPUT_PRESET,
                    P3_ARTIFACT_ID,
                    P3_RECEIPT_MEDIA_TYPE,
                    "p3-native",
                    60_000,
                ),
            ),
        ),
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "PACKAGE_REF",
    "P3_ARTIFACT_ID",
    "P3_INPUT_PRESET",
    "P3_RECEIPT_MEDIA_TYPE",
    "create_prime_recursive_workflow_native_package",
)
