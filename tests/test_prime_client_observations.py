from __future__ import annotations

import unittest
import asyncio
import base64
import hashlib
from collections.abc import AsyncIterator, Mapping
from typing import cast

from asterion.client.protocol import ClientCursor
from asterion.control.providers.prime.client import (
    PrimeControlError,
    PrimeControlPlaneClient,
)
from asterion.control.providers.prime.process import _event_iterator
from asterion.control.providers.prime.process import PrimeSidecarProcess


class _Resolver:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        del reference, max_bytes
        return "private"


class _Process:
    def __init__(self) -> None:
        self.event_requests: list[Mapping[str, object]] = []
        self.client_value_kind = "message"
        self.client_value_media_type = "text/plain"
        self.observations = [
            {
                "observation_id": "observation-1",
                "active_session_id": "session-1",
                "generation": 1,
                "source_sequence": 1,
                "emitted_at": "2026-08-10T03:00:01Z",
                "kind": "message.available",
                "payload": {
                    "content_ref": "private:00000000-0000-4000-8000-000000000001",
                    "media_type": "text/plain",
                    "message_id": "message-1",
                    "role": "assistant",
                    "sha256": hashlib.sha256(b"SENTINEL_BODY").hexdigest(),
                    "size": 13,
                },
            },
            {
                "observation_id": "observation-2",
                "active_session_id": "session-1",
                "generation": 1,
                "source_sequence": 2,
                "emitted_at": "2026-08-10T03:00:02Z",
                "kind": "commands.changed",
                "payload": {"commands": [], "revision": 1},
            },
        ]

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        if envelope["type"] != "client_value_read":
            raise AssertionError(envelope)
        return {
            "protocol": envelope["protocol"],
            "id": envelope["id"],
            "type": "client_value",
            "descriptor": {
                "reference": "private:00000000-0000-4000-8000-000000000001",
                "kind": self.client_value_kind,
                "media_type": self.client_value_media_type,
                "size": 13,
                "sha256": hashlib.sha256(b"SENTINEL_BODY").hexdigest(),
            },
            "body_base64": base64.b64encode(b"SENTINEL_BODY").decode("ascii"),
        }

    def events(self, envelope: Mapping[str, object]) -> AsyncIterator[Mapping[str, object]]:
        self.event_requests.append(envelope)
        cursor = envelope["cursor"]
        if cursor is not None and not isinstance(cursor, Mapping):
            raise AssertionError(cursor)
        start = 0 if cursor is None else int(cursor["sequence"])

        async def iterate() -> AsyncIterator[Mapping[str, object]]:
            for observation in self.observations[start:]:
                yield observation

        return iterate()

    async def close(self) -> None:
        return None


class _PagedProcess(_Process):
    def __init__(self, pages: Mapping[tuple[int, int] | None, Mapping[str, object]]) -> None:
        super().__init__()
        self._pages = pages
        self.client_value_reads = 0

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        if envelope["type"] == "client_value_read":
            self.client_value_reads += 1
            return await super().request(envelope)
        if envelope["type"] != "client_observations":
            raise AssertionError(envelope)
        cursor = envelope["cursor"]
        if cursor is None:
            key = None
        elif isinstance(cursor, Mapping):
            key = (int(cursor["generation"]), int(cursor["sequence"]))
        else:
            raise AssertionError(cursor)
        return self._pages[key]

    def events(self, envelope: Mapping[str, object]) -> AsyncIterator[Mapping[str, object]]:
        self.event_requests.append(envelope)
        return _event_iterator(cast(PrimeSidecarProcess, self), envelope)


