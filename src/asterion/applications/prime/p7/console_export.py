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
_GAME_NAME = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?\Z")


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


def render_console(snapshot: dict[str, object], *,
                   live_config: dict[str, object] | None = None,
                   replay_config: dict[str, object] | None = None) -> str:
    """Embed only the projected state, with hashes for the actual inline assets."""
    assets = files("asterion.applications.prime.p7").joinpath("console_assets")
    template = assets.joinpath("index.html").read_text(encoding="utf-8")
    css = assets.joinpath("tailwind.css").read_text(encoding="utf-8") + "\n" + assets.joinpath("styles.css").read_text(encoding="utf-8")
    js = assets.joinpath("app.js").read_text(encoding="utf-8")
    if live_config is not None and replay_config is not None:
        raise ValueError("console configuration ambiguous")
    if live_config is not None:
        if (not isinstance(live_config, dict) or set(live_config) - {"token", "games"}
            or not isinstance(live_config.get("token"), str)
            or not 1 <= len(live_config["token"]) <= 256):
            raise ValueError("console live configuration invalid")
    if replay_config is not None and (not isinstance(replay_config, dict)
                                     or set(replay_config) != {"games"}):
        raise ValueError("console replay configuration invalid")
    console_config = live_config if live_config is not None else replay_config
    if console_config is not None:
        games = console_config.get("games", [])
        if not isinstance(games, list) or any(
            not isinstance(game, dict) or not {"game_id", "alias", "win_levels"} <= set(game)
            or set(game) - {"game_id", "alias", "win_levels", "baseline_actions"}
            or not isinstance(game["game_id"], str) or not game["game_id"]
            or not isinstance(game["alias"], str)
            or type(game["win_levels"]) is not int or game["win_levels"] < 1
            or ("baseline_actions" in game and (
                type(game["baseline_actions"]) is not list
                or len(game["baseline_actions"]) != game["win_levels"]
                or any(type(count) is not int or count <= 0 for count in game["baseline_actions"])))
            for game in games
        ):
            raise ValueError("console catalog invalid")
    data = _inline_json(snapshot)
    config = _inline_json(console_config)
    connect = "'self'" if live_config is not None else "'none'"
    csp = (f"default-src 'none'; connect-src {connect}; img-src data:; "
           f"style-src '{_hash(css)}'; script-src '{_hash(js)}' '{_hash(data)}' '{_hash(config)}'; "
           "base-uri 'none'; form-action 'none'; object-src 'none'")
    replacements = {"__CONSOLE_CSP__": csp, "__CONSOLE_CSS__": css,
                    "__CONSOLE_JS__": js, "__CONSOLE_DATA__": data,
                    "__CONSOLE_CONFIG__": config}
    if any(template.count(key) != 1 for key in replacements):
        raise ValueError("console template invalid")
    # One substitution pass: evidence resembling a template marker stays data.
    return re.sub("|".join(replacements), lambda match: replacements[match[0]], template)


