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

from .console_snapshot import build_console_snapshot
from .run_story.storage import write_atomic_file


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
    parser.add_argument("run_root", type=Path, help="本次 P7 运行目录")
    parser.add_argument("--output", type=Path, help="输出 HTML；默认写入运行目录 p7-console.html")
    args = parser.parse_args(argv)
    try:
        export_console(args.run_root, args.output)
    except Exception:
        stderr.write("ARC 控制台导出失败。请检查运行记录格式、身份和输出文件权限。\n")
        return 2
    stdout.write("已导出单文件 HTML。用浏览器打开即可回放；无需联网或构建。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
