"""Provider-owned persistent IPython process with bounded private JSONL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import select
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

from asterion.agents.prime.tools import PrimeToolCall, PrimeToolResult

from .task import P1_INPUT_TUPLE, P1_TASK_STATEMENT
from .worker import (
    OUTPUT_CAP,
    ROOT_BYTES_CAP,
    WRITE_CELL_CAP,
    WIRE_CAP,
    P1CellObservation,
    P1CellReceipt,
    P1CellRequest,
    P1InstrumentationSnapshot,
    P1WorkerCheckpoint,
    P1WorkerCleanupReceipt,
    P1WorkerError,
    P1WorkerIdentity,
    digest,
)


class P1WorkerProcess:
    """One process and namespace, owned across clean control reconstruction.

    This restricts the Python cell surface. It is not an OS security sandbox.
    The caller supplies the one absolute run deadline after operator preflight.
    """

    def __init__(self, *, deadline: float, interpreter: str | None = None) -> None:
        if (
            type(deadline) not in {int, float}
            or not math.isfinite(deadline)
            or deadline <= time.monotonic()
        ):
            raise P1WorkerError("P1 worker configuration rejected")
        if not (
            callable(getattr(select, "kqueue", None))
            or (
                callable(getattr(os, "waitid", None))
                and all(
                    hasattr(os, name)
                    for name in ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT")
                )
            )
        ):
            raise P1WorkerError("P1 worker configuration rejected")
        self._deadline = deadline
        self._interpreter = Path(interpreter or sys.executable).absolute()
        self._entrypoint = Path(__file__).with_name("worker_main.py").resolve()
        self._launch_fingerprints = self._fingerprints()
        self._process: subprocess.Popen[bytes] | None = None
        self._started_process: subprocess.Popen[bytes] | None = None
        self._root: tempfile.TemporaryDirectory[str] | None = None
        self._root_fd: int | None = None
        self._root_identity: tuple[int, int] | None = None
        self._identity: P1WorkerIdentity | None = None
        self._authority = object()
        self._lifecycle = object()
        self._snapshot: P1InstrumentationSnapshot | None = None
        self._seen: set[str] = set()
        self._active = False
        self._closed = self._poisoned = self._starting = False
        self._cleanup: P1WorkerCleanupReceipt | None = None
        self._close_lock = asyncio.Lock()
        self._frames: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
        self._readers: list[threading.Thread] = []
        self._reader_stop = threading.Event()
        self._protocol_failed = threading.Event()
        self._stdout_gone = threading.Event()
        self._process_gone = threading.Event()
        self._exit_watch: select.kqueue | None = None
        self._liveness_ready = False
        self._reap_count = 0

    def __repr__(self) -> str:
        return "<P1WorkerProcess redacted>"

    def _fingerprints(self) -> tuple:
        result = []
        failed = False
        try:
            for path in (self._interpreter, self._entrypoint):
                value = path.stat()
                if not stat.S_ISREG(value.st_mode):
                    raise ValueError
                result.append(
                    (
                        value.st_dev,
                        value.st_ino,
                        value.st_size,
                        value.st_mtime_ns,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
        except Exception:
            failed = True
        if failed:
            raise P1WorkerError("P1 worker configuration rejected")
        return tuple(result)

    @property
    def identity(self) -> P1WorkerIdentity:
        if self._identity is None:
            raise P1WorkerError("P1 worker unavailable")
        return self._identity

    @property
    def identity_sha256(self) -> str:
        return self.identity.sha256()

    @property
    def cleanup_receipt(self) -> P1WorkerCleanupReceipt | None:
        return self._cleanup

    def _open_exit_watch(self, process: subprocess.Popen[bytes]) -> None:
        # macOS Python 3.10-3.12 has no os.waitid. Register against our still-owned
        # child before accepting readiness; NOTE_EXIT observes even an unreaped
        # zombie and never consumes Popen's eventual wait status.
        if callable(getattr(select, "kqueue", None)):
            watch = select.kqueue()
            event = select.kevent(
                process.pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_EXIT,
            )
            try:
                watch.control([event], 0, 0)
            except Exception:
                watch.close()
                raise
            self._exit_watch = watch
        elif not (
            callable(getattr(os, "waitid", None))
            and all(
                hasattr(os, name) for name in ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT")
            )
        ):
            raise ValueError
        self._liveness_ready = True

    def _has_exited(self, process: subprocess.Popen[bytes]) -> bool:
        if self._process_gone.is_set():
            return True
        if self._exit_watch is not None:
            # No wait/poll/reap, and no blocking. Latch an observed exit because
            # retrieving a kevent clears that observer's notification.
            exited = bool(self._exit_watch.control(None, 1, 0))
        else:
            exited = (
                os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                is not None
            )
        if exited:
            self._process_gone.set()
        return exited

    def validate_lifecycle(self) -> object:
        valid = False
        try:
            process = self._process
            if (
                self._closed
                or self._poisoned
                or self._protocol_failed.is_set()
                or self._stdout_gone.is_set()
                or process is None
                or process is not self._started_process
                or self._identity is None
                or process.pid != self.identity.pid
                or process.returncode is not None
                or self._root_fd is None
                or self._root is None
                or time.monotonic() >= self._deadline
            ):
                raise ValueError
            os.kill(process.pid, 0)
            if self._has_exited(process):
                raise ValueError
            root_stat = os.fstat(self._root_fd)
            path_stat = os.stat(self._root.name, follow_symlinks=False)
            valid = (root_stat.st_dev, root_stat.st_ino) == self._root_identity == (
                path_stat.st_dev,
                path_stat.st_ino,
            ) and self._launch_fingerprints == self._fingerprints()
        except Exception:
            valid = False
        if not valid:
            raise P1WorkerError("P1 worker unavailable")
        return self._lifecycle

    def snapshot(self) -> P1InstrumentationSnapshot:
        if self._snapshot is None:
            raise P1WorkerError("P1 worker unavailable")
        return self._snapshot

    def public_namespace(self) -> tuple[str, ...]:
        """Only the fixed seed inventory is exposed, never namespace values."""
        return self.snapshot().seeded_symbols

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while not self._reader_stop.is_set():
                line = process.stdout.readline(WIRE_CAP + 1)
                if not line:
                    self._stdout_gone.set()
                    self._frames.put_nowait(None)
                    return
                if len(line) > WIRE_CAP or not line.endswith(b"\n"):
                    self._protocol_failed.set()
                    return
                self._frames.put_nowait(line)
        except Exception:
            if not self._reader_stop.is_set():
                self._protocol_failed.set()

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        count = 0
        try:
            while not self._reader_stop.is_set():
                chunk = process.stderr.read(4096)
                if not chunk:
                    return
                count += len(chunk)
                if count > OUTPUT_CAP:
                    self._protocol_failed.set()
                    return
        except Exception:
            if not self._reader_stop.is_set():
                self._protocol_failed.set()

    def _send_blocking(self, encoded: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise ValueError
        process.stdin.write(encoded)
        process.stdin.flush()

    async def _exchange(self, message: dict) -> dict:
        encoded = (
            json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        )
        if len(encoded) > WIRE_CAP:
            raise ValueError
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError
        await asyncio.wait_for(
            asyncio.to_thread(self._send_blocking, encoded), remaining
        )
        while time.monotonic() < self._deadline:
            if self._protocol_failed.is_set():
                raise ValueError
            try:
                line = self._frames.get_nowait()
            except queue.Empty:
                await asyncio.sleep(
                    min(0.01, max(0, self._deadline - time.monotonic()))
                )
                continue
            if line is None:
                raise ValueError
            value = json.loads(line.decode("utf-8"))
            if type(value) is not dict:
                raise ValueError
            return value
        raise ValueError

    async def start(self) -> None:
        if (
            self._starting
            or self._process is not None
            or self._closed
            or self._poisoned
        ):
            raise P1WorkerError("P1 worker unavailable")
        self._starting = True
        failed = cancelled = False
        try:
            if (
                self._fingerprints() != self._launch_fingerprints
                or time.monotonic() >= self._deadline
            ):
                raise ValueError
            self._root = tempfile.TemporaryDirectory(prefix="asterion-p1-")
            self._root_fd = os.open(
                self._root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            root_stat = os.fstat(self._root_fd)
            self._root_identity = (root_stat.st_dev, root_stat.st_ino)
            self._process = subprocess.Popen(
                [
                    str(self._interpreter),
                    "-I",
                    "-B",
                    "-u",
                    str(self._entrypoint),
                    str(self._root_fd),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._root.name,
                env={
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PYTHONIOENCODING": "utf-8",
                },
                pass_fds=(self._root_fd,),
                start_new_session=True,
            )
            self._started_process = self._process
            self._open_exit_watch(self._process)
            for target in (self._read_stdout, self._read_stderr):
                thread = threading.Thread(target=target, daemon=True)
                thread.start()
                self._readers.append(thread)
            ready = await self._exchange(
                {"input_tuple": P1_INPUT_TUPLE, "task_statement": P1_TASK_STATEMENT}
            )
            if (
                set(ready)
                != {"type", "pid", "namespace_nonce", "cwd", "seeded_symbols"}
                or ready["type"] != "ready"
                or type(ready["pid"]) is not int
                or ready["pid"] != self._process.pid
                or ready["cwd"] != list(self._root_identity)
                or ready["seeded_symbols"] != ["input_tuple", "task_statement"]
                or type(ready["namespace_nonce"]) is not str
                or len(ready["namespace_nonce"]) != 32
            ):
                raise ValueError
            self._identity = P1WorkerIdentity(
                self._process.pid, ready["namespace_nonce"], digest(self._root_identity)
            )
            self._snapshot = P1InstrumentationSnapshot(
                self.identity,
                ("input_tuple", "task_statement"),
                (),
                None,
                self._authority,
            )
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        finally:
            self._starting = False
        if failed or cancelled:
            self._poisoned = True
            await self.close()
            if cancelled:
                raise asyncio.CancelledError()
            raise P1WorkerError("P1 worker start failed")

    def _file_bytes(self) -> tuple[bytes | None, tuple[int, int] | None]:
        if self._root_fd is None:
            raise ValueError
        try:
            fd = os.open(
                "stage-one.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=self._root_fd,
            )
        except FileNotFoundError:
            return None, None
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError
            data = os.read(fd, OUTPUT_CAP + 1)
            if len(data) > OUTPUT_CAP:
                raise ValueError
            return data, (file_stat.st_dev, file_stat.st_ino)
        finally:
            os.close(fd)

    def _observation(
        self, frame: dict, request: P1CellRequest
    ) -> tuple[P1CellObservation, str]:
        expected = {
            "type",
            "request_id",
            "turn_id",
            "sequence",
            "status",
            "output",
            "accumulator_id",
            "class_name",
            "callable_probe",
            "stage_one_verified",
            "final_result",
            "call_observations",
            "file_reads",
            "file_read_sha256",
            "file_write_calls",
            "file_write_bytes",
            "file_write_opens",
            "cell_write_bytes",
            "root_bytes",
            "audit_denials",
        }
        if (
            set(frame) != expected
            or frame["type"] != "cell"
            or frame["request_id"] != request.request_id
            or frame["turn_id"] != request.turn_id
            or type(frame["sequence"]) is not int
            or frame["sequence"] != len(self.snapshot().cells) + 1
            or frame["status"] not in {"completed", "uncertain"}
        ):
            raise ValueError
        output = frame["output"]
        if type(output) is not str or len(output.encode("utf-8")) > OUTPUT_CAP:
            raise ValueError
        for name in (
            "file_reads",
            "audit_denials",
            "file_write_calls",
            "file_write_bytes",
            "file_write_opens",
        ):
            if type(frame[name]) is not int or not 0 <= frame[name] <= 100000:
                raise ValueError
        if (
            type(frame["cell_write_bytes"]) is not int
            or not 0 <= frame["cell_write_bytes"] <= WRITE_CELL_CAP
            or type(frame["root_bytes"]) is not int
            or not 0 <= frame["root_bytes"] <= ROOT_BYTES_CAP
        ):
            raise ValueError
        for name in ("accumulator_id", "final_result"):
            if frame[name] is not None and type(frame[name]) is not int:
                raise ValueError
        if frame["class_name"] is not None and (
            type(frame["class_name"]) is not str or len(frame["class_name"]) > 128
        ):
            raise ValueError
        probe = frame["callable_probe"]
        if probe is not None and (
            type(probe) is not list
            or len(probe) != 2
            or any(type(v) is not int for v in probe)
        ):
            raise ValueError
        calls = frame["call_observations"]
        read_digests = frame["file_read_sha256"]
        if (
            type(read_digests) is not list
            or len(read_digests) > 128
            or any(
                type(value) is not str
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in read_digests
            )
        ):
            raise ValueError
        if (
            type(calls) is not list
            or len(calls) > 128
            or any(
                type(row) is not list
                or len(row) != 3
                or any(type(v) is not int for v in row)
                for row in calls
            )
        ):
            raise ValueError
        verified = frame["stage_one_verified"]
        if verified is not None and (
            type(verified) is not dict
            or any(
                type(k) is not str or type(v) not in {int, str, bool}
                for k, v in verified.items()
            )
        ):
            raise ValueError
        data, file_identity = self._file_bytes()
        observation = P1CellObservation(
            frame["sequence"],
            request.request_id,
            request.turn_id,
            hashlib.sha256(request.code.encode()).hexdigest(),
            frame["status"],
            frame["accumulator_id"],
            frame["class_name"],
            None if probe is None else (probe[0], probe[1]),
            data,
            None if data is None else hashlib.sha256(data).hexdigest(),
            verified,
            frame["final_result"],
            tuple((row[0], row[1], row[2]) for row in calls),
            frame["file_reads"],
            frame["audit_denials"],
            tuple(read_digests),
            file_identity,
            frame["file_write_calls"],
            frame["file_write_bytes"],
            frame["file_write_opens"],
            frame["cell_write_bytes"],
            frame["root_bytes"],
        )
        return observation, output

    async def execute_cell(self, request: P1CellRequest) -> P1CellReceipt:
        if (
            type(request) is not P1CellRequest
            or request.request_id in self._seen
            or self._active
            or len(self._seen) >= 4
        ):
            raise P1WorkerError("P1 worker request rejected")
        self.validate_lifecycle()
        self._active = True
        self._seen.add(request.request_id)
        cancelled = failed = False
        observation = None
        output = ""
        try:
            # Possible dispatch begins before the first asynchronous write.
            frame = await self._exchange(
                {
                    "type": "cell",
                    "request_id": request.request_id,
                    "turn_id": request.turn_id,
                    "code": request.code,
                }
            )
            observation, output = self._observation(frame, request)
            previous = self.snapshot()
            self._snapshot = P1InstrumentationSnapshot(
                previous.identity,
                previous.seeded_symbols,
                (*previous.cells, observation),
                previous.checkpoint,
                self._authority,
            )
            failed = observation.status != "completed"
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        finally:
            self._active = False
        if failed or cancelled:
            self._poisoned = True
            await self.close()
            if cancelled:
                raise asyncio.CancelledError()
            return P1CellReceipt(
                request.request_id,
                "uncertain",
                "",
                digest((request.request_id, "uncertain"))
                if observation is None
                else observation.sha256(),
            )
        if observation is None:
            raise P1WorkerError("P1 worker unavailable")
        return P1CellReceipt(request.request_id, "ok", output, observation.sha256())

    async def execute(self, call: PrimeToolCall, *, turn_id: str) -> PrimeToolResult:
        """Private Pi bridge seam; the operator supplies the admitted turn ID."""
        if (
            type(call) is not PrimeToolCall
            or call.name != "ipython"
            or set(call.arguments) != {"code"}
            or type(call.arguments["code"]) is not str
        ):
            raise P1WorkerError("P1 worker request rejected")
        result = await self.execute_cell(
            P1CellRequest(call.call_id, turn_id, call.arguments["code"])
        )
        return PrimeToolResult(
            call.call_id,
            "ok" if result.status == "ok" else "uncertain",
            ({"type": "text", "text": result.output},),
        )

    def mark_compact_checkpoint(self, checkpoint: P1WorkerCheckpoint) -> None:
        self.validate_lifecycle()
        current = self.snapshot()
        if (
            self._active
            or type(checkpoint) is not P1WorkerCheckpoint
            or current.checkpoint is not None
            or len(current.cells) != 2
            or checkpoint.after_sequence != 2
            or checkpoint.worker_identity_sha256 != self.identity_sha256
        ):
            raise P1WorkerError("P1 worker checkpoint rejected")
        self._snapshot = P1InstrumentationSnapshot(
            current.identity,
            current.seeded_symbols,
            current.cells,
            checkpoint,
            self._authority,
        )

    def _signal_owned_process(self, process: subprocess.Popen[bytes], sig: int) -> None:
        if self._liveness_ready and self._has_exited(process):
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can report EPERM for a child that became a zombie between
            # observation and signaling. Only positive exit evidence permits it.
            if self._liveness_ready:
                if not self._has_exited(process):
                    raise
            else:
                # Observer setup failed, but this exact Popen is still ours.
                # Cleanup alone may reap; a zero-time wait must prove exit.
                process.wait(timeout=0)

    def _reap_blocking(self) -> tuple[bool, bool]:
        process = self._started_process
        if process is None:
            return True, True
        self._reader_stop.set()
        if self._reap_count == 0:
            self._signal_owned_process(process, signal.SIGTERM)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._signal_owned_process(process, signal.SIGKILL)
                process.wait(timeout=1)
            self._reap_count += 1
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        for thread in self._readers:
            thread.join(timeout=1)
        if self._exit_watch is not None:
            self._exit_watch.close()
            self._exit_watch = None
        return process.returncode is not None, all(
            pipe is None or pipe.closed
            for pipe in (process.stdin, process.stdout, process.stderr)
        ) and all(not thread.is_alive() for thread in self._readers)

    async def close(self) -> P1WorkerCleanupReceipt:
        result = None
        cancelled = failed = False
        try:
            result = await self._close()
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if cancelled:
            raise asyncio.CancelledError()
        if failed or result is None:
            raise P1WorkerError("P1 worker cleanup failed")
        return result

    async def _close(self) -> P1WorkerCleanupReceipt:
        async with self._close_lock:
            if self._cleanup is not None:
                return self._cleanup
            self._closed = True
            cleanup_task = asyncio.create_task(asyncio.to_thread(self._reap_blocking))
            cancelled = False
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    cancelled = True
            failed = False
            try:
                reaped, pipes_closed = cleanup_task.result()
                if not reaped or not pipes_closed:
                    raise ValueError
                if self._root_fd is not None:
                    os.close(self._root_fd)
                    self._root_fd = None
                if self._root is not None:
                    self._root.cleanup()
                self._cleanup = P1WorkerCleanupReceipt(
                    self.identity_sha256
                    if self._identity is not None
                    else digest("unstarted"),
                    self.snapshot().cells[-1].sha256()
                    if self._snapshot is not None and self._snapshot.cells
                    else digest("no-effects"),
                    reaped,
                    pipes_closed,
                    self._root is None or not Path(self._root.name).exists(),
                    self._reap_count,
                )
            except Exception:
                failed = True
            if cancelled:
                raise asyncio.CancelledError()
            if failed or self._cleanup is None:
                raise P1WorkerError("P1 worker cleanup failed")
            return self._cleanup
