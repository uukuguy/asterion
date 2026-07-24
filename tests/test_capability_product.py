from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.applications.product import (
    CapabilityFunction,
    CapabilityProductDescription,
    CapabilityProductError,
    ConfigurationRequirement,
    InstalledCapabilityProduct,
    VerificationCheckResult,
    VerificationProfile,
    VerificationRequest,
    VerificationResult,
    validate_capability_product,
    validate_verification_result,
)


def description() -> CapabilityProductDescription:
    return CapabilityProductDescription(
        product_id="example-product",
        version="1.0.0",
        summary="Example capability product",
        functions=(
            CapabilityFunction(
                function_id="research",
                summary="Research a local corpus",
                argv=("example", "run"),
            ),
        ),
        configuration=(
            ConfigurationRequirement(
                name="EXAMPLE_API_KEY",
                purpose="Provider credential",
                required_for=("basic",),
                secret=True,
                default=None,
                hint="Set this in .env",
            ),
        ),
        profiles=(
            VerificationProfile(
                level="preflight",
                summary="Check local prerequisites",
                cost_class="provider-free",
                provider_backed_operation_count=0,
                full_dataset=False,
            ),
        ),
    )


class CapabilityProductTests(unittest.TestCase):
    def test_valid_product_is_frozen_and_preserved(self) -> None:
        product = validate_capability_product(
            InstalledCapabilityProduct(description=description(), verifier=lambda request: None)
        )

        self.assertEqual(product.description.product_id, "example-product")
        with self.assertRaises(FrozenInstanceError):
            product.description.summary = "changed"

    def test_invalid_identifiers_ordering_and_collections_fail_closed(self) -> None:
        valid = description()
        cases = (
            CapabilityProductDescription(
                product_id="Bad ID",
                version=valid.version,
                summary=valid.summary,
                functions=valid.functions,
                configuration=valid.configuration,
                profiles=valid.profiles,
            ),
            CapabilityProductDescription(
                product_id=valid.product_id,
                version=valid.version,
                summary=valid.summary,
                functions=(valid.functions[0], valid.functions[0]),
                configuration=valid.configuration,
                profiles=valid.profiles,
            ),
            CapabilityProductDescription(
                product_id=valid.product_id,
                version=valid.version,
                summary=valid.summary,
                functions=valid.functions,
                configuration=valid.configuration,
                profiles=(
                    VerificationProfile(
                        level="preflight",
                        summary="Unsafe",
                        cost_class="unknown",
                        provider_backed_operation_count=0,
                        full_dataset=False,
                    ),
                ),
            ),
        )
        for item in cases:
            with self.subTest(item=item), self.assertRaises(CapabilityProductError):
                validate_capability_product(
                    InstalledCapabilityProduct(description=item, verifier=lambda request: None)
                )

    def test_verification_result_accepts_only_safe_aggregate_evidence(self) -> None:
        result = VerificationResult(
            product_id="example-product",
            level="preflight",
            status="PASS",
            checks=(
                VerificationCheckResult(
                    check_id="configuration",
                    summary="Configuration is present",
                    status="PASS",
                    artifact_refs=("reports/summary.json",),
                    counts=(("present", 3),),
                ),
            ),
            provider_backed_operation_count=0,
            full_dataset_ran=False,
        )

        self.assertIs(validate_verification_result(result, description()), result)
        invalid = VerificationResult(
            product_id=result.product_id,
            level=result.level,
            status=result.status,
            checks=(
                VerificationCheckResult(
                    check_id="configuration",
                    summary="Configuration is present",
                    status="PASS",
                    artifact_refs=("/private/result.json",),
                    counts=(),
                ),
            ),
            provider_backed_operation_count=0,
            full_dataset_ran=False,
        )
        with self.assertRaises(CapabilityProductError):
            validate_verification_result(invalid, description())

    def test_verification_request_carries_only_explicit_paths(self) -> None:
        request = VerificationRequest(
            level="preflight",
            env_file=Path(".env"),
            corpus_root=None,
            output_root=None,
            acceptance_root=None,
        )

        self.assertEqual(request.env_file, Path(".env"))


if __name__ == "__main__":
    unittest.main()
