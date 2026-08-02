from __future__ import annotations

import asyncio
import gc
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from asterion.adapters.pi import map_pi_capabilities
from asterion.capabilities.dci.implementation.services import create_local_corpus_service_factory
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import ProtocolError, validate_event_stream
from asterion.runtime.working_directory import ProcessWorkingDirectory
from asterion.runtimes.pi import PiRuntimeClient
from asterion.services.registry import HostServiceFactoryContext


SUCCESS_SCRIPT = r'''
import json
import sys

request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({
    "type": "message_update",
    "assistantMessageEvent": {"type": "text_delta", "delta": "Pudding Lane"}
}), flush=True)
print(json.dumps({
    "type": "message_end",
    "message": {
        "role": "assistant",
        "stopReason": "stop",
        "usage": {"input": 1, "output": 2},
        "content": [{"type": "text", "text": "Pudding Lane"}]
    }
}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

INVALID_JSON_SCRIPT = r'''
import sys
sys.stdin.readline()
print("SECRET-NOT-JSON", flush=True)
'''

EARLY_EOF_SCRIPT = r'''
import json
import sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
'''

SLOW_SCRIPT = r'''
import sys
import time
sys.stdin.readline()
time.sleep(5)
'''

ERROR_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "SECRET-PROVIDER-FAILURE"}}), flush=True)
print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "usage": {"input": 1, "output": 1}}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

RETRY_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "discarded"}}), flush=True)
print(json.dumps({"type": "agent_end", "willRetry": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "recovered answer"}}), flush=True)
print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "usage": {"input": 1, "output": 1}}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

OVER_TURN_SCRIPT = r'''
import json, sys, time
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
time.sleep(5)
'''

RECOVERED_FINAL_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "usage": {"input": 1, "output": 1}, "content": [{"type": "text", "text": "recovered final"}]}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

EMPTY_FINAL_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "usage": {"input": 1, "output": 0}, "content": []}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

OBSERVATION_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({
    "type": "provider_request_context", "requestIndex": 1,
    "provider": "SENTINEL_PROVIDER", "model": "SENTINEL_MODEL",
    "messages": [{"role": "user", "content": "SENTINEL_PROMPT"}],
}), flush=True)
print(json.dumps({
    "type": "tool_execution_start", "toolCallId": "call-1", "toolName": "grep",
    "args": {"pattern": "SENTINEL_ARGUMENTS"},
}), flush=True)
print(json.dumps({
    "type": "tool_execution_end", "toolCallId": "call-1",
    "result": "SENTINEL_RESULT", "isError": False,
}), flush=True)
print(json.dumps({
    "type": "provider_request_context", "requestIndex": 2,
    "provider": "SENTINEL_PROVIDER", "model": "SENTINEL_MODEL",
    "messages": [
        {"role": "user", "content": "SENTINEL_PROMPT"},
        {"role": "toolResult", "toolCallId": "call-1", "content": "SENTINEL_RESULT"},
    ],
}), flush=True)
print(json.dumps({
    "type": "message_end", "message": {
        "role": "assistant", "stopReason": "stop", "usage": {"input": 7, "output": 3},
        "content": "SENTINEL_ANSWER",
    },
}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

DESCENDANT_STDERR_SCRIPT = r'''
import json, subprocess, sys
request = json.loads(sys.stdin.readline())
subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(5)"])
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "owned tree"}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

LARGE_STDERR_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
sys.stderr.write("x" * (1024 * 1024))
sys.stderr.flush()
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "bounded stderr"}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''

OVERSIZED_LINE_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "x" * (128 * 1024)}}), flush=True)
'''

EVENT_FLOOD_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
for _ in range(2100):
    print(json.dumps({"type": "agent_start"}), flush=True)
'''

FINAL_TEXT_CAP_SCRIPT = r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
for _ in range(1100):
    print(json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "x" * 1024}}), flush=True)
'''


class MutableSignal:
    def __init__(self) -> None:
        self.cancelled = False


class RecordingDirectoryAuthority:
    def __init__(self, root: Path) -> None:
        self.directory_path = root
        self._root_fd = os.open(root, os.O_RDONLY)
        self.process_fd: int | None = None

    @contextmanager
    def open_process_working_directory(self):
        descriptor = os.dup(self._root_fd)
        self.process_fd = descriptor
        try:
            yield ProcessWorkingDirectory(
                identity_path=self.directory_path,
                cwd=str(self.directory_path),
                pass_fds=(descriptor,),
            )
        finally:
            os.close(descriptor)

    def close(self) -> None:
        os.close(self._root_fd)


class PiRuntimeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_authority_launch_ignores_python_startup_controls(
        self,
    ) -> None:
        script = r'''
