from __future__ import annotations

import asyncio
from hashlib import sha256
import unittest


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"


def _digest(value: object) -> str:
    import json

    return (
        "sha256:"
        + sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


class _Provider:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    async def __call__(self, _: bytes) -> bytes:
        self.calls += 1
        self.events.append("provider")
        return b"{}"

    def terminal_usage(self) -> object:
        self.events.append("usage")
        return type(
            "Usage", (), {"input_tokens": 1, "output_tokens": 1, "cost_microunits": 1}
        )()

    async def close(self) -> None:
        self.events.append("provider.close")


class _Worker:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.cells = 0

    async def acquire(self) -> None:
        self.events.append("acquire")

    async def initial_snapshot(self) -> bytes:
        self.events.append("snapshot0")
        return _INITIAL

    async def execute_cell(self, _: str) -> dict[str, object]:
        self.cells += 1
        self.events.append("cell")
        return {
            "cell_count": self.cells,
            "kernel_generation": 1,
            "probe_count": self.cells * 6,
        }

    async def finish(self) -> object:
        self.events.append("finish")
        return type(
            "Completion",
            (),
            {"kernel_generation": 1, "cell_count": 2, "probe_count": 12},
        )()

    async def snapshot(self) -> bytes:
        self.events.append("snapshot1")
        return _FINAL

    async def cleanup(self) -> None:
        self.events.append("cleanup")


class _Gateway:
    def __init__(
        self,
        events: list[str],
        *,
        recover_ok: bool = True,
        replay_complete: bool = True,
        compact_ok: bool = True,
    ) -> None:
        self.events, self.recover_ok = events, recover_ok
        self.replay_complete, self.compact_ok = replay_complete, compact_ok
        self.model = self.tool = None
        self.compacts = self.prompts = 0
        self.candidate = {
            "active_session_id": "active",
            "session_id": "native",
            "initial_attach_cursor": {"generation": "g", "sequence": 3},
            "cursor": {"generation": "g", "sequence": 7},
            "transcript_sha256": _digest("transcript"),
            "tree_sha256": _digest("tree"),
            "artifact_sha256": _digest("artifact"),
        }

    def bind(self, *, model_hook: object, tool_hook: object) -> None:
        self.model, self.tool = model_hook, tool_hook

    async def open(self, **_: object) -> None:
        self.events.append("open")

    async def prompt(self, _: str) -> dict[str, object]:
        self.prompts += 1
        self.events.append("prompt" + str(self.prompts))
        for index in range(2 if self.prompts == 1 else 3):
            await self.model({"turn": index})  # type: ignore[misc]
        await self.tool({"tool_call_id": "call-" + str(self.prompts), "code": "x"})  # type: ignore[misc]
        if self.prompts == 1:
            return {"lifecycle": "completed", "checkpoint_candidate": self.candidate}
        return {
            "lifecycle": "completed",
            "model_callback_count": 5,
            "tool_callback_count": 2,
        }

    async def recover(self) -> dict[str, object]:
        self.events.append("recover")
        if not self.recover_ok:
            return {
                "active_session_id": "wrong",
                "session_id": "native",
                "from_cursor": self.candidate["cursor"],
                "to_cursor": self.candidate["cursor"],
                "snapshot_cursor": self.candidate["cursor"],
                "replay_status": "complete" if self.replay_complete else "partial",
            }
        return {
            "active_session_id": "active",
            "session_id": "native",
            "from_cursor": self.candidate["cursor"],
            "to_cursor": self.candidate["cursor"],
            "snapshot_cursor": self.candidate["cursor"],
            "replay_status": "complete" if self.replay_complete else "partial",
        }

    async def compact(self) -> dict[str, object]:
        self.compacts += 1
        self.events.append("compact")
        return {
            "compact_called": True,
            "succeeded": True,
            "start_count": 1,
            "end_count": 1,
            "new_entry_count": 1 if self.compact_ok else 2,
            "active_path_sha256": _digest("active-path"),
            "first_kept_entry_id_sha256": _digest("first-kept"),
            "tokens_before": 3,
        }

    async def close(self) -> None:
        self.events.append("gateway.close")

    async def cancel(self) -> object:
        self.events.append("gateway.cancel")
        return {"lifecycle": "cancelled"}


class TestPrimeP4DevelopmentHost(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_provider_body_preserves_non_ascii_utf8(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1b_development_sdk_provider as provider_contract,
        )
        from asterion.applications.prime_agent.operator.p4_development_host import (
            _canonical,
        )

        model = {
            "api": "asterion-p4-development",
            "baseUrl": "http://127.0.0.1:0",
            "contextWindow": 16_384,
            "cost": {"cacheRead": 0, "cacheWrite": 0, "input": 0, "output": 0},
            "id": "p4-development",
            "input": ["text"],
            "maxTokens": 1_024,
            "name": "p4-development",
            "provider": "asterion-p4-development",
            "reasoning": False,
        }
        payload = {
            "context": {
                "messages": [{"content": "你好", "role": "user"}],
                "systemPrompt": "系统提示",
                "tools": [
                    {
                        "description": "IPython bridge",
                        "name": "ipython",
                        "parameters": {
                            "properties": {"code": {"type": "string"}},
                            "required": ["code"],
                            "type": "object",
                        },
                    }
                ],
            },
            "model": model,
            "options": {
                "apiKey": "in-memory-development-provider",
                "maxRetries": 0,
                "maxRetryDelayMs": 60_000,
                "model": model,
                "serviceTier": "default",
                "sessionId": "session-1",
                "signal": {},
                "toolExecution": "parallel",
                "transport": "auto",
            },
        }

        body = _canonical(payload)  # noqa: SLF001
        self.assertIn("系统提示".encode("utf-8"), body)
        provider_contract._decode_request(body, 0, [])  # noqa: SLF001

    async def test_runs_the_fixed_recover_compact_continuity_flow(self) -> None:
        from asterion.applications.prime_agent.operator.p4_development_host import (
            run_p4_development_lifecycle,
        )

        events: list[str] = []
        trace = await run_p4_development_lifecycle(
            gateway=_Gateway(events),
            provider=_Provider(events),
            worker=_Worker(events),
            run_id="run",
            session_id="session",
            prime_source_root="/prime",
            workspace="/work",
        )
        self.assertRegex(trace.trace_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertNotIn("active", repr(trace))
        self.assertEqual(
            events,
            [
                "acquire",
                "snapshot0",
                "open",
                "prompt1",
                "provider",
                "provider",
                "cell",
                "recover",
                "compact",
                "prompt2",
                "provider",
                "provider",
                "provider",
                "cell",
                "gateway.close",
                "usage",
                "finish",
                "snapshot1",
                "provider.close",
                "cleanup",
            ],
        )

    async def test_recover_identity_failure_does_not_compact_or_send_second_prompt(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p4_development_host import (
            PrimeP4DevelopmentHostError,
            run_p4_development_lifecycle,
        )

        events: list[str] = []
        gateway = _Gateway(events, recover_ok=False)
        with self.assertRaises(PrimeP4DevelopmentHostError):
            await run_p4_development_lifecycle(
                gateway=gateway,
                provider=_Provider(events),
                worker=_Worker(events),
                run_id="run",
                session_id="session",
                prime_source_root="/prime",
                workspace="/work",
            )
        self.assertEqual(gateway.compacts, 0)
        self.assertEqual(gateway.prompts, 1)
        self.assertIn("cleanup", events)

    async def test_incomplete_replay_or_nonexact_compaction_never_reaches_prompt_two(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p4_development_host import (
            PrimeP4DevelopmentHostError,
            run_p4_development_lifecycle,
        )

        for gateway in (
            _Gateway([], replay_complete=False),
            _Gateway([], compact_ok=False),
        ):
            with self.subTest(gateway=gateway):
                with self.assertRaises(PrimeP4DevelopmentHostError):
                    await run_p4_development_lifecycle(
                        gateway=gateway,
                        provider=_Provider(gateway.events),
                        worker=_Worker(gateway.events),
                        run_id="run",
                        session_id="session",
                        prime_source_root="/prime",
                        workspace="/work",
                    )
                self.assertEqual(gateway.prompts, 1)

    async def test_cancellation_waits_for_cleanup_and_does_not_return_a_trace(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p4_development_host import (
            run_p4_development_lifecycle,
        )

        events: list[str] = []

        class CancelGateway(_Gateway):
            async def recover(self) -> dict[str, object]:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await run_p4_development_lifecycle(
                gateway=CancelGateway(events),
                provider=_Provider(events),
                worker=_Worker(events),
                run_id="run",
                session_id="session",
                prime_source_root="/prime",
                workspace="/work",
            )
        self.assertIn("cleanup", events)
