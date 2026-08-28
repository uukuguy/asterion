from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.operation.protocol import EFFECT_COUNTERS, OperationReceipt, OperationTransaction
from asterion.operation.services import OperationReconciliationContext
from asterion.operation.settings import (
    KeybindingRecord,
    OperationServiceError,
    PreferenceRecord,
    PreferenceStore,
    SettingsOperationService,
    validate_settings_keybindings_request,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "operation" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _settings_request(
    scope: str,
    name: str,
    value: object,
    **overrides: object,
) -> dict[str, object]:
    kind = "keybinding" if name.startswith("app.") else "setting"
    request: dict[str, object] = {
        "type": kind,
        "name": name,
        "scope": scope,
        "value": value,
    }
    if scope == "project":
        request["project_id"] = "project-1"
    request.update(overrides)
    return request


def _settings_transaction(
    operation_id: str,
    *,
    scope: str = "global",
    key: str = "theme",
    value: object = "dark",
    feature_id: str = "operation.settings-keybindings",
    request_kind: str = "operation.settings-keybindings-request",
    purpose: str = "operation.settings-keybindings",
    media_type: str = "application/json",
    byte_count: int = 512,
) -> OperationTransaction:
    del scope, key, value
    return OperationTransaction.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "operation_id": operation_id,
            "request": {
                "protocol": "asterion.operation/v1",
                "request_kind": request_kind,
                "request_ref": f"request-{operation_id}",
                "request_sha256": "a" * 64,
                "media_type": media_type,
                "byte_count": byte_count,
                "purpose": purpose,
                "client_id": "client-1",
                "session_id": "session-1",
                "generation": 1,
                "authority_revision": 1,
            },
            "session_id": "session-1",
            "client_id": "client-1",
            "generation": 1,
            "authority_revision": 1,
            "authority_id": "authority-1",
            "idempotency_key": f"key-{operation_id}",
            "feature_id": feature_id,
            "requested_at": "2026-08-10T15:00:00Z",
        }
    )


def _settings_service() -> tuple[SettingsOperationService, PreferenceStore]:
    store = PreferenceStore()
    return SettingsOperationService(store=store), store


class TestSettingsKeybindingsRequest(unittest.TestCase):
    def test_request_is_closed_immutable_and_has_exact_scopes(self) -> None:
        request = validate_settings_keybindings_request(
            _fixture("valid-settings-keybindings-request.json")
        )
        self.assertEqual(set(request), {"type", "name", "scope", "value"})
        with self.assertRaises(TypeError):
            request["scope"] = "project"  # type: ignore[index]
        with self.assertRaises(OperationServiceError) as raised:
            validate_settings_keybindings_request(
                _fixture("invalid-settings-keybindings-secret.json")
            )
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_keybindings_are_typed_and_allowlisted(self) -> None:
        record = KeybindingRecord.from_request(
            validate_settings_keybindings_request(
                _settings_request("global", "app.session.new", "Ctrl+N")
            )
        )
        self.assertEqual((record.type, record.name, record.value), ("keybinding", "app.session.new", "Ctrl+N"))
        for request in (
            _settings_request("global", "app.session.new", "Ctrl+N", type="setting"),
            _settings_request("global", "theme", "Ctrl+N", type="keybinding"),
            _settings_request("global", "app.cancel", "Ctrl+N"),
            _settings_request("global", "keybinding.command_palette", "Ctrl+P"),
            _settings_request("global", "ui.theme", "dark"),
            _settings_request("global", "app.session.new", "not-a-key-chord"),
        ):
            with self.subTest(request=request):
                with self.assertRaises(OperationServiceError):
                    validate_settings_keybindings_request(request)


