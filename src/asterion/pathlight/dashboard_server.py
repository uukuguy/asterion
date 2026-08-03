"""Loopback-only, read-only HTTP delivery for the Pathlight Dashboard."""

from __future__ import annotations

import json
import re
import socket
import webbrowser
from collections.abc import Mapping
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from types import MappingProxyType

from asterion.pathlight.dashboard import (
    DashboardSnapshot,
    validate_dashboard_snapshot,
)
from asterion.pathlight.protocol import PathlightError


_API_PREFIX = "/api/pathlight/v1"
_TRACE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_READ_METHODS = frozenset({"GET", "HEAD"})
_ASSETS = MappingProxyType(
    {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    }
)
_FIXED_HEADERS = MappingProxyType(
    {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
        ),
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
)


@dataclass(frozen=True, slots=True)
class DashboardResponse:
    """One fully rendered response without access to server state."""

    status: int
    media_type: str
    headers: Mapping[str, str]
    body: bytes


class DashboardApplication:
    """Pure request dispatch over one immutable Dashboard snapshot."""

    def __init__(self, snapshot: DashboardSnapshot) -> None:
        if type(snapshot) is not DashboardSnapshot:
            raise PathlightError("Pathlight Dashboard application is invalid")
        self._snapshot = validate_dashboard_snapshot(snapshot.to_mapping())

    def response(self, method: str, target: str) -> DashboardResponse:
        """Return a fixed safe response for one exact same-origin target."""

        try:
            if type(method) is not str or type(target) is not str:
                raise ValueError
            if method not in _READ_METHODS:
                return _response(method, 405, {"error": "method-not-allowed"})
            if target in _ASSETS:
                return _asset_response(method, target)
            value = self._route(target)
            rendered = _response(method, 200, value)
            return rendered
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return _response(
                method if type(method) is str else "GET", 404, {"error": "not-found"}
            )

    def _route(self, target: str) -> object:
        if not _valid_target(target):
            raise ValueError
        mapping = self._snapshot.to_mapping()
        exact = {
            f"{_API_PREFIX}/snapshot": mapping,
            f"{_API_PREFIX}/summary": mapping["summary"],
            f"{_API_PREFIX}/traces": mapping["traces"],
            f"{_API_PREFIX}/evaluations": mapping["evaluations"],
            f"{_API_PREFIX}/experiments": mapping["experiments"],
            f"{_API_PREFIX}/diagnoses": mapping["diagnoses"],
        }
        if target in exact:
            return exact[target]
        prefix = f"{_API_PREFIX}/traces/"
        if not target.startswith(prefix):
            raise ValueError
        suffix = target[len(prefix) :]
        flow = suffix.endswith("/flow")
        trace_id = suffix[:-5] if flow else suffix
        if _TRACE_ID.fullmatch(trace_id) is None:
            raise ValueError
        collection = mapping["flows"] if flow else mapping["traces"]
        if not isinstance(collection, list):
            raise ValueError
        for item in collection:
            if isinstance(item, Mapping) and item.get("trace_id") == trace_id:
                return item
        raise ValueError


def validate_dashboard_bind(host: str, port: int) -> tuple[str, int]:
    """Reject non-loopback addresses and invalid ports before socket creation."""

    if (
        type(host) is not str
        or host not in _LOOPBACK_HOSTS
        or type(port) is not int
        or not 0 <= port <= 65535
    ):
        raise PathlightError("Pathlight Dashboard bind is invalid")
    return host, port


def serve_dashboard(
    snapshot: DashboardSnapshot,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = False,
    on_ready: Callable[[str], None] | None = None,
) -> None:
    """Serve one validated snapshot in the foreground until interrupted."""

    checked_host, checked_port = validate_dashboard_bind(host, port)
    if type(open_browser) is not bool or (
        on_ready is not None and not callable(on_ready)
    ):
        raise PathlightError("Pathlight Dashboard launch is invalid")
    application = DashboardApplication(snapshot)
    handler = _handler_for(application)
    server_type: type[ThreadingHTTPServer] = (
        _IPv6ThreadingHTTPServer if checked_host == "::1" else ThreadingHTTPServer
    )
    server = server_type((checked_host, checked_port), handler)
    try:
        address = "[::1]" if checked_host == "::1" else checked_host
        url = f"http://{address}:{server.server_address[1]}/"
        if on_ready is not None:
            on_ready(url)
        if open_browser:
            webbrowser.open(url, new=2)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _valid_target(target: str) -> bool:
    return (
        0 < len(target) <= 2048
        and target.startswith("/")
        and not target.startswith("//")
        and all(value not in target for value in ("?", "#", "%", "\\", "\x00"))
        and ".." not in target.split("/")
    )


def _response(method: str, status: int, value: object) -> DashboardResponse:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _body_response(
        method,
        status,
        "application/json; charset=utf-8",
        body,
    )


def _asset_response(method: str, target: str) -> DashboardResponse:
    name, media_type = _ASSETS[target]
    body = files("asterion.pathlight").joinpath("dashboard_assets", name).read_bytes()
    return _body_response(method, 200, media_type, body)


def _body_response(
    method: str, status: int, media_type: str, body: bytes
) -> DashboardResponse:
    headers = {
        **_FIXED_HEADERS,
        "Content-Length": str(len(body)),
    }
    if status == 405:
        headers["Allow"] = "GET, HEAD"
    return DashboardResponse(
        status=status,
        media_type=media_type,
        headers=MappingProxyType(headers),
        body=b"" if method == "HEAD" else body,
    )


def _handler_for(application: DashboardApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "Asterion-Pathlight"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

        def do_GET(self) -> None:  # noqa: N802
            self._send(application.response("GET", self.path))

        def do_HEAD(self) -> None:  # noqa: N802
            self._send(application.response("HEAD", self.path))

        def do_POST(self) -> None:  # noqa: N802
            self._send(application.response("POST", self.path))

        def do_PUT(self) -> None:  # noqa: N802
            self._send(application.response("PUT", self.path))

        def do_PATCH(self) -> None:  # noqa: N802
            self._send(application.response("PATCH", self.path))

        def do_DELETE(self) -> None:  # noqa: N802
            self._send(application.response("DELETE", self.path))

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(application.response("OPTIONS", self.path))

        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _send(self, response: DashboardResponse) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.media_type)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            if response.body:
                self.wfile.write(response.body)

    return Handler


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
