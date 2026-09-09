"""Operator CLI for compiling, analyzing, rendering, and serving ARC stories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from .analysis import analyze_bundle
from .compiler import compile_run
from .model import RunStoryError, canonical_json
from .operator_narrator import load_operator_narrator
from .renderer import render_web
from .server import serve_artifacts
from .standalone import export_standalone
from .storage import safe_id


_CATALOG_PORT = 8765


def default_artifact_root() -> Path:
    return (Path.cwd() / "artifacts" / "arc-agi-3").resolve()


def _bundle(root: Path, game_id: str, run_id: str) -> Path:
    return root / "games" / safe_id(game_id) / "runs" / safe_id(run_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asterion arc-story")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_parser = commands.add_parser("compile")
    compile_parser.add_argument("run_root")
    analyze = commands.add_parser("analyze")
    analyze.add_argument("game_id")
    analyze.add_argument("run_id")
    render = commands.add_parser("render")
    render.add_argument("game_id")
    render.add_argument("run_id")
    render.add_argument("--analysis", required=True)
    export = commands.add_parser("export")
    export.add_argument("game_id")
    export.add_argument("run_id")
    export.add_argument("--render", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--open-browser", action="store_true")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = _parser().parse_args(argv)
    root = default_artifact_root()
    try:
        if args.command == "compile":
            run_root = Path(args.run_root)
            if not run_root.is_absolute():
                raise RunStoryError("evidence-root-not-absolute")
            result = compile_run(run_root, root)
            payload = {
                "bundle_sha256": result.bundle_sha256,
                "game_id": result.artifact["game_id"],
                "run_id": result.artifact["run_id"],
                "artifact": result.run_root.relative_to(root).as_posix(),
            }
        elif args.command == "analyze":
            result = analyze_bundle(
                _bundle(root, args.game_id, args.run_id),
                load_operator_narrator(Path.cwd()),
            )
            payload = {
                "analysis_id": result.analysis_id,
                "status": result.status,
                "game_id": args.game_id,
                "run_id": args.run_id,
            }
        elif args.command == "render":
            result = render_web(
                _bundle(root, args.game_id, args.run_id), args.analysis
            )
            payload = {
                "render_id": result.render_id,
                "game_id": args.game_id,
                "run_id": args.run_id,
            }
        elif args.command == "export":
            bundle = _bundle(root, args.game_id, args.run_id)
            result = export_standalone(
                bundle / "renders" / "web" / safe_id(args.render),
                root / "exports",
            )
            payload = {
                "file": result.path.relative_to(Path.cwd()).as_posix(),
                "render_id": result.render_id,
                "sha256": result.sha256,
            }
        else:
            root.mkdir(mode=0o750, parents=True, exist_ok=True)
            serve_artifacts(
                root,
                port=_CATALOG_PORT,
                open_browser=args.open_browser,
                on_ready=lambda url: stdout.write(url + "\n"),
            )
            return 0
        stdout.write(canonical_json(payload).decode("utf-8"))
        return 0
    except RunStoryError as error:
        stderr.write(f"asterion arc-story: {error}\n")
        return 2


__all__ = ("default_artifact_root", "main")
