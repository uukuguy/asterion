"""Prime's persistent Python subprocess and its dedicated response channel.

No application imports, action bridge, inherited credentials, or inherited
operator descriptors are supplied. This is not an OS security sandbox.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import os
from pathlib import Path
import signal as process_signals
import socket
import sys


class SubprocessPythonWorker:
    def __init__(self, *, python: Path | None = None) -> None:
        self._python = str(python or Path(sys.executable))
        self._process: asyncio.subprocess.Process | None = None
        self._channel: socket.socket | None = None
        self._pending = bytearray()
        self._response_limit = 0
        self.closed = False

    def __repr__(self) -> str:
        return "<SubprocessPythonWorker redacted>"

    async def start(self, bootstrap: object, *, limits: object, signal: object) -> None:
        from asterion.agents.prime.ipython import _plain

        if self._process is not None or self.closed or signal.cancelled:
            raise RuntimeError("Prime worker is unavailable")
        workspace = bootstrap.workspace
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent, child = socket.socketpair()
        parent.setblocking(False)
        self._channel = parent
        self._response_limit = (
            limits.max_output_bytes * 6
            + limits.max_export_bytes * limits.max_exports_per_cell * 6
            + 8192
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._python,
                "-I",
                "-u",
                str(Path(__file__).resolve()),
                str(child.fileno()),
                cwd=workspace,
                env={"LANG": "C.UTF-8"},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(child.fileno(),),
                start_new_session=True,
            )
        finally:
            child.close()
        value = await self._request(
            {
                "operation": "bootstrap",
                "modules": dict(bootstrap.modules),
                "data": _plain(bootstrap.initial_data),
                "max_output_bytes": limits.max_output_bytes,
                "max_exports_per_cell": limits.max_exports_per_cell,
                "max_export_bytes": limits.max_export_bytes,
            }
        )
        if value != {"ready": True}:
            raise RuntimeError("Prime worker bootstrap failed")

    async def execute_cell(self, code: str, *, signal: object) -> Mapping[str, object]:
        if signal.cancelled:
            raise RuntimeError("Prime worker was cancelled")
        return await self._request({"operation": "execute", "code": code})

    async def restore(
        self, sources: tuple[str, ...], data: Mapping[str, object], *, signal: object
    ) -> None:
        if signal.cancelled:
            raise RuntimeError("Prime worker was cancelled")
        value = await self._request(
            {"operation": "restore", "sources": list(sources), "data": dict(data)}
        )
        if value != {"restored": True}:
            raise RuntimeError("Prime worker restore failed")

    async def _request(self, request: Mapping[str, object]) -> dict[str, object]:
        process = self._process
        channel = self._channel
        if (
            process is None
            or process.stdin is None
            or channel is None
            or process.returncode is not None
        ):
            raise RuntimeError("Prime worker is unavailable")
        process.stdin.write(
            (
                json.dumps(request, allow_nan=False, separators=(",", ":")) + "\n"
            ).encode()
        )
        await process.stdin.drain()
        while b"\n" not in self._pending:
            chunk = await asyncio.get_running_loop().sock_recv(channel, 65536)
            if not chunk:
                raise RuntimeError("Prime worker transport was lost")
            self._pending.extend(chunk)
            if len(self._pending) > self._response_limit:
                raise RuntimeError("Prime worker response exceeded limit")
        line, _, trailing = self._pending.partition(b"\n")
        self._pending = bytearray(trailing)
        value = json.loads(line)
        if type(value) is not dict:
            raise RuntimeError("Prime worker response was invalid")
        return value

    async def close(self) -> None:
        if self.closed:
            return
        process = self._process
        complete = False
        try:
            if process is not None:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    os.killpg(process.pid, process_signals.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 0.5)
                except asyncio.TimeoutError:
                    pass
                # The leader may already be reaped while descendants ignore
                # SIGTERM. Give the whole owned group a finite grace period.
                deadline = asyncio.get_running_loop().time() + 0.5
                while (
                    self._group_alive(process.pid)
                    and asyncio.get_running_loop().time() < deadline
                ):
                    await asyncio.sleep(0.01)
                try:
                    os.killpg(process.pid, process_signals.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                await asyncio.wait_for(process.wait(), 0.5)
                deadline = asyncio.get_running_loop().time() + 0.5
                while (
                    self._group_alive(process.pid)
                    and asyncio.get_running_loop().time() < deadline
                ):
                    await asyncio.sleep(0.01)
                if self._group_alive(process.pid):
                    raise RuntimeError("Prime worker process-group cleanup failed")
            complete = True
        finally:
            if process is not None and not complete:
                # Cleanup cancellation must still send the final group kill.
                try:
                    os.killpg(process.pid, process_signals.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            if self._channel is not None:
                self._channel.close()
                self._channel = None
            self.closed = complete

    @staticmethod
    def _group_alive(group: int) -> bool:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # macOS can report EPERM while a killed orphan is being reaped.
            # Keep waiting; this is never evidence of completed cleanup.
            return True
        return True


def _controller(descriptor: int) -> None:
    """Standalone stdlib cell loop; responses never travel over user stdout."""
    import ast
    import contextlib
    import io
    import math
    import re
    import traceback
    import types

    channel = socket.socket(fileno=descriptor)

    def respond(value: dict[str, object]) -> None:
        channel.sendall(
            (json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n").encode()
        )

    setup = json.loads(sys.stdin.readline())
    output_limit = setup["max_output_bytes"]
    export_limit = setup["max_export_bytes"]
    export_count_limit = setup["max_exports_per_cell"]
    namespace = {"__name__": "__prime_workspace__"}
    pending: list[dict[str, object]] = []
    accepting_exports = False

    class BoundedOutput(io.TextIOBase):
        def __init__(self) -> None:
            self.buffer = bytearray()

        def write(self, text: str) -> int:
            remaining = output_limit - len(self.buffer)
            if remaining > 0:
                self.buffer.extend(text.encode("utf-8", "replace")[:remaining])
            return len(text)

        def text(self) -> str:
            return self.buffer.decode("utf-8", "ignore")

    def validate_json(value: object, active: set[int] | None = None) -> None:
        if value is None or type(value) in {str, bool, int}:
            return
        if type(value) is float and math.isfinite(value):
            return
        if type(value) not in {dict, list}:
            raise ValueError("Export must contain finite JSON values")
        if active is None:
            active = set()
        if id(value) in active:
            raise ValueError("Export cannot contain cycles")
        active.add(id(value))
        try:
            if type(value) is dict:
                if any(type(key) is not str for key in value):
                    raise ValueError("Export JSON keys must be strings")
                children = value.values()
            else:
                children = value
            for item in children:
                validate_json(item, active)
        finally:
            active.remove(id(value))

    def export(name: str, value: object) -> None:
        if not accepting_exports:
            raise RuntimeError("Exports are only available during a cell")
        if (
            type(name) is not str
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", name) is None
        ):
            raise ValueError("Export name must be a simple identifier")
        if len(pending) >= export_count_limit or any(
            item["name"] == name for item in pending
        ):
            raise ValueError("Export count or duplicate name rejected")
        validate_json(value)
        # Round-trip now, so later namespace mutations cannot change candidates.
        encoded = json.dumps(
            value, allow_nan=False, ensure_ascii=True, separators=(",", ":")
        )
        if (
            len(encoded.encode())
            + sum(
                len(
                    json.dumps(
                        item["value"],
                        allow_nan=False,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode()
                )
                for item in pending
            )
            > export_limit
        ):
            raise ValueError("Export exceeds the configured size limit")
        pending.append(
            {
                "name": name,
                "kind": "text" if type(value) is str else "json",
                "value": json.loads(encoded),
            }
        )

    workspace_module = types.ModuleType("prime_workspace")
    workspace_module.export = export
    sys.modules["prime_workspace"] = workspace_module
    namespace["prime_workspace"] = workspace_module
    try:
        with (
            contextlib.redirect_stdout(BoundedOutput()),
            contextlib.redirect_stderr(BoundedOutput()),
        ):
            for name, source in setup["modules"].items():
                module = types.ModuleType(name)
                sys.modules[name] = module
                exec(
                    compile(source, "<prime-bootstrap-module>", "exec"),
                    module.__dict__,
                    module.__dict__,
                )
            namespace.update(setup["data"])
    except BaseException:
        respond({"ready": False})
        return
    respond({"ready": True})
    for raw in sys.stdin:
        request = json.loads(raw)
        output = BoundedOutput()
        pending.clear()
        if request["operation"] == "restore":
            try:
                with (
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(output),
                ):
                    for source in request["sources"]:
                        exec(
                            compile(source, "<prime-restored-source>", "exec"),
                            namespace,
                            namespace,
                        )
                    namespace.update(request["data"])
                respond({"restored": True})
            except BaseException:
                respond({"restored": False})
            continue
        is_error = False
        accepting_exports = True
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                tree = ast.parse(request["code"], "<prime-cell>", "exec")
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    prefix = ast.Module(body=tree.body[:-1], type_ignores=[])
                    ast.fix_missing_locations(prefix)
                    exec(compile(prefix, "<prime-cell>", "exec"), namespace, namespace)
                    expression = ast.Expression(tree.body[-1].value)
                    ast.fix_missing_locations(expression)
                    result = eval(
                        compile(expression, "<prime-cell>", "eval"),
                        namespace,
                        namespace,
                    )
                    if result is not None:
                        print(repr(result))
                else:
                    exec(compile(tree, "<prime-cell>", "exec"), namespace, namespace)
        except BaseException:
            is_error = True
            output.write(traceback.format_exc(limit=2))
        finally:
            accepting_exports = False
        respond(
            {
                "is_error": is_error,
                "output": output.text(),
                "exports": [] if is_error else pending,
            }
        )


if __name__ == "__main__":
    _controller(int(sys.argv[1]))


__all__ = ("SubprocessPythonWorker",)
