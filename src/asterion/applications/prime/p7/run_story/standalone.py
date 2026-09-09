"""Build one self-contained, offline ARC run-story HTML file."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .model import RunStoryError
from .storage import digest_bytes, safe_id, write_atomic_file


@dataclass(frozen=True, slots=True)
class StandaloneExport:
    path: Path
    sha256: str
    render_id: str


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RunStoryError("export-invalid")
    try:
        return path.read_bytes()
    except OSError:
        raise RunStoryError("export-invalid") from None


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(_read(path).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise RunStoryError("export-invalid") from None
    if not isinstance(value, dict):
        raise RunStoryError("export-invalid")
    return value


def _inline_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _csp_hash(value: str) -> str:
    digest = sha256(value.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def export_standalone(render_root: Path, output_root: Path) -> StandaloneExport:
    """Export a validated web render as one deterministic offline HTML file."""

    render_root = render_root.resolve(strict=True)
    manifest = _json(render_root / "render.json")
    render_id = safe_id(str(manifest.get("render_id", "")))
    if render_root.name != render_id:
        raise RunStoryError("export-invalid")
    bundle_root = render_root.parents[2]
    data = manifest.get("data")
    analysis = manifest.get("analysis")
    if not isinstance(data, dict) or not isinstance(analysis, dict):
        raise RunStoryError("export-invalid")
    references = [*data.values(), analysis.get("story")]
    if any(type(reference) is not str for reference in references):
        raise RunStoryError("export-invalid")
    embedded: dict[str, str] = {
        "render.json": json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    }
    for reference in references:
        assert isinstance(reference, str)
        path = (render_root / reference).resolve(strict=True)
        if not path.is_relative_to(bundle_root):
            raise RunStoryError("export-invalid")
        embedded[reference] = _read(path).decode("utf-8")

    html = _read(render_root / "index.html").decode("utf-8")
    css = _read(render_root / "assets" / "styles.css").decode("utf-8")
    app = _read(render_root / "assets" / "app.js").decode("utf-8")
    image = base64.b64encode(_read(render_root / "assets" / "header-art.png")).decode("ascii")
    bootstrap = (
        "const __ASTERION_EMBEDDED__=Object.freeze("
        + _inline_json(embedded)
        + ");window.fetch=async input=>{const key=typeof input==='string'?input:input.url;"
        "return Object.prototype.hasOwnProperty.call(__ASTERION_EMBEDDED__,key)"
        "?new Response(__ASTERION_EMBEDDED__[key],{status:200,headers:{'Content-Type':'application/json;charset=utf-8'}})"
        ":new Response('',{status:404});};"
    )
    csp = (
        "default-src 'none'; img-src data:; style-src '"
        + _csp_hash(css)
        + "'; script-src '"
        + _csp_hash(bootstrap)
        + "' '"
        + _csp_hash(app)
        + "'; base-uri 'none'; frame-ancestors 'none'"
    )
    html = html.replace(
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'  <meta http-equiv="Content-Security-Policy" content="{csp}">',
    )
    html = html.replace('<link rel="stylesheet" href="assets/styles.css">', f"<style>{css}</style>")
    html = html.replace(
        'src="assets/header-art.png"',
        f'src="data:image/png;base64,{image}"',
    )
    html = html.replace(
        '<script src="assets/app.js"></script>',
        f"<script>{bootstrap}</script>\n<script>{app}</script>",
    )
    if 'src="assets/' in html or 'href="assets/' in html:
        raise RunStoryError("export-invalid")

    run = _json(bundle_root / "data" / "run.json")
    game_id = safe_id(str(run.get("game_id", "")))
    run_id = safe_id(str(run.get("run_id", "")))
    payload = html.encode("utf-8")
    destination = output_root / f"arc-agi-3-{game_id}-{run_id}-{render_id}.html"
    write_atomic_file(destination, payload)
    return StandaloneExport(destination, digest_bytes(payload), render_id)


__all__ = ("StandaloneExport", "export_standalone")
