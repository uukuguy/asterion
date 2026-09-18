"""Exact implementation binding for native Prime P4 long-session-continuity."""

from __future__ import annotations

from pathlib import Path

from asterion.capability_sdk import (
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
    open_portable_payload,
)


PACKAGE_REF = CapabilityPackageRef("prime-long-session-continuity-native", "1.0.0")
CAPABILITY_REF = CapabilityRef("prime.long-session-continuity", "1.0.0")
P4_INPUT_PRESET = "fixed-cross-generation-continuity"
P4_ARTIFACT_ID = "prime.p4-native.receipt"
P4_RECEIPT_MEDIA_TYPE = (
    "application/vnd.asterion.prime.p4-native-receipt+json"
)


def create_prime_long_session_continuity_native_package() -> InstalledCapabilityPackage:
    """Load the exact builtin package after portable payload validation."""

    payload_root = Path(__file__).resolve().parent / "payload"
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=PACKAGE_REF,
        payload_sha256=payload.payload_sha256,
        source_id="prime-long-session-continuity-native.builtin",
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=(),  # operator-driven; no synchronous implementation
        benchmark_bindings=(),
    )


__all__ = (
    "CAPABILITY_REF",
    "PACKAGE_REF",
    "P4_ARTIFACT_ID",
    "P4_INPUT_PRESET",
    "P4_RECEIPT_MEDIA_TYPE",
    "create_prime_long_session_continuity_native_package",
)