"""Serve the single-page grid regulation desk on localhost."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import webbrowser
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from asterion.applications.grid_regulation.answer import (
    GridResearch,
    UnavailableResearch,
    answer_fault,
)
from asterion.applications.grid_regulation.retrieve import (
    RegulationCitationError,
    RegulationQuery,
    cite_regulation,
)
from asterion.documents import DocumentToolError, read_span

_HOST = "127.0.0.1"
_TOOLS = frozenset({"docx", "pdf", "docx,pdf"})
_MAX_BODY = 64 * 1024
_PAGE = "text/html; charset=utf-8"
_JSON = "application/json; charset=utf-8"
_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class GridRegulationPageError(ValueError):
    """Raised when the local page cannot be served."""


def page_bytes() -> bytes:
    """Return the one HTML file shipped with this application."""

    return (
        files("asterion.applications.grid_regulation")
        .joinpath("page.html")
        .read_bytes()
    )


def corpus_index(root: Path) -> dict[str, object]:
    """List PDF and DOCX names under the corpus. No file text."""

    _directory(root)
    found: list[dict[str, object]] = []
    root_resolved = root.resolve()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        folder = Path(directory)
        dirnames[:] = [name for name in dirnames if not (folder / name).is_symlink()]
        for name in filenames:
            candidate = folder / name
            if candidate.is_symlink() or candidate.suffix.casefold() not in {
                ".docx",
                ".pdf",
            }:
                continue
            try:
                relative = candidate.resolve().relative_to(root_resolved).as_posix()
                size = candidate.stat().st_size
            except (OSError, ValueError):
                continue
            found.append(
                {
                    "document": relative,
                    "kind": candidate.suffix.casefold().lstrip("."),
                    "bytes": size,
                }
            )
    found.sort(key=lambda item: str(item["document"]))
    return {"root": str(root_resolved), "files": found}


async def cite_for_page(root: Path, payload: Mapping[str, object]) -> dict[str, object]:
    """Cite one clause and attach the span text for the operator page."""

    query = _query(payload)
    tools = payload.get("document_tools", "docx,pdf")
    if type(tools) is not str or tools not in _TOOLS:
        raise GridRegulationPageError("request is invalid")
    try:
        citation = await cite_regulation(root, query, document_tools=tools)
    except RegulationCitationError:
        raise GridRegulationPageError("regulation citation is unavailable") from None
    hits: list[dict[str, object]] = []
    for anchor in citation.anchors:
        try:
            text = read_span(root, anchor)
        except DocumentToolError:
            raise GridRegulationPageError(
                "regulation citation is unavailable"
            ) from None
        hits.append(
            {
                "document": anchor["document"],
                "kind": anchor["kind"],
                "position": anchor["position"],
                "text": text,
            }
        )
    return {
        "clause_id": citation.clause_id,
        "version": citation.version,
        "anchors": hits,
    }


async def measures_for_page(
    root: Path,
    payload: Mapping[str, object],
    *,
    research: GridResearch,
) -> dict[str, object]:
    """Return the research reply and the locations a passage read opened."""

    situation = payload.get("situation")
    document = payload.get("document", "")
    tools = payload.get("document_tools", "docx,pdf")
    if (
        type(situation) is not str
        or type(document) is not str
        or document == ""
        or type(tools) is not str
        or tools not in _TOOLS
    ):
        raise GridRegulationPageError("request is invalid")
    try:
        found = await answer_fault(
            root,
            document=document,
            question=situation,
            research=research,
            document_tools=tools,
        )
    except RegulationCitationError as exc:
        if str(exc) == "request is invalid":
            raise GridRegulationPageError("request is invalid") from None
        raise GridRegulationPageError("regulation measures are unavailable") from None
    return {
        "document": found.document,
        "reply": found.reply,
        "evidence": [dict(item) for item in found.evidence],
    }


def serve(
    root: Path,
    *,
    port: int = 0,
    research: GridResearch | None = None,
) -> _Server:
    """Bind a loopback server for one corpus directory."""

    _directory(root)
    if type(port) is not int or port < 0 or port > 65535:
        raise GridRegulationPageError("request is invalid")
    chosen = UnavailableResearch() if research is None else research
    return _Server(root.resolve(), port, chosen)


def main(argv: list[str] | None = None) -> int:
    """Serve the page until interrupted."""

    parser = argparse.ArgumentParser(description="Open the grid regulation page.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv

    from asterion.applications.grid_regulation.live import (
        LiveGridResearch,
        operator_evidence_root,
        repository_root,
    )

    try:
        repo = repository_root()
        env_file = repo / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
        server = serve(
            args.corpus,
            port=args.port,
            research=LiveGridResearch(
                os.environ,
                evidence_root=operator_evidence_root(repo),
                repo=repo,
            ),
        )
    except (GridRegulationPageError, RegulationCitationError):
        return 2
    url = f"http://{_HOST}:{server.server_address[1]}/"
    print(url)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


class _Server(ThreadingHTTPServer):
    def __init__(self, corpus: Path, port: int, research: GridResearch) -> None:
        super().__init__((_HOST, port), _Handler)
        self.corpus = corpus
        self.research = research


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, _PAGE, page_bytes())
            return
        if path == "/api/corpus":
            self._json(200, corpus_index(self._corpus()))
            return
        self._json(404, {"error": "not-found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/cite", "/api/measures"}:
            self._json(404, {"error": "not-found"})
            return
        try:
            payload = _payload(self)
            if path == "/api/cite":
                body = asyncio.run(cite_for_page(self._corpus(), payload))
            else:
                body = asyncio.run(
                    measures_for_page(
                        self._corpus(),
                        payload,
                        research=self._research(),
                    )
                )
        except GridRegulationPageError as exc:
            status = 400 if str(exc) == "request is invalid" else 422
            self._json(status, {"error": str(exc)})
            return
        self._json(200, body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _json(self, status: int, payload: Mapping[str, object]) -> None:
        self._send(
            status,
            _JSON,
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(),
        )

    def _send(self, status: int, media_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _corpus(self) -> Path:
        return self._server().corpus

    def _research(self) -> GridResearch:
        return self._server().research

    def _server(self) -> _Server:
        if not isinstance(self.server, _Server):
            raise GridRegulationPageError("request is invalid")
        return self.server


def _directory(root: Path) -> None:
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise GridRegulationPageError("request is invalid")


def _query(payload: Mapping[str, object]) -> RegulationQuery:
    clause_id = payload.get("clause_id")
    version = payload.get("version")
    finding = payload.get("finding")
    if (
        type(clause_id) is not str
        or type(version) is not str
        or type(finding) is not str
    ):
        raise GridRegulationPageError("request is invalid")
    return RegulationQuery(clause_id, version, finding)


def _payload(handler: BaseHTTPRequestHandler) -> Mapping[str, object]:
    raw_length = handler.headers.get("Content-Length", "")
    try:
        length = int(raw_length)
    except ValueError:
        raise GridRegulationPageError("request is invalid") from None
    if length < 0 or length > _MAX_BODY:
        raise GridRegulationPageError("request is invalid")
    try:
        payload = json.loads(handler.rfile.read(length).decode())
    except (UnicodeError, json.JSONDecodeError):
        raise GridRegulationPageError("request is invalid") from None
    if not isinstance(payload, dict):
        raise GridRegulationPageError("request is invalid")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
