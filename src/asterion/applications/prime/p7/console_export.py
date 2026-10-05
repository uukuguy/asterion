"""Provider-free export of one P7 run to a self-contained level console."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import re
import sys
from typing import TextIO
import webbrowser

from .console_snapshot import build_console_snapshot
from .run_story.storage import write_atomic_file


_RUN_NAME = re.compile(r"p7-live-[0-9]{14}-[0-9a-f]{24}\Z")


def _latest_run_root(runs_root: Path) -> Path | None:
    """Select by run identity time, without following linked or replay evidence."""
    if runs_root.is_symlink() or not runs_root.is_dir():
        return None
    for root in sorted(runs_root.iterdir(), key=lambda path: path.name, reverse=True):
        if not _RUN_NAME.fullmatch(root.name) or root.is_symlink() or not root.is_dir():
            continue
        summary = root / "summary.json"
        recordings = root / "recordings"
        if (summary.is_symlink() or not summary.is_file()
            or recordings.is_symlink() or not recordings.is_dir()):
            continue
        for session in recordings.iterdir():
            if session.is_symlink() or not session.is_dir():
                continue
            if any(not recording.is_symlink() and recording.is_file()
                   for recording in session.glob("*.jsonl")):
                return root
    return None


def _inline_json(value: object) -> str:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _hash(content: str) -> str:
    return "sha256-" + base64.b64encode(sha256(content.encode("utf-8")).digest()).decode("ascii")


def render_console(snapshot: dict[str, object]) -> str:
    """Embed only the projected state, with hashes for the actual inline assets."""
    assets = files("asterion.applications.prime.p7").joinpath("console_assets")
    template = assets.joinpath("index.html").read_text(encoding="utf-8")
    css = assets.joinpath("tailwind.css").read_text(encoding="utf-8") + "\n" + assets.joinpath("styles.css").read_text(encoding="utf-8")
    js = assets.joinpath("app.js").read_text(encoding="utf-8")
    data = _inline_json(snapshot)
    csp = ("default-src 'none'; connect-src 'none'; img-src data:; "
           f"style-src '{_hash(css)}'; script-src '{_hash(js)}' '{_hash(data)}'; "
           "base-uri 'none'; form-action 'none'; object-src 'none'")
    replacements = {"__CONSOLE_CSP__": csp, "__CONSOLE_CSS__": css,
                    "__CONSOLE_JS__": js, "__CONSOLE_DATA__": data}
    if any(template.count(key) != 1 for key in replacements):
        raise ValueError("console template invalid")
    # One substitution pass: evidence resembling a template marker stays data.
    return re.sub("|".join(replacements), lambda match: replacements[match[0]], template)


def export_console(run_root: Path, output: Path | None = None) -> Path:
    """Create the portable document; leave game evidence and solver state intact."""
    destination = Path(output) if output is not None else Path(run_root) / "p7-console.html"
    if destination.suffix.lower() != ".html" or destination.is_symlink():
        raise ValueError("console output must be a regular HTML file")
    snapshot = build_console_snapshot(Path(run_root))
    payload = render_console(snapshot).encode("utf-8")
    # Resolve operator-selected parents (macOS /tmp and /var are aliases),
    # while refusing to replace a symbolic-link output file above.
    write_atomic_file(destination.parent.resolve() / destination.name, payload)
    return destination


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None,
         stderr: TextIO | None = None) -> int:
    """Application CLI; this command never loads a provider or calls a model."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(prog="asterion arc-console", description="导出单文件 ARC-AGI-3 关卡回放")
    parser.add_argument("run_root", type=Path, nargs="?", help="P7 运行目录；默认选择最近一份带录制的运行")
    parser.add_argument("--runs-root", type=Path, default=Path(".asterion-private/prime-p7-live"),
                        help="自动选择运行的根目录")
    parser.add_argument("--output", type=Path, help="输出 HTML；默认写入运行目录 p7-console.html")
    parser.add_argument("--open-browser", action="store_true", help="导出后用现有默认浏览器打开")
    args = parser.parse_args(argv)
    try:
        run_root = args.run_root if args.run_root is not None else _latest_run_root(args.runs_root)
        if run_root is None:
            stderr.write("没有找到带运行摘要和游戏录制的 P7 运行。请先完成一次 P7 运行，或指定运行目录。\n")
            return 2
        destination = export_console(run_root, args.output)
    except Exception:
        stderr.write("ARC 控制台导出失败。请检查运行记录格式、身份和输出文件权限。\n")
        return 2
    if args.run_root is None:
        stdout.write(f"已选择运行：{run_root.name}\n")
    stdout.write("已导出单文件 HTML。用浏览器打开即可回放；无需联网或构建。\n")
    if args.open_browser:
        try:
            opened = webbrowser.open(destination.resolve().as_uri())
        except Exception:
            opened = False
        if not opened:
            stderr.write("浏览器未能自动打开；HTML 已导出。请手动用浏览器打开运行目录中的 p7-console.html；指定 --output 时打开该输出文件。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
