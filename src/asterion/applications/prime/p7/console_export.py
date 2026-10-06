"""Provider-free export of one P7 run to a self-contained level console."""

from __future__ import annotations

import argparse
import base64
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import TextIO
import webbrowser

from .console_snapshot import build_console_snapshot
from .console_replay import replay_fingerprint, projection_revision
from .console_prepared import publish_prepared
from .console_frames import frame_page


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
        if (not isinstance(live_config, dict) or set(live_config) - {"token", "games", "replay_loading"}
            or not isinstance(live_config.get("token"), str)
            or not 1 <= len(live_config["token"]) <= 256
            or ("replay_loading" in live_config and live_config["replay_loading"] != "level-manifest/v1")):
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
    # Current exports put metadata before all inert animation pages. Stop
    # after the configuration instead of loading the complete HTML arena.
    parts = []
    with path.open(encoding='utf-8') as stream:
        while chunk := stream.read(65536):
            parts.append(chunk)
            if 'id="console-config"' in chunk or len(parts) > 1 and 'id="console-config"' in parts[-2] + chunk:
                tail = ''.join(parts[-2:])
                if re.search(r'id="console-config"[^>]*>.*?</script>', tail, re.S):
                    break
    html = ''.join(parts)
    data = re.search(r'<script id="console-data" type="application/json">(.*?)</script>',
                     html, re.S)
    config = re.search(r'<script id="console-config" type="application/json">(.*?)</script>',
                       html, re.S)
    try:
        return {"snapshot": json.loads(data[1]) if data else {},
                "config": json.loads(config[1]) if config else None}
    except (ValueError, AttributeError):
        return {}


def _source_summary(runs_root: Path, run_id: object) -> tuple[dict, int]:
    if (type(run_id) is not str or not _RUN_NAME.fullmatch(run_id)
            or runs_root.is_symlink() or not runs_root.is_dir()):
        return {}, 0
    source = runs_root / run_id
    summary_path = source / "summary.json"
    if (source.is_symlink() or not source.is_dir() or summary_path.is_symlink()
            or not summary_path.is_file()):
        return {}, 0
    try:
        stat = summary_path.stat()
        if stat.st_size > 32 * 1024 * 1024:
            return {}, 0
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return (summary if isinstance(summary, dict) else {}), stat.st_mtime_ns
    except (OSError, UnicodeError, ValueError):
        return {}, 0


def _verified_partial(run_root: Path, summary: dict, run: dict):
    prefix = summary.get("completed_prefix")
    if prefix is None:
        return None
    from .live import read_trace_entries
    from .score import replay_sha256
    from .solutions import _prefix_values, _transitions, _truncate

    if (type(prefix) is not dict or prefix.get("levels_completed") != run.get("completed_level_count")
            or _prefix_values(prefix, run.get("game_id"), run.get("seed"), run.get("win_levels"),
                              is_partial=True) is None):
        return False
    entries = read_trace_entries(run_root / "trace")
    markers = [entry.payload for entry in entries if entry.kind == "arc.run.partial"]
    transitions = _truncate(_transitions(entries), prefix["levels_completed"])
    if (markers != [prefix] or len(transitions) != prefix["primitive_actions"]
            or replay_sha256(transitions, terminal_reason="level-completed") != prefix["replay_sha256"]):
        return False
    return prefix, transitions


def _route_score(snapshot: dict, summary: dict, run: dict, config: object, partial) -> Decimal | None:
    levels = snapshot.get("levels", [])
    if isinstance(levels, list):
        for level in levels:
            receipt = level.get("receipt") if isinstance(level, dict) else None
            if isinstance(receipt, dict) and level.get("level") == run.get("completed_level_count"):
                score = receipt.get("partial_game_score")
                try:
                    value = Decimal(score)
                    if value.is_finite() and value >= 0:
                        return value
                except (InvalidOperation, TypeError):
                    pass
    receipt = summary.get("receipt")
    if isinstance(receipt, dict):
        score = receipt.get("partial_game_score")
        try:
            value = Decimal(score)
            if value.is_finite() and value >= 0:
                return value
        except (InvalidOperation, TypeError):
            pass
    if partial is None or not isinstance(config, dict):
        return None
    games = config.get("games")
    game = next((item for item in games if isinstance(item, dict)
                 and item.get("game_id") == run.get("game_id")), None) if isinstance(games, list) else None
    baseline = game.get("baseline_actions") if game else None
    if (not isinstance(baseline, list) or game.get("win_levels") != run.get("win_levels")
            or len(baseline) != run.get("win_levels")):
        return None
    try:
        from .game import P7GameSelection
        from .score import partial_game_score
        prefix, transitions = partial
        action_counts, previous = [], 0
        for level_number in range(1, prefix["levels_completed"] + 1):
            end = next(item.sequence for item in transitions if item.levels_completed == level_number)
            action_counts.append(end - previous)
            previous = end
        selection = P7GameSelection(run["game_id"], run["seed"], len(action_counts),
                                    tuple(baseline), game["win_levels"])
        return Decimal(partial_game_score(tuple(action_counts), selection))
    except (KeyError, StopIteration, TypeError, ValueError, InvalidOperation):
        return None


