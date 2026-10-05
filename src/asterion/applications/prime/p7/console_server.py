"""Same-origin loopback HTTP controls for the single P7 console session."""

from __future__ import annotations

from collections.abc import Callable
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import signal
import threading
import webbrowser

from .console_export import render_console
from .console_session import ConsoleSession, ConsoleSessionError


_MAX_BODY = 4096
_JSON = "application/json; charset=utf-8"
_SECURITY = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
             "X-Content-Type-Options": "nosniff"}
_CSP = "default-src 'none'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"


def _empty_snapshot() -> dict:
    return {"schema": "asterion.arc-agi3-p7-console/v1", "generated_at": None,
            "run": {"run_id": None, "game_id": None, "status": "incomplete",
                    "completed_level_count": 0, "win_levels": None, "target_level": 1,
                    "primitive_action_count": 0, "replay_verified": False,
                    "sealed_trace": False, "model": None},
            "levels": [], "decisions": [], "warnings": []}


class ConsoleHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session: ConsoleSession, renderer: Callable, port: int) -> None:
        self.session = session
        self.renderer = renderer
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), _Handler)
        self.expected_host = f"127.0.0.1:{self.server_port}"
        self.origin = "http://" + self.expected_host

    def server_close(self) -> None:
        try:
            self.session.close()
        finally:
            super().server_close()


