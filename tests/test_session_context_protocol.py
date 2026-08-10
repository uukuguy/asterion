from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.session_context import (
    MAX_SAFE_INTEGER,
    SESSION_CONTEXT_OPERATIONS,
    SESSION_CONTEXT_PROTOCOL,
    SessionContextCommand,
    SessionContextProtocolError,
    SessionContextReceipt,
    validate_session_context_command,
    validate_session_context_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "session_context" / "v1"
COMMAND_SCHEMA = ROOT / "schemas" / "session-context" / "v1" / "command.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas" / "session-context" / "v1" / "receipt.schema.json"
SHA256_A = "a" * 64


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _command(operation: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "protocol": SESSION_CONTEXT_PROTOCOL,
        "command_id": f"command-{operation}",
        "session_id": "session-1",
        "generation": 1,
        "authority_revision": 2,
        "idempotency_key": f"idempotency-{operation}",
        "operation": operation,
        "payload": payload,
    }


def _receipt(
    operation: str,
    result: dict[str, object] | None,
    *,
    status: str = "succeeded",
) -> dict[str, object]:
    return {
        "protocol": SESSION_CONTEXT_PROTOCOL,
        "receipt_id": f"receipt-{operation}",
        "command_id": f"command-{operation}",
        "session_id": "session-1",
        "generation": 1,
        "operation": operation,
        "status": status,
        "reason_code": "session-context-succeeded",
        "payload": {"evidence_ref": "evidence-1", "result": result},
    }


class TestSessionContextProtocol(unittest.TestCase):
    def test_protocol_identity_and_operation_set_are_closed(self) -> None:
        self.assertEqual(SESSION_CONTEXT_PROTOCOL, "asterion.session-context/v1")
        self.assertEqual(
            SESSION_CONTEXT_OPERATIONS,
            frozenset(
                {
                    "session.attachment.bind",
                    "session.branch.summarize",
                    "session.clone",
                    "session.compact",
                    "session.continuation.delete",
                    "session.continuation.resume",
                    "session.describe",
                    "session.fork",
                    "session.label.set",
                    "session.name.set",
                    "session.tree.navigate",
                    "session.tree.read",
                }
            ),
        )

    def test_valid_fixtures_are_recursively_immutable_snapshots(self) -> None:
        command_source = _fixture("valid-command-tree-read.json")
        receipt_source = _fixture("valid-receipt-tree-read.json")
        root_navigation_source = _fixture("valid-receipt-tree-navigate-root.json")

        command = validate_session_context_command(command_source)
        receipt = validate_session_context_receipt(receipt_source)
        root_navigation = validate_session_context_receipt(root_navigation_source)
        receipt_payload = receipt["payload"]
        assert isinstance(receipt_payload, Mapping)
        receipt_result = receipt_payload["result"]
        assert isinstance(receipt_result, Mapping)
        root_navigation_payload = root_navigation["payload"]
        assert isinstance(root_navigation_payload, Mapping)
        root_navigation_result = root_navigation_payload["result"]
        assert isinstance(root_navigation_result, Mapping)

        self.assertEqual(command["operation"], "session.tree.read")
        self.assertEqual(receipt_result["leaf_id"], "entry-2")
        self.assertIsInstance(receipt_result["nodes"], tuple)
        self.assertIsNone(root_navigation_result["current_leaf_id"])
        with self.assertRaises(TypeError):
            command["payload"]["continuation_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            receipt_result["nodes"][0]["kind"] = "changed"  # type: ignore[index]
        command_source["command_id"] = "changed"
        self.assertEqual(command["command_id"], "context-command-1")

    def test_all_command_payload_unions_are_exact(self) -> None:
        budget = {
            "controller_tokens": 100,
            "application_tokens": 0,
            "child_tokens": 0,
            "aggregate_tokens": 100,
            "cost_micros": 50,
            "deadline_ms": 1000,
        }
        cases = {
            "session.attachment.bind": {
                "input_id": "input-1",
                "attachment_id": "attachment-1",
                "body_ref": "body-ref-1",
                "media_type": "image/png",
                "sha256": SHA256_A,
                "size": 128,
            },
            "session.branch.summarize": {
                "continuation_id": "continuation-1",
                "entry_id": "entry-1",
                "instructions_ref": None,
                "budget": budget,
            },
            "session.clone": {"continuation_id": "continuation-1"},
            "session.compact": {
                "continuation_id": "continuation-1",
                "instructions_ref": "instructions-1",
                "budget": budget,
            },
            "session.continuation.delete": {"continuation_id": "continuation-1"},
            "session.continuation.resume": {"continuation_id": "continuation-1"},
            "session.describe": {},
            "session.fork": {
                "continuation_id": "continuation-1",
                "entry_id": "entry-1",
                "position": "at",
            },
            "session.label.set": {
                "continuation_id": "continuation-1",
                "entry_id": "entry-1",
                "label_ref": None,
            },
            "session.name.set": {"name_ref": "name-ref-1"},
            "session.tree.navigate": {
                "continuation_id": "continuation-1",
                "entry_id": "entry-1",
            },
            "session.tree.read": {"continuation_id": "continuation-1"},
        }
        self.assertEqual(frozenset(cases), SESSION_CONTEXT_OPERATIONS)
        for operation, payload in cases.items():
            with self.subTest(operation=operation):
                snapshot = validate_session_context_command(
                    _command(operation, payload)
                )
                self.assertEqual(snapshot["operation"], operation)
                with self.assertRaises(SessionContextProtocolError):
                    validate_session_context_command(
                        _command(operation, {**payload, "unexpected": "SENTINEL"})
                    )

    def test_success_receipts_have_closed_operation_results(self) -> None:
        usage = {
            "controller_tokens": 10,
            "application_tokens": 2,
            "child_tokens": 0,
            "aggregate_tokens": 12,
            "cost_micros": 3,
        }
        cases = {
            "session.attachment.bind": {
                "input_id": "input-1",
                "attachment_id": "attachment-1",
                "media_type": "image/png",
                "sha256": SHA256_A,
                "size": 128,
            },
            "session.branch.summarize": {
                "continuation_id": "continuation-1",
                "previous_leaf_id": "entry-1",
                "current_leaf_id": "entry-2",
                "summary_sha256": SHA256_A,
                "usage": usage,
            },
            "session.clone": {
                "source_continuation_id": "continuation-1",
                "new_continuation_id": "continuation-2",
                "active_leaf_id": "entry-2",
                "transition_sha256": SHA256_A,
            },
            "session.compact": {
                "continuation_id": "continuation-1",
                "covered_leaf_id": "entry-1",
                "before_context_tokens": 100,
                "after_context_tokens": 40,
                "summary_sha256": SHA256_A,
                "usage": usage,
            },
            "session.continuation.delete": {
                "continuation_id": "continuation-1",
                "deletion_sha256": SHA256_A,
            },
            "session.continuation.resume": {
                "previous_continuation_id": "continuation-1",
                "current_continuation_id": "continuation-2",
                "transition_sha256": SHA256_A,
            },
            "session.describe": {
                "continuation_id": "continuation-1",
                "status": "running",
                "context_tokens": 10,
                "turns": 1,
                "usage": usage,
                "name_sha256": None,
            },
            "session.fork": {
                "source_continuation_id": "continuation-1",
                "new_continuation_id": "continuation-2",
                "active_leaf_id": "entry-2",
                "transition_sha256": SHA256_A,
            },
            "session.label.set": {
                "continuation_id": "continuation-1",
                "entry_id": "entry-1",
                "label_sha256": None,
            },
            "session.name.set": {
                "continuation_id": "continuation-1",
                "name_sha256": SHA256_A,
            },
            "session.tree.navigate": {
                "continuation_id": "continuation-1",
                "previous_leaf_id": None,
                "current_leaf_id": None,
                "transition_sha256": SHA256_A,
            },
            "session.tree.read": {
                "continuation_id": "continuation-1",
                "nodes": [],
                "leaf_id": None,
            },
        }
        for operation, result in cases.items():
            with self.subTest(operation=operation):
                snapshot = validate_session_context_receipt(
                    _receipt(operation, result)
                )
                self.assertEqual(snapshot["operation"], operation)
                with self.assertRaises(SessionContextProtocolError):
                    validate_session_context_receipt(
                        _receipt(operation, {**result, "raw_output": "SENTINEL"})
                    )

    def test_non_success_receipts_cannot_carry_results(self) -> None:
        for status in ("rejected", "failed", "cancelled", "uncertain"):
            with self.subTest(status=status):
                validate_session_context_receipt(
                    _receipt("session.describe", None, status=status)
                )
                with self.assertRaises(SessionContextProtocolError):
                    validate_session_context_receipt(
                        _receipt(
                            "session.describe",
                            {"continuation_id": "continuation-1"},
                            status=status,
                        )
                    )

    def test_tree_nodes_and_attachment_metadata_fail_closed(self) -> None:
        tree = _fixture("valid-receipt-tree-read.json")
        result = tree["payload"]["result"]  # type: ignore[index]
        assert isinstance(result, dict)
        nodes = result["nodes"]
        assert isinstance(nodes, list)
        invalid_nodes = (
            [nodes[1], nodes[0]],
            [nodes[0], nodes[0]],
            [{**nodes[0], "parent_id": "entry-missing"}],
            [{**nodes[0], "token_count": -1}],
            [{**nodes[0], "kind": "provider-private"}],
            [
                {**nodes[0], "parent_id": "entry-2"},
                {**nodes[1], "parent_id": "entry-1"},
            ],
        )
        for values in invalid_nodes:
            with self.subTest(values=values), self.assertRaises(
                SessionContextProtocolError
            ):
                validate_session_context_receipt(
                    {**tree, "payload": {"evidence_ref": "evidence-1", "result": {**result, "nodes": values}}}
                )

        parent_after_child = [
            {**nodes[0], "parent_id": "entry-2"},
            {**nodes[1], "parent_id": None},
        ]
        validate_session_context_receipt(
            {
                **tree,
                "payload": {
                    "evidence_ref": "evidence-1",
                    "result": {**result, "nodes": parent_after_child},
                },
            }
        )

        validate_session_context_receipt(
            {
                **tree,
                "payload": {
                    "evidence_ref": "evidence-1",
                    "result": {**result, "leaf_id": None},
                },
            }
        )

        attachment = _command(
            "session.attachment.bind",
            {
                "input_id": "input-1",
                "attachment_id": "attachment-1",
                "body_ref": "body-ref-1",
                "media_type": "image/png",
                "sha256": SHA256_A,
                "size": 1,
            },
        )
        for field, value in (
            ("media_type", "not-a-media-type"),
            ("sha256", "A" * 64),
            ("size", -1),
        ):
            source_payload = attachment["payload"]
            assert isinstance(source_payload, dict)
            payload = dict(source_payload)
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(
                SessionContextProtocolError
            ):
                validate_session_context_command({**attachment, "payload": payload})

    def test_all_numeric_fields_are_javascript_safe_integers(self) -> None:
        oversized = MAX_SAFE_INTEGER + 1
        base = _fixture("valid-command-tree-read.json")
        with self.assertRaises(SessionContextProtocolError):
            validate_session_context_command({**base, "generation": oversized})

        budget = {
            "controller_tokens": oversized,
            "application_tokens": 0,
            "child_tokens": 0,
            "aggregate_tokens": 0,
            "cost_micros": 0,
            "deadline_ms": 1,
        }
        with self.assertRaises(SessionContextProtocolError):
            validate_session_context_command(
                _command(
                    "session.compact",
                    {
                        "continuation_id": "continuation-1",
                        "instructions_ref": None,
                        "budget": budget,
                    },
                )
            )

        tree = _fixture("valid-receipt-tree-read.json")
        payload = tree["payload"]
        assert isinstance(payload, dict)
        result = payload["result"]
        assert isinstance(result, dict)
        nodes = result["nodes"]
        assert isinstance(nodes, list)
        with self.assertRaises(SessionContextProtocolError):
            validate_session_context_receipt(
                {
                    **tree,
                    "payload": {
                        "evidence_ref": "evidence-1",
                        "result": {
                            **result,
                            "nodes": [{**nodes[0], "token_count": oversized}],
                            "leaf_id": "entry-1",
                        },
                    },
                }
            )

    def test_dataclasses_validate_copy_and_redact_repr(self) -> None:
        command = SessionContextCommand.from_mapping(
            _fixture("valid-command-tree-read.json")
        )
        receipt = SessionContextReceipt.from_mapping(
            _fixture("valid-receipt-tree-read.json")
        )
        self.assertEqual(command.to_mapping()["operation"], "session.tree.read")
        self.assertEqual(receipt.to_mapping()["status"], "succeeded")
        self.assertNotIn("entry-2", repr(receipt))
        self.assertNotIn("continuation-1", repr(command))

    def test_invalid_fixtures_and_errors_never_render_private_values(self) -> None:
        cases = (
            ("invalid-command-private-path.json", validate_session_context_command),
            ("invalid-receipt-provider-payload.json", validate_session_context_receipt),
            (
                "invalid-receipt-tree-navigate-current-leaf.json",
                validate_session_context_receipt,
            ),
        )
        for name, validator in cases:
            with self.subTest(name=name), self.assertRaises(
                SessionContextProtocolError
            ) as raised:
                validator(_fixture(name))
            rendered = str(raised.exception)
            self.assertNotIn("SENTINEL_PRIVATE", rendered)
            self.assertNotIn("SENTINEL_SECRET", rendered)

    def test_wire_schemas_are_closed_and_cover_every_operation(self) -> None:
        command_schema = json.loads(COMMAND_SCHEMA.read_text(encoding="utf-8"))
        receipt_schema = json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(command_schema["additionalProperties"])
        self.assertFalse(receipt_schema["additionalProperties"])
        self.assertEqual(
            set(command_schema["properties"]["operation"]["enum"]),
            SESSION_CONTEXT_OPERATIONS,
        )
        self.assertEqual(
            set(receipt_schema["properties"]["operation"]["enum"]),
            SESSION_CONTEXT_OPERATIONS,
        )
        self.assertEqual(len(command_schema["allOf"][0]["oneOf"]), 12)
        self.assertEqual(len(receipt_schema["allOf"][0]["oneOf"]), 13)
        rendered = json.dumps((command_schema, receipt_schema), sort_keys=True)
        for forbidden in ("credentials", "environment", "provider_payload", "raw_output", "sessionPath"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'"{forbidden}"', rendered)


if __name__ == "__main__":
    unittest.main()
