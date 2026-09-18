"""Exact implementation binding for native Prime P5 bounded-autonomy."""

from __future__ import annotations

from pathlib import Path

from asterion.capability_sdk import (
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


PACKAGE_REF = CapabilityPackageRef("prime-bounded-autonomy-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.bounded-autonomy", "1.0.0")
P5_INPUT_PRESET = "fixed-bounded-autonomy"
P5_ARTIFACT_ID = "prime.p5-native.receipt"
P5_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p5-native-receipt+json"
)


def create_prime_bounded_autonomy_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-bounded-autonomy-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(),  # operator-driven; no synchronous implementation
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "PACKAGE_REF",
    "P5_ARTIFACT_ID",
    "P5_INPUT_PRESET",
    "P5_RECEIPT_MEDIA_TYPE",
    "create_prime_bounded_autonomy_native_package",
)