class _Handler(BaseHTTPRequestHandler):
    server: ConsoleHTTPServer

    def log_message(self, _format: str, *args: object) -> None:
        pass

    def _send(self, status: int, value: object, *, html: bool = False) -> None:
        if html:
            body = str(value).encode("utf-8")
            # The renderer hashes its actual inline scripts/styles. Reuse that
            # policy for the HTTP response rather than blocking those hashes.
            match = re.search(r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"', str(value))
            csp = unescape(match[1]) + "; frame-ancestors 'none'" if match else _CSP
        else:
            body = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            csp = _CSP
        self.send_response(status)
        for name, content in _SECURITY.items():
            self.send_header(name, content)
        self.send_header("Content-Security-Policy", csp)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else _JSON)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, status: int, code: str) -> None:
        self._send(status, {"error": code})

    def _valid_request(self) -> bool:
        if self.headers.get_all("Host") != [self.server.expected_host]:
            self._error(403, "host-rejected")
            return False
        if (len(self.path) > 256 or not self.path.startswith("/") or self.path.startswith("//")
                or any(token in self.path for token in ("%", "?", "#", "\\", "..", "\x00"))):
            self._error(404, "not-found")
            return False
        return True

    def do_GET(self) -> None:
        if not self._valid_request():
            return
        try:
            session = self.server.session
            if self.path == "/":
                view = session.view()
                page = self.server.renderer(view["snapshot"] or _empty_snapshot(),
                                            live_config={"token": self.server.token, "games": session.games()})
                self._send(200, page, html=True)
            elif self.path == "/api/state":
                self._send(200, session.view())
            elif self.path == "/api/games":
                self._send(200, {"games": session.games()})
            elif self.path == "/api/runs":
                self._send(200, {"runs": session.recorded_runs()})
            elif self.path.startswith("/api/replay/"):
                self._send(200, session.replay(self.path.removeprefix("/api/replay/")))
            else:
                self._error(404, "not-found")
        except ConsoleSessionError:
            self._error(404, "run-unavailable")
        except Exception:
            self._error(503, "console-unavailable")

    def do_POST(self) -> None:
        if not self._valid_request():
            return
        token = self.headers.get("X-P7-Console-Token", "")
        if (self.headers.get_all("Origin") != [self.server.origin]
                or len(self.headers.get_all("X-P7-Console-Token") or []) != 1
                or not token.isascii()
                or not secrets.compare_digest(token, self.server.token)):
            self._error(403, "write-rejected")
            return
        if self.path not in {"/api/start", "/api/stop", "/api/manual/open", "/api/manual/action",
                             "/api/manual/close", "/api/manual/restart"}:
            self._error(404, "not-found")
            return
        if (self.headers.get_all("Content-Type") != ["application/json"]
                or self.headers.get_all("Transfer-Encoding") is not None
                or len(self.headers.get_all("Content-Length") or []) != 1):
            self._error(400, "request-invalid")
            return
        try:
            size = int(self.headers["Content-Length"])
            if not 0 < size <= _MAX_BODY:
                raise ValueError
            self.connection.settimeout(2)
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError
            # Duplicate JSON keys are ambiguous write commands.
            def pairs(items):
                value = dict(items)
                if len(value) != len(items):
                    raise ValueError
                return value
            value = json.loads(raw, object_pairs_hook=pairs)
            keys = ({"game_id", "command_id"} if self.path in {"/api/start", "/api/manual/open"}
                    else {"session_id", "command_id", "observation_version", "action", "data"}
                    if self.path == "/api/manual/action"
                    else {"session_id", "command_id", "observation_version"}
                    if self.path == "/api/manual/restart" else {"session_id", "command_id"})
            if type(value) is not dict or (set(value) != keys
                    and not (self.path == "/api/manual/open" and set(value) == keys | {"level"})):
                raise ValueError
            if any(type(v) is not str for key, v in value.items() if key not in {"observation_version", "data", "level"}):
                raise ValueError
            if "level" in value and type(value["level"]) is not int:
                raise ValueError
            if "observation_version" in value and (
                    type(value["observation_version"]) is not int or value["observation_version"] < 0):
                raise ValueError
            if self.path == "/api/manual/action" and type(value["data"]) is not dict:
                raise ValueError
        except (ValueError, OSError, UnicodeError, RecursionError):
            self._error(400, "request-invalid")
            return
        try:
            if self.path == "/api/start":
                result = self.server.session.start(value["game_id"], value["command_id"])
            elif self.path == "/api/stop":
                result = self.server.session.stop(value["session_id"], value["command_id"])
            elif self.path == "/api/manual/open":
                result = self.server.session.manual_open(value["game_id"], value["command_id"], value.get("level", 1))
            elif self.path == "/api/manual/action":
                result = self.server.session.manual_action(value["session_id"], value["command_id"],
                                                         value["observation_version"], value["action"], value["data"])
            elif self.path == "/api/manual/restart":
                result = self.server.session.manual_restart(value["session_id"], value["command_id"],
                                                          value["observation_version"])
            else:
                result = self.server.session.manual_close(value["session_id"], value["command_id"])
            self._send(200 if self.path.startswith("/api/manual/") else 202, result)
        except ConsoleSessionError as error:
            self._error(409, str(error))
        except Exception:
            self._error(503, "console-unavailable")


def create_console_server(session: ConsoleSession, *, renderer: Callable = render_console,
                          port: int = 0) -> ConsoleHTTPServer:
    if type(port) is not int or not 0 <= port <= 65535:
        raise ConsoleSessionError("console-unavailable")
    return ConsoleHTTPServer(session, renderer, port)


def serve_console(operator_root: Path, arc_root: Path, *, guest_machine: str = "ubuntu",
                  open_browser: bool = False, on_ready: Callable[[str], None] | None = None) -> None:
    session = ConsoleSession(operator_root, arc_root, guest_machine=guest_machine)
    server = create_console_server(session)
    previous = {}

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, interrupt)
        url = server.origin + "/"
        if on_ready is not None:
            on_ready(url)
        if open_browser:
            webbrowser.open(url, new=2)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        # Ignore repeated process interrupts while the finite guest cleanup is
        # in progress. Restore the enclosing host's handlers afterward.
        for signum in previous:
            signal.signal(signum, signal.SIG_IGN)
        try:
            server.server_close()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


__all__ = ("create_console_server", "serve_console")
