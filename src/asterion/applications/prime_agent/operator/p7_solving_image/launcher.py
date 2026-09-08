#!/usr/local/bin/python
"""Persistent, local-only IPython cell server for the P7 solve image."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
from types import ModuleType
from typing import NoReturn

from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output

_SOCKET = Path("/workspace/kernel.sock")
_FRAME_CAP = 65536
_CELL_CAP = 16 * 1024
_OUTPUT_CAP = 4096
_CELL_LIMIT = 128


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _unavailable() -> NoReturn:
    raise RuntimeError("P7 solve worker is unavailable")


def _bounded(value: str) -> str:
    encoded = value.encode("utf-8", "replace")[:_OUTPUT_CAP]
    return encoded.decode("utf-8", "ignore")


def _read_exact(connection: socket.socket, size: int) -> bytes:
    if size < 0 or size > _FRAME_CAP:
        _unavailable()
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            _unavailable()
        data.extend(chunk)
    return bytes(data)


def _read_request(connection: socket.socket) -> str:
    size = struct.unpack("!I", _read_exact(connection, 4))[0]
    raw = _read_exact(connection, size)
    try:
        value = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        _unavailable()
    if type(value) is not dict or set(value) != {"code"} or type(value["code"]) is not str or _canonical(value) != raw or len(value["code"].encode()) > _CELL_CAP:
        _unavailable()
    return value["code"]


def _write_response(connection: socket.socket, value: dict[str, object]) -> None:
    raw = _canonical(value)
    if len(raw) > _FRAME_CAP:
        _unavailable()
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def _execute(shell: InteractiveShell, code: str, count: int) -> dict[str, object]:
    try:
        with capture_output() as captured:
            result = shell.run_cell(code, store_history=False)
        failed = result.error_before_exec is not None or result.error_in_exec is not None
        output = (
            "cell execution failed"
            if failed
            else _bounded(
                captured.stdout
                + captured.stderr
                + "".join(str(item) for item in captured.outputs)
            )
        )
        return {"cell_count": count, "is_error": failed, "output": output}
    except BaseException:
        return {"cell_count": count, "is_error": True, "output": "cell execution failed"}


def _load_client() -> None:
    # Load only the host-seeded module; never add the writable workspace to sys.path.
    path = "/workspace/p7_client.py"
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            _unavailable()
        source = stream.read(_CELL_CAP + 1)
    if not source or len(source) > _CELL_CAP:
        _unavailable()
    module = ModuleType("p7_client")
    module.__file__ = path
    exec(compile(source, path, "exec"), module.__dict__)
    sys.modules["p7_client"] = module


def serve() -> None:
    listener: socket.socket | None = None
    try:
        if _SOCKET.exists() or _SOCKET.is_symlink():
            _unavailable()
        _load_client()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(_SOCKET))
        os.chmod(_SOCKET, 0o600)
        listener.listen(1)
        shell, count = InteractiveShell(), 0
        while count < _CELL_LIMIT:
            connection, _ = listener.accept()
            with connection:
                try:
                    code = _read_request(connection)
                    count += 1
                    _write_response(connection, _execute(shell, code, count))
                except BaseException:
                    _write_response(connection, {"cell_count": count, "is_error": True, "output": "cell execution failed"})
    finally:
        if listener is not None:
            listener.close()
        try:
            _SOCKET.unlink()
        except OSError:
            pass


def client(encoded: str) -> int:
    try:
        code = base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8", "strict")
        if not code or len(code.encode()) > _CELL_CAP:
            _unavailable()
        raw = _canonical({"code": code})
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(_SOCKET))
            connection.sendall(struct.pack("!I", len(raw)) + raw)
            raw_result = _read_exact(connection, struct.unpack("!I", _read_exact(connection, 4))[0])
            result = json.loads(raw_result.decode("utf-8", "strict"))
        if type(result) is not dict or _canonical(result) != raw_result or set(result) != {"cell_count", "is_error", "output"} or type(result["cell_count"]) is not int or type(result["is_error"]) is not bool or type(result["output"]) is not str:
            _unavailable()
        sys.stdout.buffer.write(_canonical(result))
        return 0
    except BaseException:
        return 1


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--client":
        return client(sys.argv[2])
    if len(sys.argv) == 1:
        serve()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
