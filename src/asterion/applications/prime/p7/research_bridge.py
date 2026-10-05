"""Read-only evidence transport; its server allowlist has no action route."""

from __future__ import annotations

import json
import secrets
import socketserver
import threading

from .research import copy_json


class ResearchReadServer:
    def __init__(self, *, context, history, frame, artifact):
        callbacks = {
            "context": context,
            "history": history,
            "frame": frame,
            "artifact": artifact,
        }
        if any(not callable(callback) for callback in callbacks.values()):
            raise ValueError("research readers unavailable")
        self._readers = callbacks
        self._server = None
        self._thread = None
        self._closed = False
        self._token = secrets.token_hex(32)

    def dispatch(self, request: object) -> dict:
        try:
            if (
                self._closed
                or type(request) is not dict
                or set(request) != {"method", "args"}
            ):
                raise ValueError
            method, args = request["method"], request["args"]
            if (
                type(method) is not str
                or method not in self._readers
                or type(args) is not list
            ):
                raise ValueError
            if method == "context":
                if args:
                    raise ValueError
            elif method == "history":
                if (
                    len(args) != 2
                    or any(type(v) is not int for v in args)
                    or args[0] < 0
                    or not 1 <= args[1] <= 32
                ):
                    raise ValueError
            elif method == "frame":
                if len(args) != 1 or type(args[0]) is not int or args[0] < 0:
                    raise ValueError
            elif len(args) != 1 or type(args[0]) is not str or len(args[0]) != 71:
                raise ValueError
            return {"status": "ok", "value": copy_json(self._readers[method](*args))}
        except Exception:
            return {"status": "rejected", "reason": "read-unavailable"}

    def start(self) -> str:
        if self._closed:
            raise ValueError("research readers closed")
        if self._server is None:
            owner = self

            class Handler(socketserver.StreamRequestHandler):
                def handle(self):
                    self.connection.settimeout(5)
                    try:
                        line = self.rfile.readline(65537)
                        request = json.loads(line)
                        if (
                            len(line) > 65536
                            or type(request) is not dict
                            or set(request) != {"token", "request"}
                            or request["token"] != owner._token
                        ):
                            raise ValueError
                        result = owner.dispatch(request["request"])
                    except Exception:
                        result = {"status": "rejected", "reason": "read-unavailable"}
                    self.wfile.write(
                        json.dumps(
                            result, allow_nan=False, separators=(",", ":")
                        ).encode()
                        + b"\n"
                    )

            class Server(socketserver.ThreadingTCPServer):
                daemon_threads = True

            self._server = Server(("127.0.0.1", 0), Handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True
            )
            self._thread.start()
        address = self._server.server_address
        return f'''"""Host evidence snapshots; no environment action methods."""
import json as _json
import socket as _socket
def _read(method, args):
    with _socket.create_connection({address!r}, timeout=5) as connection:
        connection.sendall((_json.dumps({{"token": {self._token!r}, "request": {{"method": method, "args": args}}}}, allow_nan=False) + "\\n").encode())
        stream = connection.makefile("rb")
        raw = stream.readline(1048577)
        if len(raw) > 1048576:
            raise ValueError("research response unavailable")
        result = _json.loads(raw)
        if result.get("status") != "ok":
            raise ValueError("research read rejected")
        return result["value"]
def context(): return _read("context", [])
def history(start, limit): return _read("history", [start, limit])
def frame(sequence): return _read("frame", [sequence])
def artifact(export_id): return _read("artifact", [export_id])
'''

    def close(self) -> None:
        self._closed = True
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