IFS= read -r request
[ "$PYTHONPATH" = "$0" ] || exit 91
[ "$PYTHONHOME" = "$1" ] || exit 92
request_id=$(printf '%s' "$request" | /usr/bin/sed -E 's/.*"id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
printf '{"type":"response","id":"%s","success":true}\n' "$request_id"
printf '%s\n' \
  '{"type":"agent_start"}' \
  '{"type":"turn_start"}' \
  '{"type":"message_end","message":{"role":"assistant","stopReason":"stop","usage":{"input":1,"output":1},"content":[{"type":"text","text":"hostile-env-ok"}]}}' \
  '{"type":"agent_end"}'
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            shadow = root / "shadow"
            shadow_module = shadow / "asterion/runtime"
            shadow_module.mkdir(parents=True)
            benign_python_path = root / "benign-python-path"
            benign_python_path.mkdir()
            (shadow / "asterion/__init__.py").write_text("")
            (shadow_module / "__init__.py").write_text("")
            marker = root / "shadow-executed"
            (shadow_module / "cwd_exec.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['MALICIOUS_MARKER']).write_text('executed')\n"
            )
            environments = (
                {
                    "PYTHONPATH": str(shadow),
                    "PYTHONHOME": sys.prefix,
                    "PYTHONUSERBASE": str(root / "user-base"),
                    "PYTHONSTARTUP": str(root / "startup.py"),
                    "PYTHONWARNINGS": "ignore",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONHASHSEED": "7",
                    "MALICIOUS_MARKER": str(marker),
                },
                {
                    "PYTHONPATH": str(benign_python_path),
                    "PYTHONHOME": "/definitely/not/a/python/home",
                },
            )
            context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                context
            ) as authority:
                for index, environment in enumerate(environments):
                    with self.subTest(environment=index):
                        clients = (
                            PiRuntimeClient(
                                command=(
                                    "/bin/sh",
                                    "-c",
                                    script,
                                    environment["PYTHONPATH"],
                                    environment["PYTHONHOME"],
                                ),
                                cwd=corpus,
                                capabilities=("filesystem.read",),
                                env=environment,
                            ),
                            PiRuntimeClient(
                                command=(
                                    "/bin/sh",
                                    "-c",
                                    script,
                                    environment["PYTHONPATH"],
                                    environment["PYTHONHOME"],
                                ),
                                cwd=None,
                                cwd_authority=authority,
                                capabilities=("filesystem.read",),
                                env=environment,
                            ),
                        )
                        streams = []
                        for client_index, client in enumerate(clients):
                            with self.subTest(authority=client_index == 1):
                                streams.append([
                                    event.to_mapping()
                                    async for event in client.run(
                                        RunRequest(
                                            "hostile-python",
                                            "question",
                                            requested_capabilities=(
                                                "filesystem.read",
                                            ),
                                        )
                                    )
                                ])
                        self.assertEqual(streams[1], streams[0])
                        self.assertFalse(marker.exists())

    async def test_authority_launch_preserves_argv_and_session_identity(
        self,
    ) -> None:
        script = r'''
import json, os, sys
request = json.loads(sys.stdin.readline())
answer = json.dumps({
    "argv": sys.argv[1:],
    "session_leader": os.getsid(0) == os.getpid() == os.getpgrp(),
}, sort_keys=True)
print(json.dumps({"type": "response", "id": request["id"], "success": True}), flush=True)
print(json.dumps({"type": "agent_start"}), flush=True)
print(json.dumps({"type": "turn_start"}), flush=True)
print(json.dumps({"type": "message_end", "message": {
    "role": "assistant", "stopReason": "stop",
    "usage": {"input": 1, "output": 1},
    "content": [{"type": "text", "text": answer}],
}}), flush=True)
print(json.dumps({"type": "agent_end"}), flush=True)
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                context
            ) as authority:
                clients = (
                    PiRuntimeClient(
                        command=(
                            sys.executable,
                            "-u",
                            "-c",
                            script,
                            "alpha",
                            "two words",
                        ),
                        cwd=corpus,
                        capabilities=("filesystem.read",),
                        env={},
                        evidence_root=root / "direct-evidence",
                    ),
                    PiRuntimeClient(
                        command=(
                            sys.executable,
                            "-u",
                            "-c",
                            script,
                            "alpha",
                            "two words",
                        ),
                        cwd=None,
                        cwd_authority=authority,
                        capabilities=("filesystem.read",),
                        env={},
                        evidence_root=root / "authority-evidence",
                    ),
                )
                answers: list[str] = []
                for index, client in enumerate(clients):
                    _ = [
                        event
                        async for event in client.run(
                            RunRequest(
                                f"argv-session-{index}",
                                "question",
                                requested_capabilities=(
                                    "filesystem.read",
                                ),
                            )
                        )
                    ]
                    run_dir = client.completed_run_dir(
                        f"argv-session-{index}"
                    )
                    assert run_dir is not None
                    answers.append((run_dir / "final.txt").read_text())

            self.assertEqual(answers[1], answers[0])
            self.assertEqual(
                json.loads(answers[0]),
                {
                    "argv": ["alpha", "two words"],
                    "session_leader": True,
                },
            )

    async def test_authority_cancellation_matches_direct_process_reaping(
        self,
    ) -> None:
        script = (
            "import json,os,pathlib,sys,time;"
            "json.loads(sys.stdin.readline());"
            "pathlib.Path(os.environ['PID_FILE']).write_text(str(os.getpid()));"
            "time.sleep(30)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                context
            ) as authority:
                for index in range(2):
                    pid_file = root / f"pid-{index}"
                    signal = MutableSignal()
                    client = PiRuntimeClient(
                        command=(sys.executable, "-u", "-c", script),
                        cwd=corpus if index == 0 else None,
                        cwd_authority=authority if index == 1 else None,
                        capabilities=("filesystem.read",),
                        env={"PID_FILE": str(pid_file)},
                    )
                    task = asyncio.create_task(
                        anext(
                            client.run(
                                RunRequest(
                                    f"cancel-exact-{index}",
                                    "question",
                                    requested_capabilities=(
                                        "filesystem.read",
                                    ),
                                ),
                                signal=signal,
                            )
                        )
                    )
                    for _ in range(200):
                        if pid_file.exists():
                            break
                        await asyncio.sleep(0.01)
                    self.assertTrue(pid_file.exists())
                    pid = int(pid_file.read_text())
                    signal.cancelled = True
                    with self.assertRaises(ProtocolError):
                        await asyncio.wait_for(task, timeout=3)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)

    async def test_authority_launch_restores_direct_sigpipe_behavior(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            context = HostServiceFactoryContext(
                provider_id="dci-agent-lite",
                application_id="dci.research-capability",
                application_version="1.0.0",
                capability_id="corpus.local-root",
                options={"root": str(corpus)},
            )
            async with create_local_corpus_service_factory().factory(
                context
            ) as authority:
                clients = (
                    PiRuntimeClient(
                        command=(
                            "/bin/bash",
                            "-c",
                            "kill -s PIPE $$; printf survived > \"$0\"",
                            str(root / "direct-survived"),
                        ),
                        cwd=corpus,
                        capabilities=("filesystem.read",),
                        env={},
                    ),
                    PiRuntimeClient(
                        command=(
                            "/bin/bash",
                            "-c",
                            "kill -s PIPE $$; printf survived > \"$0\"",
                            str(root / "authority-survived"),
                        ),
                        cwd=None,
                        cwd_authority=authority,
                        capabilities=("filesystem.read",),
                        env={},
                    ),
                )
                for index, client in enumerate(clients):
                    with (
                        self.subTest(authority=index == 1),
                        self.assertRaises(ProtocolError),
                    ):
                        await anext(
                            client.run(
                                RunRequest(
                                    f"sigpipe-{index}",
                                    "question",
                                    requested_capabilities=(
                                        "filesystem.read",
                                    ),
                                )
                            )
                        )
                    self.assertFalse(
                        (root / (
                            "authority-survived"
                            if index == 1
                            else "direct-survived"
                        )).exists()
                    )

    def _client(
        self,
        root: Path,
        script: str,
        *,
        max_turns: int = 4,
    ) -> PiRuntimeClient:
        return PiRuntimeClient(
            command=(sys.executable, "-u", "-c", script),
            cwd=root,
            capabilities=("filesystem.read", "shell"),
            max_turns=max_turns,
            evidence_root=root / "evidence",
        )

    async def test_reordered_tools_produce_canonical_request_and_started_capabilities(
        self,
    ) -> None:
        capabilities = map_pi_capabilities("bash,read,bash")
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SUCCESS_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=tuple(capabilities),
            )
            events = [
                event
                async for event in client.run(
                    RunRequest(
                        run_id="canonical-pi-tools",
                        input_text="Read the corpus",
                        requested_capabilities=tuple(capabilities),
                    )
                )
            ]

        self.assertEqual(capabilities, ["filesystem.read", "shell"])
        self.assertEqual(events[0].payload["capabilities"], capabilities)
        validate_event_stream([event.to_mapping() for event in events])

    async def test_process_binding_fd_closes_on_start_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            authority = RecordingDirectoryAuthority(Path(temp_dir))
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SUCCESS_SCRIPT),
                cwd=None,
                cwd_authority=authority,
                capabilities=("filesystem.read",),
            )
            try:
                with (
                    patch(
                        "asterion.runtimes.pi.asyncio.create_subprocess_exec",
                        side_effect=OSError("SECRET-START"),
                    ),
                    self.assertRaises(ProtocolError) as caught,
                ):
                    await anext(
                        client.run(
                            RunRequest(
                                "start-failure",
                                "question",
                                requested_capabilities=("filesystem.read",),
                            )
                        )
                    )
                assert authority.process_fd is not None
                with self.assertRaises(OSError):
                    os.fstat(authority.process_fd)
                self.assertNotIn("SECRET", str(caught.exception))
            finally:
                authority.close()

    async def test_process_binding_fd_is_closed_before_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            authority = RecordingDirectoryAuthority(Path(temp_dir))
            signal = MutableSignal()
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=None,
                cwd_authority=authority,
                capabilities=("filesystem.read",),
            )
            task = asyncio.create_task(
                anext(
                    client.run(
                        RunRequest(
                            "authority-cancel",
                            "question",
                            requested_capabilities=("filesystem.read",),
                        ),
                        signal=signal,
                    )
                )
            )
            try:
                for _ in range(100):
                    if authority.process_fd is not None:
                        try:
                            os.fstat(authority.process_fd)
                        except OSError:
                            break
                    await asyncio.sleep(0.01)
                assert authority.process_fd is not None
                with self.assertRaises(OSError):
                    os.fstat(authority.process_fd)
                signal.cancelled = True
                with self.assertRaises(ProtocolError):
                    await asyncio.wait_for(task, timeout=3)
            finally:
                authority.close()

    async def test_translates_one_pi_rpc_run_to_normalized_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SUCCESS_SCRIPT),
                cwd=root,
                capabilities=("filesystem.read", "shell"),
                evidence_root=root / "evidence",
            )

            events = [
                event
                async for event in client.run(
                    RunRequest(
                        run_id="pi-run-1",
                        input_text="Read the corpus",
                        requested_capabilities=("filesystem.read", "shell"),
                    )
                )
            ]

            completed = client.completed_run_dir("pi-run-1")
            self.assertIsNotNone(completed)
            assert completed is not None
            self.assertEqual((completed / "final.txt").read_text(), "Pudding Lane")
            self.assertEqual(
                os.stat(completed).st_mode & 0o777,
                0o700,
            )
            self.assertEqual(
                os.stat(completed / "final.txt").st_mode & 0o777,
                0o600,
            )

        self.assertEqual(client.manifest.runtime_id, "pi.reference")
        self.assertEqual(
            tuple(event.type for event in events),
            (
                "run.started",
                "text.delta",
                "usage.reported",
                "artifact.created",
                "run.completed",
            ),
        )
        self.assertEqual(events[-1].payload["status"], "completed")

    async def test_completed_run_exposes_only_a_validated_deep_copied_observation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", OBSERVATION_SCRIPT),
                cwd=root,
                capabilities=("filesystem.read",),
                evidence_root=root / "evidence",
            )
            events = [
                event
                async for event in client.run(
                    RunRequest(
                        run_id="pathlight-private-run",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    )
                )
            ]

            observed = client.pathlight_runtime_observation("pathlight-private-run")
            self.assertEqual(events[-1].type, "run.completed")
            self.assertIsNotNone(observed)
            assert observed is not None
            self.assertEqual(len(observed["frames"]), 2)
            self.assertEqual(len(observed["model_calls"]), 2)
            rendered = json.dumps(observed)
            for sentinel in (
                "SENTINEL_PROVIDER",
                "SENTINEL_MODEL",
                "SENTINEL_PROMPT",
                "SENTINEL_ARGUMENTS",
                "SENTINEL_RESULT",
                "SENTINEL_ANSWER",
            ):
                self.assertNotIn(sentinel, rendered)
            observed["frames"].clear()
            next_observed = client.pathlight_runtime_observation("pathlight-private-run")
            assert next_observed is not None
            self.assertEqual(len(next_observed["frames"]), 2)
            self.assertIsNone(client.pathlight_runtime_observation("other-run"))

    async def test_completion_is_published_only_after_normal_stream_exhaustion(
        self,
    ) -> None:
        for prefix in range(1, 6):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                client = self._client(root, SUCCESS_SCRIPT)
                stream = client.run(
                    RunRequest(
                        run_id=f"prefix-{prefix}",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    )
                )
                for _ in range(prefix):
                    await anext(stream)
                await stream.aclose()
                self.assertIsNone(client.completed_run_dir(f"prefix-{prefix}"))
                self.assertEqual(list((root / "evidence").iterdir()), [])

        for prefix in range(1, 5):
            with self.subTest(failure_prefix=prefix), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                client = self._client(root, SUCCESS_SCRIPT)
                stream = client.run(
                    RunRequest(
                        run_id=f"consumer-failure-{prefix}",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    )
                )
                for _ in range(prefix):
                    await anext(stream)
                with self.assertRaisesRegex(RuntimeError, "consumer stopped"):
                    await stream.athrow(RuntimeError("consumer stopped"))
                self.assertIsNone(
                    client.completed_run_dir(f"consumer-failure-{prefix}")
                )
                self.assertEqual(list((root / "evidence").iterdir()), [])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            client = self._client(root, SUCCESS_SCRIPT)
            events = [
                event
                async for event in client.run(
                    RunRequest(
                        run_id="fully-consumed",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    )
                )
            ]
            self.assertEqual(events[-1].type, "run.completed")
            self.assertIsNotNone(client.completed_run_dir("fully-consumed"))

    async def test_error_retry_turn_limit_and_final_recovery_lifecycle(self) -> None:
        cases = (
            ("assistant-error", ERROR_SCRIPT, 4, False, None),
            ("over-turn-limit", OVER_TURN_SCRIPT, 1, False, None),
            ("empty-final", EMPTY_FINAL_SCRIPT, 4, False, None),
            ("retry-final", RETRY_SCRIPT, 4, True, "recovered answer"),
            (
                "message-recovery",
                RECOVERED_FINAL_SCRIPT,
                4,
                True,
                "recovered final",
            ),
        )
        for run_id, script, turns, succeeds, expected in cases:
            with self.subTest(run_id=run_id), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                client = self._client(root, script, max_turns=turns)
                request = RunRequest(
                    run_id=run_id,
                    input_text="question",
                    requested_capabilities=("filesystem.read",),
                )
                if succeeds:
                    events = await _collect(client, request, MutableSignal())
                    completed = client.completed_run_dir(run_id)
                    self.assertIsNotNone(completed)
                    assert completed is not None
                    self.assertEqual((completed / "final.txt").read_text(), expected)
                    if run_id == "retry-final":
                        deltas = [
                            event.payload["text"]
                            for event in events
                            if event.type == "text.delta"
                        ]
                        self.assertEqual(deltas, ["recovered answer"])
                else:
                    with self.assertRaises(ProtocolError) as raised:
                        await _collect(client, request, MutableSignal())
                    self.assertNotIn("SECRET", str(raised.exception))
                    self.assertIsNone(client.completed_run_dir(run_id))

    async def test_owned_tree_caps_and_reuse_after_failure(self) -> None:
        for script in (DESCENDANT_STDERR_SCRIPT, LARGE_STDERR_SCRIPT):
            with self.subTest(script=script[:20]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                client = self._client(root, script)
                started = time.monotonic()
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="bounded-success",
                            input_text="question",
                            requested_capabilities=("filesystem.read",),
                        ),
                        MutableSignal(),
                    ),
                    timeout=2,
                )
                self.assertLess(time.monotonic() - started, 2)
                self.assertFalse(client._running)

        for index, script in enumerate(
            (OVERSIZED_LINE_SCRIPT, EVENT_FLOOD_SCRIPT, FINAL_TEXT_CAP_SCRIPT)
        ):
            with self.subTest(cap=index), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                client = self._client(root, script)
                with self.assertRaises(ProtocolError):
                    await _collect(
                        client,
                        RunRequest(
                            run_id=f"oversized-{index}",
                            input_text="question",
                            requested_capabilities=("filesystem.read",),
                        ),
                        MutableSignal(),
                    )
                self.assertFalse(client._running)
                client._command = (sys.executable, "-u", "-c", SUCCESS_SCRIPT)
                await _collect(
                    client,
                    RunRequest(
                        run_id=f"reused-{index}",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    ),
                    MutableSignal(),
                )
                self.assertIsNotNone(
                    client.completed_run_dir(f"reused-{index}")
                )

    async def test_cancellation_during_finalization_reaps_tree_and_reuses_client(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            client = self._client(root, DESCENDANT_STDERR_SCRIPT)
            work = asyncio.create_task(
                _collect(
                    client,
                    RunRequest(
                        run_id="cancel-finalization",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    ),
                    MutableSignal(),
                )
            )
            await asyncio.sleep(0.1)
            work.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(work, timeout=2)
            self.assertFalse(client._running)
            self.assertIsNone(client.completed_run_dir("cancel-finalization"))

            client._command = (sys.executable, "-u", "-c", SUCCESS_SCRIPT)
            await _collect(
                client,
                RunRequest(
                    run_id="after-finalization-cancel",
                    input_text="question",
                    requested_capabilities=("filesystem.read",),
                ),
                MutableSignal(),
            )
            self.assertIsNotNone(
                client.completed_run_dir("after-finalization-cancel")
            )

    async def test_evidence_root_rejects_symlinks_modes_files_and_replacement(
        self,
    ) -> None:
        for kind in ("symlink", "file", "public"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                evidence = root / f"SECRET-{kind}"
                if kind == "symlink":
                    target = root / "target"
                    target.mkdir(mode=0o700)
                    evidence.symlink_to(target, target_is_directory=True)
                elif kind == "file":
                    evidence.write_text("private")
                    evidence.chmod(0o600)
                else:
                    evidence.mkdir(mode=0o755)
                client = PiRuntimeClient(
                    command=("SECRET-MISSING-COMMAND",),
                    cwd=root,
                    capabilities=("filesystem.read",),
                    env={},
                    evidence_root=evidence,
                )
                with self.assertRaises(ProtocolError) as raised:
                    await _collect(
                        client,
                        RunRequest(
                            run_id="SECRET-RUN-ID",
                            input_text="SECRET-INPUT",
                            requested_capabilities=("filesystem.read",),
                        ),
                        MutableSignal(),
                    )
                self.assertNotIn("SECRET", str(raised.exception))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            evidence = root / "evidence"
            client = self._client(root, SUCCESS_SCRIPT)
            original_stage = __import__(
                "asterion.runtimes.pi", fromlist=["_stage_evidence"]
            )._stage_evidence
            parked = root / "parked"

            def replace_root(*args, **kwargs):
                staged = original_stage(*args, **kwargs)
                evidence.rename(parked)
                evidence.mkdir(mode=0o700)
                return staged

            with (
                patch(
                    "asterion.runtimes.pi._stage_evidence",
                    side_effect=replace_root,
                ),
                self.assertRaises(ProtocolError),
            ):
                await _collect(
                    client,
                    RunRequest(
                        run_id="replacement-race",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    ),
                    MutableSignal(),
                )
            self.assertIsNone(client.completed_run_dir("replacement-race"))
            self.assertEqual(list(parked.iterdir()), [])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            evidence = root / "evidence"
            client = self._client(root, SUCCESS_SCRIPT)
            module = __import__(
                "asterion.runtimes.pi", fromlist=["_publish_evidence"]
            )
            original_publish = module._publish_evidence
            parked = root / "parked"

            def replace_after_publish(*args, **kwargs):
                identity = original_publish(*args, **kwargs)
                evidence.rename(parked)
                evidence.mkdir(mode=0o700)
                return identity

            with (
                patch(
                    "asterion.runtimes.pi._publish_evidence",
                    side_effect=replace_after_publish,
                ),
                self.assertRaises(ProtocolError),
            ):
                await _collect(
                    client,
                    RunRequest(
                        run_id="post-publication-race",
                        input_text="question",
                        requested_capabilities=("filesystem.read",),
                    ),
                    MutableSignal(),
                )
            self.assertIsNone(
                client.completed_run_dir("post-publication-race")
            )
            self.assertEqual(list(parked.iterdir()), [])

    async def test_failure_paths_close_every_evidence_descriptor(self) -> None:
        descriptor_root = Path("/dev/fd")
        if not descriptor_root.is_dir():
            self.skipTest("descriptor inventory is unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            client = self._client(root, INVALID_JSON_SCRIPT)
            before = len(list(descriptor_root.iterdir()))
            for index in range(5):
                with self.assertRaises(ProtocolError):
                    await _collect(
                        client,
                        RunRequest(
                            run_id=f"descriptor-failure-{index}",
                            input_text="question",
                            requested_capabilities=("filesystem.read",),
                        ),
                        MutableSignal(),
                    )
            gc.collect()
            after = len(list(descriptor_root.iterdir()))
            self.assertLessEqual(after, before)

    async def test_capability_mismatch_fails_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=("missing-secret-command",),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            with self.assertRaises(ProtocolError) as raised:
                _ = [
                    event
                    async for event in client.run(
                        RunRequest(
                            run_id="capability-mismatch",
                            input_text="SECRET-INPUT",
                            requested_capabilities=("shell",),
                        )
                    )
                ]
        self.assertNotIn("SECRET", str(raised.exception))

    async def test_invalid_json_and_early_eof_are_redacted(self) -> None:
        for script in (INVALID_JSON_SCRIPT, EARLY_EOF_SCRIPT):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temp_dir:
                evidence_root = Path(temp_dir) / "evidence"
                client = PiRuntimeClient(
                    command=(sys.executable, "-u", "-c", script),
                    cwd=Path(temp_dir),
                    capabilities=("filesystem.read",),
                    evidence_root=evidence_root,
                )
                with self.assertRaises(ProtocolError) as raised:
                    _ = [
                        event
                        async for event in client.run(
                            RunRequest(
                                run_id="invalid-stream",
                                input_text="SECRET-INPUT",
                                requested_capabilities=("filesystem.read",),
                            )
                        )
                    ]
                self.assertNotIn("SECRET", str(raised.exception))
                self.assertIsNone(client.completed_run_dir("invalid-stream"))
                self.assertFalse(evidence_root.exists())

    async def test_cancellation_aborts_and_reaps_a_slow_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
                evidence_root=Path(temp_dir) / "evidence",
            )
            signal = MutableSignal()

            async def cancel() -> None:
                await asyncio.sleep(0.05)
                signal.cancelled = True

            cancel_task = asyncio.create_task(cancel())
            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="cancelled-run",
                            input_text="Read the corpus",
                            requested_capabilities=("filesystem.read",),
                        ),
                        signal,
                    ),
                    timeout=1,
                )
            await cancel_task
            self.assertIsNone(client.completed_run_dir("cancelled-run"))
            self.assertIsNone(client.pathlight_runtime_observation("cancelled-run"))

    async def test_rejects_a_second_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            first_signal = MutableSignal()
            first = asyncio.create_task(
                _collect(
                    client,
                    RunRequest(
                        run_id="first-run",
                        input_text="Read the corpus",
                        requested_capabilities=("filesystem.read",),
                    ),
                    first_signal,
                )
            )
            await asyncio.sleep(0.05)
            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="second-run",
                            input_text="Read the corpus",
                            requested_capabilities=("filesystem.read",),
                        ),
                        MutableSignal(),
                    ),
                    timeout=0.5,
                )
            first_signal.cancelled = True
            with self.assertRaises(ProtocolError):
                await first

    async def test_request_deadline_terminates_and_reaps_the_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = PiRuntimeClient(
                command=(sys.executable, "-u", "-c", SLOW_SCRIPT),
                cwd=Path(temp_dir),
                capabilities=("filesystem.read",),
            )
            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(
                    _collect(
                        client,
                        RunRequest(
                            run_id="deadline-run",
                            input_text="Read the corpus",
                            requested_capabilities=("filesystem.read",),
                            deadline_ms=50,
                        ),
                        MutableSignal(),
                    ),
                    timeout=1,
                )


async def _collect(
    client: PiRuntimeClient,
    request: RunRequest,
    signal: MutableSignal,
):
    return [event async for event in client.run(request, signal=signal)]


if __name__ == "__main__":
    unittest.main()