class TestSettingsOperationService(unittest.IsolatedAsyncioTestCase):
    async def test_project_preference_overrides_global_but_cannot_admit_operation(self) -> None:
        service, store = _settings_service()
        await service.execute(
            _settings_transaction("settings-global", scope="global", key="theme", value="dark"),
            _settings_request("global", "theme", "dark"),
        )
        await service.execute(
            _settings_transaction("settings-project", scope="project", key="theme", value="light"),
            _settings_request("project", "theme", "light"),
        )
        resolved = store.resolve("theme", project_id="project-1")
        assert resolved is not None
        self.assertEqual(resolved.value, "light")
        self.assertFalse(resolved.is_authority)
        self.assertEqual(store.last_receipt.revision if store.last_receipt else None, 2)

    async def test_sequential_writes_bind_the_exact_next_store_revision(self) -> None:
        service, store = _settings_service()
        self.assertEqual(store.next_revision(), 1)

        await service.execute(
            _settings_transaction("revision-global"),
            _settings_request("global", "theme", "dark"),
        )
        self.assertEqual(store.last_receipt.revision if store.last_receipt else None, 1)
        self.assertEqual(store.next_revision(), 2)

        await service.execute(
            _settings_transaction("revision-project"),
            _settings_request("project", "theme", "light"),
        )
        self.assertEqual(store.last_receipt.revision if store.last_receipt else None, 2)
        self.assertEqual(store.next_revision(), 3)
        resolved = store.resolve("theme", project_id="project-1")
        assert resolved is not None
        self.assertEqual((resolved.value, resolved.revision), ("light", 2))

    async def test_secret_key_free_text_and_unknown_key_are_rejected_without_leakage(self) -> None:
        for request in (
            _settings_request("global", "app.new_session", "SENTINEL_SECRET"),
            _settings_request("global", "theme", "SENTINEL_SECRET"),
            _settings_request("global", "token.theme", "dark"),
            _settings_request("global", "theme", "dark", body="SENTINEL_SECRET"),
        ):
            with self.subTest(request=request):
                service, store = _settings_service()
                with self.assertRaises(OperationServiceError) as raised:
                    await service.execute(_settings_transaction("bad"), request)
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                self.assertIsNone(store.resolve("theme", project_id="project-1"))

    async def test_receipt_is_public_safe_and_store_receipt_has_only_preference_metadata(self) -> None:
        service, store = _settings_service()
        transaction = _settings_transaction("settings-receipt")

        receipt = await service.execute(transaction, _settings_request("global", "theme", "dark"))

        self.assertIsInstance(receipt, OperationReceipt)
        self.assertEqual(receipt.effect_counts, {key: 0 for key in EFFECT_COUNTERS})
        self.assertNotIn("dark", repr(receipt))
        stored = store.last_receipt
        assert stored is not None
        self.assertEqual(
            set(stored.to_mapping()), {"type", "name", "scope", "value_digest", "revision"}
        )
        self.assertNotIn("dark", repr(stored))

    async def test_self_attesting_store_subclass_is_rejected_before_calls_or_mutation(self) -> None:
        class SelfAttestingStore(PreferenceStore):
            def __init__(self) -> None:
                super().__init__()
                self.calls: list[str] = []

            def next_revision(self) -> int:
                self.calls.append("next_revision")
                return 1_000_000

            def put(self, record: PreferenceRecord):
                del record
                self.calls.append("put")
                self._revision = 1_000_000
                raise RuntimeError("SENTINEL_SECRET")

            def snapshot(self, record: PreferenceRecord):
                del record
                self.calls.append("snapshot")
                return None

        store = SelfAttestingStore()
        with self.assertRaises(OperationServiceError) as raised:
            SettingsOperationService(store=store)
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
        self.assertEqual(store.calls, [])
        self.assertEqual(store.records, ())
        self.assertEqual(store._revision, 0)

    async def test_wrong_binding_and_reconciliation_fail_before_store_mutation(self) -> None:
        service, store = _settings_service()
        request = _settings_request("global", "theme", "dark")
        for transaction in (
            _settings_transaction("wrong-feature", feature_id="operation.auth"),
            _settings_transaction("wrong-kind", request_kind="operation.auth-request"),
            _settings_transaction("wrong-purpose", purpose="operation.auth"),
            _settings_transaction("wrong-media", media_type="text/plain"),
            _settings_transaction("wrong-bytes", byte_count=4097),
        ):
            with self.subTest(transaction=transaction.operation_id):
                with self.assertRaises(OperationServiceError):
                    await service.execute(transaction, request)
        transaction = _settings_transaction("reconcile")
        with self.assertRaises(OperationServiceError):
            await service.reconcile(
                transaction,
                request,
                OperationReconciliationContext("other-operation", 1, 1),
            )
        self.assertIsNone(store.last_receipt)

    async def test_records_are_immutable_and_global_only_applies_without_exact_project_value(self) -> None:
        service, store = _settings_service()
        await service.execute(_settings_transaction("global"), _settings_request("global", "theme", "dark"))
        global_record = store.resolve("theme")
        assert isinstance(global_record, PreferenceRecord)
        self.assertEqual(global_record.value, "dark")
        self.assertIsNone(store.resolve("theme", project_id="project-1", inherit_global=False))
        with self.assertRaises((AttributeError, TypeError)):
            global_record.value = "light"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
