"""Provider-free web rendering for one validated run-story bundle."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from .model import RunStoryError, SCHEMA, canonical_json, content_id
from .storage import digest_bytes, publish_directory, rebuild_catalog, safe_id


@dataclass(frozen=True, slots=True)
class RenderResult:
    render_root: Path
    render_id: str
    manifest: Mapping[str, object]


def _json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RunStoryError("artifact-invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RunStoryError("artifact-invalid") from None
    if not isinstance(value, dict):
        raise RunStoryError("artifact-invalid")
    return value


def _asset_bytes(name: str) -> bytes:
    try:
        return files("asterion.applications.prime.p7.run_story").joinpath(
            "assets", name
        ).read_bytes()
    except (OSError, FileNotFoundError):
        raise RunStoryError("render-assets-unavailable") from None


def render_web(
    bundle_root: Path,
    analysis_id: str,
    *,
    theme_version: str = "poster-v1",
) -> RenderResult:
    """Create or validate one content-bound deterministic web render."""

    if type(theme_version) is not str or not theme_version:
        raise RunStoryError("render-invalid")
    artifact = _json(bundle_root / "artifact.json")
    if artifact.get("schema") != SCHEMA or type(artifact.get("bundle_sha256")) is not str:
        raise RunStoryError("artifact-invalid")
    analysis_id = safe_id(analysis_id)
    analysis_root = bundle_root / "analyses" / analysis_id
    analysis = _json(analysis_root / "analysis.json")
    story_path = analysis_root / "story.json"
    if (
        analysis.get("analysis_id") != analysis_id
        or analysis.get("bundle_sha256") != artifact["bundle_sha256"]
        or story_path.is_symlink()
        or not story_path.is_file()
        or digest_bytes(story_path.read_bytes()) != analysis.get("story_sha256")
    ):
        raise RunStoryError("analysis-invalid")
    assets = {
        "index.html": _asset_bytes("index.html"),
        "assets/styles.css": _asset_bytes("styles.css"),
        "assets/app.js": _asset_bytes("app.js"),
        "assets/header-art.png": _asset_bytes("header-art.png"),
    }
    identity = {
        "schema": SCHEMA,
        "renderer_version": "web-v1",
        "theme_version": theme_version,
        "bundle_sha256": artifact["bundle_sha256"],
        "analysis_sha256": digest_bytes(canonical_json(analysis)),
        "asset_sha256": {
            name: digest_bytes(value) for name, value in sorted(assets.items())
        },
    }
    render_id = content_id("web", identity)
    manifest = {
        **identity,
        "render_id": render_id,
        "data": {
            "run": "../../../data/run.json",
            "actions": "../../../data/actions.jsonl",
            "frames": "../../../data/frames.jsonl",
            "diffs": "../../../data/diffs.jsonl",
            "metrics": "../../../data/metrics.json",
        },
        "analysis": {
            "analysis_id": analysis_id,
            "story": f"../../../analyses/{analysis_id}/story.json",
        },
    }
    destination = bundle_root / "renders" / "web" / render_id
    publish_directory(
        destination,
        {**assets, "render.json": canonical_json(manifest)},
    )
    rebuild_catalog(bundle_root.parents[3])
    return RenderResult(destination, render_id, MappingProxyType(manifest))


__all__ = ("RenderResult", "render_web")
