from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    OPERATION_PROTOCOL,
    OperationProtocolError,
    OperationReceipt,
    OperationRequestDescriptor,
    OperationTransaction,
    validate_operation_receipt,
    validate_operation_request_descriptor,
    validate_operation_transaction,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "operation" / "v1"
SCHEMAS = ROOT / "schemas" / "operation" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class TestOperationProtocol(unittest.TestCase):
    def test_identity_is_asterion_owned(self) -> None:
        self.assertEqual(OPERATION_PROTOCOL, "asterion.operation/v1")

    def test_transaction_and_receipt_are_closed_body_free_and_immutable(self) -> None:
        descriptor = OperationRequestDescriptor.from_mapping(
            _fixture("valid-request-descriptor.json")
        )
        transaction = OperationTransaction.from_mapping(
            _fixture("valid-transaction.json")
        )
        receipt = OperationReceipt.from_mapping(_fixture("valid-receipt.json"))

        self.assertEqual(transaction.protocol, "asterion.operation/v1")
        self.assertEqual(receipt.effect_counts["network_operations"], 0)
        self.assertEqual(transaction.request, descriptor)
        self.assertNotIn("SENTINEL_BODY", repr((transaction, receipt)))
        with self.assertRaises(TypeError):
            receipt.effect_counts["network_operations"] = 1  # type: ignore[index]
        with self.assertRaises(OperationProtocolError):
            OperationTransaction.from_mapping(
                _fixture("invalid-transaction-secret.json")
            )

    def test_validators_snapshot_the_three_contract_values(self) -> None:
        descriptor_source = _fixture("valid-request-descriptor.json")
        transaction_source = _fixture("valid-transaction.json")
        receipt_source = _fixture("valid-receipt.json")

        descriptor = validate_operation_request_descriptor(descriptor_source)
        transaction = validate_operation_transaction(transaction_source)
        receipt = validate_operation_receipt(receipt_source)

        descriptor_source["client_id"] = "changed"
        transaction_source["operation_id"] = "changed"
        receipt_source["reason_code"] = "changed"
        self.assertEqual(descriptor["client_id"], "client-1")
        self.assertEqual(transaction["operation_id"], "operation-1")
        self.assertEqual(receipt["reason_code"], "operation-succeeded")

    def test_rejects_every_invalid_fixture_without_rendering_private_values(
        self,
    ) -> None:
        cases = (
            ("invalid-protocol-missing.json", validate_operation_request_descriptor),
            ("invalid-identity-mismatch.json", validate_operation_transaction),
            ("invalid-recursive-forbidden-key.json", validate_operation_transaction),
            ("invalid-timestamp.json", validate_operation_transaction),
            ("invalid-unsafe-integer.json", validate_operation_request_descriptor),
            ("invalid-nested-extra.json", validate_operation_transaction),
            ("invalid-canonical-array.json", validate_operation_receipt),
            ("invalid-transaction-secret.json", validate_operation_transaction),
            ("invalid-transaction-unknown.json", validate_operation_transaction),
            ("invalid-receipt-effect-counter.json", validate_operation_receipt),
        )
        for name, validator in cases:
            with (
                self.subTest(name=name),
                self.assertRaises(OperationProtocolError) as raised,
            ):
                validator(_fixture(name))
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
            self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    def test_receipts_have_the_exact_zeroed_prohibited_effect_vector(self) -> None:
        receipt = validate_operation_receipt(_fixture("valid-receipt.json"))
        self.assertEqual(tuple(receipt["effect_counts"]), EFFECT_COUNTERS)
        self.assertEqual(set(receipt["effect_counts"].values()), {0})  # type: ignore[union-attr]

    def test_feature_and_purpose_are_distinct_and_retained_for_later_binding(
        self,
    ) -> None:
        transaction = validate_operation_transaction(
            _fixture("valid-purpose-feature-distinct.json")
        )
        request = transaction["request"]
        assert isinstance(request, Mapping)
        receipt = validate_operation_receipt(
            _fixture("valid-receipt-purpose-feature-distinct.json")
        )

        self.assertEqual(transaction["feature_id"], "operation.auth")
        self.assertEqual(request["purpose"], "operation.auth.read")
        self.assertEqual(receipt["purpose"], request["purpose"])

    def test_operation_contracts_expose_no_array_bearing_public_fields(self) -> None:
        schemas = tuple(
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(SCHEMAS.glob("*.json"))
        )
        for schema in schemas:
            with self.subTest(schema=schema["$id"]):
                self.assertFalse(
                    any(
                        property_schema.get("type") == "array"
                        for property_schema in schema["properties"].values()
                    )
                )
        # The retained fixture name documents that any array fails closed here:
        # effect_counts is a closed object, not a sortable public vector.
        with self.assertRaises(OperationProtocolError):
            validate_operation_receipt(_fixture("invalid-canonical-array.json"))

    def test_wire_schemas_are_closed_and_body_free(self) -> None:
        schemas = tuple(
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(SCHEMAS.glob("*.json"))
        )
        self.assertEqual(len(schemas), 3)
        rendered = json.dumps(schemas, sort_keys=True)
        for schema in schemas:
            self.assertFalse(schema["additionalProperties"])
        for forbidden in (
            "api_key",
            "authorization",
            "body",
            "credential",
            "destination",
            "path",
            "prompt",
            "refresh_token",
            "text",
            "token",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'"{forbidden}"', rendered)


if __name__ == "__main__":
    unittest.main()
