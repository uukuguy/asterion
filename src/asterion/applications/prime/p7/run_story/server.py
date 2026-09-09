"""Loopback-only read-only server for the ARC run-story catalog."""

from __future__ import annotations

import json
import mimetypes
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from .model import RunStoryError


_LOOPBACK = {"127.0.0.1", "::1"}
_SECURITY = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_INDEX = """<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>ARC-AGI-3 Run Stories</title><link rel=\"stylesheet\" href=\"/_catalog.css\"></head><body><main><h1>ARC-AGI-3</h1><p>Asterion Prime 解题制品目录</p><section id=\"runs\">正在读取制品…</section></main><script src=\"/_catalog.js\"></script></body></html>""".encode("utf-8")
_CATALOG_CSS = """body{margin:0;background:#07101c;color:#edf3f9;font:16px system-ui;padding:42px}main{max-width:980px;margin:auto}h1{font-size:52px;letter-spacing:-.04em}article{border-top:1px solid #29384e;padding:20px 0}a{color:#78d9e8}small{color:#91a3b7}""".encode("utf-8")
_CATALOG_JS = """fetch('/catalog.json',{cache:'no-store'}).then(r=>r.json()).then(c=>{const root=document.querySelector('#runs');root.textContent='';for(const run of c.runs){const card=document.createElement('article');const title=document.createElement('h2');title.textContent=run.game_id+' / '+run.run_id;card.append(title);const meta=document.createElement('small');meta.textContent=run.verification;card.append(meta);for(const render of run.renders||[]){const p=document.createElement('p'),a=document.createElement('a');a.href='/'+render.path;a.textContent='打开 '+render.render_id;p.append(a);card.append(p)}root.append(card)}if(!c.runs.length)root.textContent='尚无解题制品。'}).catch(()=>{document.querySelector('#runs').textContent='制品目录不可用。'});""".encode("utf-8")


@dataclass(frozen=True, slots=True)
class ArtifactResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


def _response(method: str, status: int, media_type: str, body: bytes) -> ArtifactResponse:
    headers = MappingProxyType(
        {**_SECURITY, "Content-Type": media_type, "Content-Length": str(len(body))}
    )
    return ArtifactResponse(status, headers, b"" if method == "HEAD" else body)


def _error(method: str, status: int, name: str) -> ArtifactResponse:
    return _response(
        method,
        status,
        "application/json; charset=utf-8",
        (json.dumps({"error": name}, separators=(",", ":")) + "\n").encode(),
    )


def validate_bind(host: str, port: int) -> tuple[str, int]:
    if host not in _LOOPBACK or type(port) is not int or not 0 <= port <= 65535:
        raise RunStoryError("server-bind-invalid")
    return host, port


def _valid_target(target: str) -> bool:
    return (
        type(target) is str
        and 0 < len(target) <= 2048
        and target.startswith("/")
        and not target.startswith("//")
        and all(value not in target for value in ("%", "?", "#", "\\", "\x00"))
        and ".." not in PurePosixPath(target).parts
    )


class ArtifactApplication:
    def __init__(self, artifact_root: Path) -> None:
        if artifact_root.is_symlink() or not artifact_root.is_dir():
            raise RunStoryError("artifact-root-invalid")
        self._root = artifact_root.resolve()

    def handle(self, method: str, target: str) -> ArtifactResponse:
        if method not in {"GET", "HEAD"}:
            return _error(method, 405, "method-not-allowed")
        if not _valid_target(target):
            return _error(method, 404, "not-found")
        if target == "/":
            return _response(method, 200, "text/html; charset=utf-8", _INDEX)
        if target == "/_catalog.js":
            return _response(method, 200, "text/javascript; charset=utf-8", _CATALOG_JS)
        if target == "/_catalog.css":
            return _response(method, 200, "text/css; charset=utf-8", _CATALOG_CSS)
        relative = PurePosixPath(target.removeprefix("/"))
        path = self._root.joinpath(*relative.parts)
        cursor = self._root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return _error(method, 404, "not-found")
        if not path.is_file():
            return _error(method, 404, "not-found")
        try:
            body = path.read_bytes()
        except OSError:
            return _error(method, 404, "not-found")
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if media.startswith("text/") or media in {"application/json", "application/javascript"}:
            media += "; charset=utf-8"
        return _response(method, 200, media, body)


def _handler_for(application: ArtifactApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._send(application.handle("GET", self.path))

        def do_HEAD(self) -> None:
            self._send(application.handle("HEAD", self.path))

        def do_POST(self) -> None:
            self._send(application.handle("POST", self.path))

        def _send(self, response: ArtifactResponse) -> None:
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            if response.body:
                self.wfile.write(response.body)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return Handler


def serve_artifacts(
    artifact_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = False,
    on_ready: Callable[[str], None] | None = None,
) -> None:
    host, port = validate_bind(host, port)
    application = ArtifactApplication(artifact_root)
    server = ThreadingHTTPServer((host, port), _handler_for(application))
    try:
        url = f"http://{host}:{server.server_address[1]}/"
        if on_ready is not None:
            on_ready(url)
        if open_browser:
            webbrowser.open(url, new=2)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = (
    "ArtifactApplication",
    "ArtifactResponse",
    "serve_artifacts",
    "validate_bind",
)