def _fixed_projection(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("console output must be a regular HTML file")
    if not path.is_file():
        return {}
    match = re.search(r'<script id="console-data" type="application/json">(.*?)</script>',
                      path.read_text(encoding="utf-8"), re.S)
    try:
        return json.loads(match[1]).get("run", {}) if match else {}
    except (ValueError, AttributeError):
        return {}


def _publish_fixed_replays(run_root: Path, snapshot: dict, payload: bytes) -> None:
    """Keep stable viewing files, without replacing a better saved progression."""
    run = snapshot.get("run", {})
    game_id = run.get("game_id")
    if (not _RUN_NAME.fullmatch(run_root.name) or run.get("run_id") != run_root.name
            or type(game_id) is not str or not _GAME_NAME.fullmatch(game_id)
            or run.get("sealed_trace") is not True
            or type(run.get("completed_level_count")) is not int
            or run["completed_level_count"] < 1):
        return
    summary_path = run_root / "summary.json"
    if summary_path.is_symlink():
        raise ValueError("console evidence unavailable")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (summary.get("run_id") != run_root.name or any(summary.get(key) is not True
            for key in ("sealed_trace", "replay_verified", "cleanup_complete"))):
        return
    prefix = summary.get("completed_prefix")
    if prefix is not None:
        from .live import read_trace_entries
        from .score import replay_sha256
        from .solutions import _prefix_values, _transitions, _truncate

        if (type(prefix) is not dict or prefix.get("levels_completed") != run["completed_level_count"]
                or _prefix_values(prefix, game_id, run.get("seed"), run.get("win_levels"),
                                  is_partial=True) is None):
            return
        entries = read_trace_entries(run_root / "trace")
        markers = [entry.payload for entry in entries if entry.kind == "arc.run.partial"]
        transitions = _truncate(_transitions(entries), prefix["levels_completed"])
        if (markers != [prefix] or len(transitions) != prefix["primitive_actions"]
                or replay_sha256(transitions, terminal_reason="level-completed") != prefix["replay_sha256"]):
            return
    elif run.get("replay_verified") is not True:
        return
    root = run_root.parent.resolve()
    game_path = root / "replays" / (game_id.split("-")[0] + ".html")
    latest_path = root / "p7-console.html"
    # Validate both outputs before publication, including an existing linked file.
    previous_game = _fixed_projection(game_path)
    previous_latest = _fixed_projection(latest_path)
    rank = (run["completed_level_count"], run["run_id"])
    old_rank = (previous_game.get("completed_level_count", 0), previous_game.get("run_id", ""))
    if rank >= old_rank:
        write_atomic_file(game_path, payload)
    if run["run_id"] >= previous_latest.get("run_id", ""):
        write_atomic_file(latest_path, payload)


def export_console(run_root: Path, output: Path | None = None, *,
                   replay_config: dict[str, object] | None = None) -> Path:
    """Create the portable document; leave game evidence and solver state intact."""
    destination = Path(output) if output is not None else Path(run_root) / "p7-console.html"
    if destination.suffix.lower() != ".html" or destination.is_symlink():
        raise ValueError("console output must be a regular HTML file")
    snapshot = build_console_snapshot(Path(run_root))
    payload = render_console(snapshot, replay_config=replay_config).encode("utf-8")
    # Resolve operator-selected parents (macOS /tmp and /var are aliases),
    # while refusing to replace a symbolic-link output file above.
    write_atomic_file(destination.parent.resolve() / destination.name, payload)
    if output is None:
        _publish_fixed_replays(Path(run_root), snapshot, payload)
    return destination


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None,
         stderr: TextIO | None = None) -> int:
    """Export or open the application console; startup never calls a model."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["serve"]:
        return _serve_main(arguments[1:], stdout=stdout, stderr=stderr)
    if arguments[:1] == ["replay"]:
        return _replay_main(arguments[1:], stdout=stdout, stderr=stderr)
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


def _replay_main(argv: list[str], *, stdout: TextIO, stderr: TextIO) -> int:
    parser = argparse.ArgumentParser(prog="asterion arc-console replay", description="打开固定文件名的已保存回放")
    parser.add_argument("--runs-root", type=Path, default=Path(".asterion-private/prime-p7-live"))
    parser.add_argument("--game", help="游戏别名，例如 sp80；省略时打开最近已验证回放")
    args = parser.parse_args(argv)
    if args.game is not None and not _GAME_NAME.fullmatch(args.game):
        stderr.write("游戏名称无效。\n")
        return 2
    path = (args.runs_root / "replays" / (args.game.split("-")[0] + ".html")
            if args.game else args.runs_root / "p7-console.html")
    if path.is_symlink() or not path.is_file():
        stderr.write("尚无已保存回放；请先完成并导出一次运行。\n")
        return 2
    if args.game and "-" in args.game and _fixed_projection(path).get("game_id") != args.game:
        stderr.write("固定回放与指定游戏版本不匹配。\n")
        return 2
    try:
        opened = webbrowser.open(path.resolve().as_uri())
    except Exception:
        opened = False
    if not opened:
        stderr.write("浏览器未能打开；固定回放文件仍可直接打开。\n")
        return 2
    stdout.write("已打开保存回放。\n")
    return 0


def _serve_main(argv: list[str], *, stdout: TextIO, stderr: TextIO) -> int:
    parser = argparse.ArgumentParser(prog="asterion arc-console serve", description="打开 P7 自主求解控制台")
    parser.add_argument("--operator-root", type=Path, default=Path.cwd())
    parser.add_argument("--arc-root", type=Path, default=Path.cwd().parent / "external-prime" / "arc-agi-3")
    parser.add_argument("--guest-machine", default="ubuntu")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=57515, help="本地监听端口（默认 57515）")
    args = parser.parse_args(argv)

    def ready(url: str) -> None:
        stdout.write(f"P7 自主求解控制台：{url}\n")
        stdout.flush()

    try:
        from .console_server import serve_console

        serve_console(operator_root=args.operator_root, arc_root=args.arc_root,
                      guest_machine=args.guest_machine, open_browser=not args.no_browser,
                      on_ready=ready, port=args.port)
    except KeyboardInterrupt:
        return 0
    except Exception:
        stderr.write("P7 控制台服务无法启动或已异常结束。请检查本地游戏资源及运行配置。\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
