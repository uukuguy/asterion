"""Focused development-only P1 Docker/model host wiring checks."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerTokenUsage,
)
from asterion.services.restricted_worker import RestrictedWorkerLease
from tests.test_prime_docker_worker import _IMAGE_DIGEST, _Transport


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"


class _Provider:
    def __init__(self) -> None:
        self.requests: list[bytes] = []

    async def __call__(self, body: bytes) -> bytes:
        self.requests.append(body)
        return json.dumps(
            {
                "content": [{"text": "done", "type": "text"}],
                "role": "assistant",
                "stopReason": "stop",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        return PrimeModelBrokerTokenUsage(3, 4, 5)


class _Gateway:
    instances: list["_Gateway"] = []

    def __init__(self, *, model_hook: object, tool_hook: object, **kwargs: object) -> None:
        self.calls: list[str] = ["constructed"]
        self.kwargs = kwargs
        self.model_hook = model_hook
        self.tool_hook = tool_hook
        type(self).instances.append(self)

    async def open(self, **kwargs: object) -> None:
        self.calls.append("open")
        self.open_kwargs = kwargs

    async def prompt(self, prompt: str) -> object:
        self.calls.append("prompt")
        self.prompt_value = prompt
        first = await self.model_hook(  # type: ignore[operator]
            {
                "context": {"messages": [{"content": "verify", "role": "user"}]},
                "model": {"api": "asterion-p1-development", "id": "p1-development", "provider": "asterion-development"},
                "options": {},
            }
        )
        self.tool_result = await self.tool_hook(  # type: ignore[operator]
            {"code": "print(42)", "tool_call_id": "call-1"}
        )
        second = await self.model_hook(  # type: ignore[operator]
            {
                "context": {
                    "messages": [
                        {"content": "verify", "role": "user"},
                        first,
                        self.tool_result,
                    ]
                },
                "model": {"api": "asterion-p1-development", "id": "p1-development", "provider": "asterion-development"},
                "options": {},
            }
        )
        self.second = second
        return {"lifecycle": "completed"}

    async def close(self) -> None:
        self.calls.append("close")


class TestPrimeP1DevelopmentHost(unittest.IsolatedAsyncioTestCase):
    async def test_development_run_waits_for_request_then_snapshots_and_cleans_up(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_host as subject,
        )

        transport = _Transport()
        transport.lease = RestrictedWorkerLease(
            "worker-1", "prime.ipython-coding", "prime-p1-development-" + "a" * 32,
            subject._CHALLENGE_DIGEST, subject.PRIME_IPYTHON_CODING_WORKLOAD_DIGEST,  # noqa: SLF001
        )
        snapshots = iter((_INITIAL, _FINAL))
        transport.closed = False  # type: ignore[attr-defined]

        async def snapshot_solution(container_id: str, *, control: object) -> bytes:
            del control
            transport.assert_container_id(container_id)
            transport.calls.append("snapshot_solution")
            return next(snapshots)

        transport.snapshot_solution = snapshot_solution  # type: ignore[method-assign]
        transport.close = lambda: setattr(transport, "closed", True)  # type: ignore[attr-defined]
        provider = _Provider()
        _Gateway.instances.clear()
        with (
            patch.object(subject, "uuid4", return_value=SimpleNamespace(hex="a" * 32)),
            patch.object(subject, "DockerCliEngineTransport", return_value=transport),
            patch.object(subject, "PrimeP1DevelopmentGateway", _Gateway),
            patch.object(subject, "create_prime_p1_development_sdk_provider", return_value=provider),
        ):
            trace = await subject.run_prime_p1_development(
                docker_executable="/operator/docker",
                socket_path="/operator/docker.sock",
                seccomp_profile_fd=9,
                platform=ImagePlatformDescriptor("linux", "amd64", None),
                image_digest=_IMAGE_DIGEST,
                operator_config={"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                node_bin="/operator/node",
                entrypoint="/operator/p1-development-main.js",
                prime_source_root="/operator/prime-agent",
            )

        self.assertEqual((trace.scope, trace.promotion), ("p1-a-development", "unpromoted"))
        self.assertRegex(trace.trace.evidence_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertLess(
            transport.calls.index("model_request"), transport.calls.index("snapshot_solution")
        )
        self.assertEqual(transport.calls.count("snapshot_solution"), 2)
        self.assertEqual(transport.calls.count("model_response"), 1)
        self.assertEqual(transport.calls[-2:], ["force_remove", "assert_absent"])
        self.assertTrue(transport.closed)  # type: ignore[attr-defined]
        gateway = _Gateway.instances[0]
        self.assertEqual(gateway.calls, ["constructed", "open", "prompt", "close"])
        self.assertEqual(gateway.open_kwargs["prime_source_root"], "/operator/prime-agent")
        self.assertEqual(gateway.tool_result, {"content": [{"text": "IPython cell completed", "type": "text"}], "details": {}, "isError": False})
        self.assertEqual(len(provider.requests), 2)
        self.assertTrue(all(json.loads(body) for body in provider.requests))
