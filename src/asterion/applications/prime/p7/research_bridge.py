"""Read-only evidence transport; its server allowlist has no action route."""

from __future__ import annotations

import json
import secrets
import socketserver
import threading

from .dynamic_evidence import EvidenceProcessingError
from .processing_diagnostics import public_diagnostic


class ResearchReadServer:
    def __init__(self, *, context, history, frame, artifact, experience=None, animation=None, diagnostic_sink=None):
        callbacks = {
            "context": context,
            "history": history,
            "frame": frame,
            "artifact": artifact,
        }
        if any(not callable(callback) for callback in callbacks.values()):
            raise ValueError("research readers unavailable")
        if experience is not None:
            if not callable(experience):
                raise ValueError("research readers unavailable")
            callbacks["experience"] = experience
        if animation is not None:
            if not callable(animation):
                raise ValueError('research readers unavailable')
            callbacks['animation'] = animation
        self._readers = callbacks
        self._server = None
        self._thread = None
        self._closed = False
        self._token = secrets.token_hex(32)
        self._diagnostic_sink = diagnostic_sink

    def _rejection(self, code, *, observed=None):
        diagnostic = public_diagnostic(dict(
            diagnostic_id=f'{code}:derived-failed:0', code=code, severity='warning',
            stage='derived-failed', action_sequence=0, outcome_known=True, durable=False,
            observed=observed, limit=1048576 if observed is not None else None,
            unit='bytes' if observed is not None else None, recovery='fix-request' if observed is not None else 'retry-read'))
        if callable(self._diagnostic_sink):
            self._diagnostic_sink(diagnostic)
        return {'status': 'rejected', 'reason': 'read-unavailable', 'diagnostic': diagnostic}

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
            elif method == 'animation':
                if (len(args) != 3 or type(args[0]) is not dict
                        or type(args[1]) is not int or args[1] < 0
                        or type(args[2]) is not int or not 1 <= args[2] <= 32):
                    raise ValueError
            elif method == "experience":
                if (len(args) != 5 or type(args[0]) is not str or len(args[0]) > 160
                        or type(args[1]) is not str or args[1] not in {"index", "research", "history", "frame", "animation", "artifact", "cells"}
                        or type(args[2]) is not int or args[2] < 0
                        or type(args[3]) is not int or not 1 <= args[3] <= 32
                        or (args[4] is not None and (type(args[4]) is not str or len(args[4]) != 71))):
                    raise ValueError
            elif len(args) != 1 or type(args[0]) is not str or len(args[0]) != 71:
                raise ValueError
            result = {"status": "ok", "value": self._readers[method](*args)}
            encoded = json.dumps(result, allow_nan=False, separators=(',', ':')).encode() + b'\n'
            if len(encoded) > 1048576:
                return self._rejection('research-response-budget-exceeded', observed=len(encoded))
            return json.loads(encoded)
        except EvidenceProcessingError as error:
            diagnostic = public_diagnostic(error.diagnostic)
            if callable(self._diagnostic_sink):
                self._diagnostic_sink(diagnostic)
            return {'status': 'rejected', 'reason': 'read-unavailable', 'diagnostic': diagnostic}
        except Exception:
            return self._rejection('research-read-failed')

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
def animation(observation_ref, start=0, limit=32):
    """Read animation pages for one exact committed current-run observation."""
    return _read("animation", [observation_ref, start, limit])
def artifact(export_id): return _read("artifact", [export_id])
def experience(source_run_id, kind, start=0, limit=32, artifact_id=None):
    return _read("experience", [source_run_id, kind, start, limit, artifact_id])
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