class TestPrimeClientObservations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.process = _Process()
        self.client = PrimeControlPlaneClient(
            process=self.process,
            private_content=_Resolver(),
        )

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_prime_observations_are_body_free_and_replayable(self) -> None:
        observations = [item async for item in self.client.client_observations()]
        replay = [
            item
            async for item in self.client.client_observations(ClientCursor(1, 1))
        ]
        self.assertEqual(replay, observations[1:])
        self.assertNotIn("SENTINEL_BODY", repr(observations))
        self.assertEqual(self.process.event_requests[0]["type"], "client_observations")

    async def test_hostile_observation_transport_is_redacted(self) -> None:
        self.process.observations[0] = {
            **self.process.observations[0],
            "payload": {"content_ref": "SENTINEL_BODY"},
        }
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$") as raised:
            _ = [item async for item in self.client.client_observations()]
        self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    async def test_private_read_rechecks_observed_descriptor(self) -> None:
        observations = [item async for item in self.client.client_observations()]
        reference = observations[0].payload["content_ref"]
        if not isinstance(reference, str):
            self.fail("content reference is invalid")
        self.assertEqual(self.client.describe(reference).size, 13)
        self.assertEqual(await self.client.read(reference, max_bytes=13), b"SENTINEL_BODY")

    async def test_extension_payload_reference_is_readable(self) -> None:
        self.process.client_value_kind = "extension-ui"
        self.process.client_value_media_type = "application/json"
        self.process.observations = [{
            "observation_id": "observation-1", "active_session_id": "session-1",
            "generation": 1, "source_sequence": 1, "emitted_at": "2026-08-10T03:00:01Z",
            "kind": "extension-ui.requested",
            "payload": {"deadline_ms": 1, "method": "extension-1", "payload_ref": "private:00000000-0000-4000-8000-000000000001", "request_id": "request-1"},
        }]
        observations = [item async for item in self.client.client_observations()]
        reference = observations[0].payload["payload_ref"]
        if not isinstance(reference, str):
            self.fail("payload reference is invalid")
        self.assertEqual(self.client.describe(reference).kind, "extension-ui")

    async def test_extension_payload_descriptor_requires_json_and_redacts_body(self) -> None:
        self.process.client_value_kind = "extension-ui"
        self.process.client_value_media_type = "text/plain"
        self.process.observations = [{
            "observation_id": "observation-1", "active_session_id": "session-1",
            "generation": 1, "source_sequence": 1, "emitted_at": "2026-08-10T03:00:01Z",
            "kind": "extension-ui.requested",
            "payload": {"deadline_ms": 1, "method": "extension-1", "payload_ref": "private:00000000-0000-4000-8000-000000000001", "request_id": "request-1"},
        }]
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$") as raised:
            _ = [item async for item in self.client.client_observations()]
        self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    async def test_client_observation_cancellation_is_redacted(self) -> None:
        class CancelProcess(_Process):
            def events(self, envelope: Mapping[str, object]) -> AsyncIterator[Mapping[str, object]]:
                async def iterate() -> AsyncIterator[Mapping[str, object]]:
                    raise asyncio.CancelledError()
                    yield envelope
                return iterate()
        client = PrimeControlPlaneClient(process=CancelProcess(), private_content=_Resolver())
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$"):
            _ = [item async for item in client.client_observations()]
        await client.close()

    async def test_malformed_page_cursor_has_no_descriptor_side_effects(self) -> None:
        extension_observation = {
            "observation_id": "observation-1", "active_session_id": "session-1",
            "generation": 1, "source_sequence": 1,
            "emitted_at": "2026-08-10T03:00:01Z",
            "kind": "extension-ui.requested",
            "payload": {
                "deadline_ms": 1, "method": "extension-1",
                "payload_ref": "private:00000000-0000-4000-8000-000000000001",
                "request_id": "request-1",
            },
        }
        process = _PagedProcess({
            None: {"observations": [extension_observation], "next_cursor": {"generation": 1}},
        })
        process.client_value_kind = "extension-ui"
        process.client_value_media_type = "application/json"
        client = PrimeControlPlaneClient(process=process, private_content=_Resolver())
        yielded = []
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$"):
            async for observation in client.client_observations():
                yielded.append(observation)
        self.assertEqual(yielded, [])
        self.assertEqual(process.client_value_reads, 0)
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$"):
            client.describe("private:00000000-0000-4000-8000-000000000001")
        await client.close()

    async def test_initial_replay_generation_is_pinned_before_descriptor_side_effects(self) -> None:
        extension_observation = {
            "observation_id": "observation-2", "active_session_id": "session-1",
            "generation": 2, "source_sequence": 2,
            "emitted_at": "2026-08-10T03:00:02Z",
            "kind": "extension-ui.requested",
            "payload": {
                "deadline_ms": 1, "method": "extension-1",
                "payload_ref": "private:00000000-0000-4000-8000-000000000001",
                "request_id": "request-1",
            },
        }
        process = _PagedProcess({
            None: {
                "observations": [{
                    "observation_id": "observation-1", "active_session_id": "session-1",
                    "generation": 1, "source_sequence": 1,
                    "emitted_at": "2026-08-10T03:00:01Z",
                    "kind": "commands.changed", "payload": {"commands": [], "revision": 1},
                }],
                "next_cursor": {"generation": 1, "sequence": 1},
            },
            (1, 1): {"observations": [extension_observation], "next_cursor": None},
        })
        process.client_value_kind = "extension-ui"
        process.client_value_media_type = "application/json"
        client = PrimeControlPlaneClient(process=process, private_content=_Resolver())
        yielded = []
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$"):
            async for observation in client.client_observations():
                yielded.append(observation)
        self.assertEqual([observation.source_sequence for observation in yielded], [1])
        self.assertEqual(process.client_value_reads, 0)
        with self.assertRaisesRegex(PrimeControlError, "^Prime control operation failed$"):
            client.describe("private:00000000-0000-4000-8000-000000000001")
        await client.close()