def _fixed_rank(snapshot: dict, summary: dict, config: object, mtime: int, partial=None):
    run = snapshot.get("run", {})
    if not isinstance(run, dict):
        return (0, False, Decimal(-1), 0, mtime)
    completed = run.get("completed_level_count")
    completed = completed if type(completed) is int and completed > 0 else 0
    route_actions = partial[0].get("primitive_actions") if partial else run.get("primitive_action_count")
    route_actions = route_actions if type(route_actions) is int and route_actions > 0 else 10**9
    score = _route_score(snapshot, summary, run, config, partial)
    return (completed, score is not None, score if score is not None else Decimal(-1),
            -route_actions, mtime)


def _write_stream(path, parts):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('console output must be a regular HTML file')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, 'wb') as stream:
            descriptor = -1
            for part in parts:
                stream.write(part.encode('utf-8') if type(part) is str else part)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)


def _copy_public_html(source, destination):
    def parts():
        with source.open('rb') as stream:
            while part := stream.read(65536):
                yield part
    _write_stream(destination, parts())


def _publish_fixed_replays(run_root: Path, snapshot: dict, payload: Path,
                           replay_config: dict[str, object] | None = None) -> None:
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
    partial = _verified_partial(run_root, summary, run)
    if partial is False:
        return
    if partial is None and run.get("replay_verified") is not True:
        return
    root = run_root.parent.resolve()
    game_path = root / "replays" / (game_id.split("-")[0] + ".html")
    latest_path = root / "p7-console.html"
    # Validate both outputs before publication, including an existing linked file.
    previous_game = _fixed_projection(game_path)
    previous_latest = _fixed_projection(latest_path)
    current_config = replay_config if replay_config is not None else previous_game.get("config")
    candidate_rank = _fixed_rank(snapshot, summary, current_config,
                                 summary_path.stat().st_mtime_ns, partial)
    previous_snapshot = previous_game.get("snapshot", {})
    previous_run = previous_snapshot.get("run", {}) if isinstance(previous_snapshot, dict) else {}
    previous_summary, previous_mtime = _source_summary(root, previous_run.get("run_id"))
    previous_partial = None
    previous_run_root = root / previous_run.get("run_id", "") if previous_run else root
    if previous_summary.get("completed_prefix") is not None and previous_run_root.is_dir():
        try:
            previous_partial = _verified_partial(previous_run_root, previous_summary, previous_run)
            if previous_partial is False:
                previous_partial = None
        except (OSError, ValueError, TypeError, KeyError):
            previous_partial = None
    old_rank = _fixed_rank(previous_snapshot if isinstance(previous_snapshot, dict) else {},
                           previous_summary, previous_game.get("config"), previous_mtime, previous_partial)
    same_game_source = run["run_id"] == previous_run.get("run_id")
    if candidate_rank > old_rank or same_game_source:
        _copy_public_html(payload, game_path)
    latest_run = previous_latest.get("snapshot", {}).get("run", {})
    latest_run_id = latest_run.get("run_id") if isinstance(latest_run, dict) else None
    _, latest_mtime = _source_summary(root, latest_run_id)
    if summary_path.stat().st_mtime_ns > latest_mtime or run["run_id"] == latest_run_id:
        _copy_public_html(payload, latest_path)


def export_console(run_root: Path, output: Path | None = None, *,
                   replay_config: dict[str, object] | None = None) -> Path:
    """Create the portable document; leave game evidence and solver state intact."""
    destination = Path(output) if output is not None else Path(run_root) / "p7-console.html"
    if destination.suffix.lower() != ".html" or destination.is_symlink():
        raise ValueError("console output must be a regular HTML file")
    root = Path(run_root).resolve()
    try:
        fingerprint = replay_fingerprint(root)
    except (OSError, ValueError, TypeError):
        fingerprint = None
    snapshot = build_console_snapshot(Path(run_root))
    if fingerprint is not None:
        publish_prepared(root, snapshot, fingerprint)
    paged = any('frame_page' in level for level in snapshot['levels'])
    display = ({**snapshot, 'offline_frames': True,
                'replay_revision': projection_revision(fingerprint or ())} if paged else snapshot)
    html = render_console(display, replay_config=replay_config)
    def parts():
        if not paged:
            yield html
            return
        position = html.index('<script>')
        yield html[:position]
        for bucket in snapshot['levels']:
            if 'frame_page' not in bucket:
                continue
            for start in range(0, bucket['frame_count'], 32):
                page = frame_page(root, bucket['level'], display['replay_revision'],
                                  bucket['frame_page']['source_token'], start, 32)
                yield f'<script type="application/json" id="console-frame-page-{bucket["level"]}-{start}">'
                yield _inline_json(page)
                yield '</script>\n'
        yield html[position:]
    # Resolve operator-selected parents (macOS /tmp and /var are aliases),
    # while refusing to replace a symbolic-link output file above.
    actual = destination.parent.resolve() / destination.name
    _write_stream(actual, parts())
    if output is None:
        _publish_fixed_replays(Path(run_root), snapshot, actual, replay_config)
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
