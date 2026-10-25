"""Live Pi options for the regulation desk. Importing this module does not start Pi."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from asterion.applications.grid_regulation.retrieve import RegulationCitationError
from asterion.runtime.host import CancellationSignal

GRID_MAX_TURNS = "32"
GRID_CONTEXT_POLICY = '{"tool_result_chars":20000}'
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*")
_UNAVAILABLE = "regulation measures are unavailable"
_LOG_LOCK = threading.Lock()
_LOG_BLOCKED = ("key", "token", "secret", "authorization")


def write_desk_log(line: str) -> None:
    """Write one operator progress line. It carries no passage text."""

    if (
        type(line) is not str
        or not line
        or len(line) > 80
        or "\n" in line
        or "\r" in line
    ):
        return
    lowered = line.casefold()
    if any(word in lowered for word in _LOG_BLOCKED):
        return
    with _LOG_LOCK:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


_LOG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}\Z")


def _desk_progress(kind: str, detail: str) -> None:
    if kind == "turn":
        write_desk_log(f"第 {detail} 轮")
    elif kind == "decision":
        write_desk_log(f"决定 {detail}")
    elif kind == "tool":
        write_desk_log(_tool_log_line(detail))


def _tool_log_line(detail: str) -> str:
    parts = detail.split(" ")
    if not parts or parts[0] not in {"read", "bash", "grep"}:
        return ""
    tool = parts[0]
    name = parts[1] if len(parts) > 1 and _LOG_NAME.fullmatch(parts[1]) else ""
    if tool == "read" and name:
        if len(parts) == 3 and parts[2].isdigit():
            return f"读 {name} 第 {int(parts[2])} 行起"
        if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
            start = int(parts[2])
            limit = int(parts[3])
            end = start + limit - 1
            if limit == 1:
                return f"读 {name} 第 {start} 行"
            return f"读 {name} 第 {start}-{end} 行"
        return f"读 {name}"
    if tool in {"bash", "grep"}:
        return f"搜索 {name}" if name else "搜索"
    return f"打开 {tool}"


@dataclass(frozen=True)
class GridLiveOptions:
    runtime_options: Mapping[str, str]
    host_service_options: Mapping[str, Mapping[str, str]]
    run_id: str
    evidence_file: Path


class _Cancel:
    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


def repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file() and (
            parent / "src" / "asterion"
        ).is_dir():
            return parent
    _fail()


def operator_evidence_root(repo: Path) -> Path:
    """Operator evidence parent. This function does not create it."""

    return Path(repo) / "outputs" / "grid-regulation"


def grid_run_id() -> str:
    return "grid-" + uuid4().hex


def exact_directory(value: str, *, require_directory: bool) -> str:
    """Accept one path Pi can use. The error text is the fixed unavailable string."""

    if type(value) is not str:
        _fail()
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or str(path.resolve(strict=False)) != value
    ):
        _fail()
    current = Path(path.anchor)
    try:
        details = current.stat(follow_symlinks=False)
    except OSError:
        _fail()
    for component in path.parts[1:]:
        current /= component
        try:
            details = current.stat(follow_symlinks=False)
        except FileNotFoundError:
            if current == path and not require_directory:
                return value
            _fail()
        except OSError:
            _fail()
        if stat.S_ISLNK(details.st_mode):
            _fail()
    if require_directory and not stat.S_ISDIR(details.st_mode):
        _fail()
    return value


def answer_evidence_path(evidence_root: str, run_id: str) -> Path:
    digest = hashlib.sha256(run_id.encode()).hexdigest()
    return Path(evidence_root) / digest / "final.txt"


def build_grid_options(
    corpus: Path | str,
    env: Mapping[str, str],
    *,
    evidence_root: Path | str,
    which: Callable[[str], str | None] = shutil.which,
    run_id: str | None = None,
    repo: Path | None = None,
) -> GridLiveOptions:
    """Build one Pi option set. This function does not start Pi."""

    root = repository_root() if repo is None else Path(repo)
    provider = _identity(env.get("DCI_PROVIDER"))
    model = _identity(env.get("DCI_MODEL"))
    checkout = _checkout(root, env)
    cli = checkout / "packages/coding-agent/dist/cli.js"
    if not cli.is_absolute():
        cli = Path.cwd() / cli
    node = _node_path(which)
    agent = _agent_directory(env)
    corpus_text = _corpus_directory(corpus)
    evidence_text = _evidence_directory(corpus_text, Path(evidence_root))
    chosen = grid_run_id() if run_id is None else run_id
    if type(chosen) is not str or not chosen:
        _fail()
    environment = {str(key): str(value) for key, value in env.items()}
    environment["PI_CODING_AGENT_DIR"] = agent
    runtime_options = {
        "command": json.dumps(
            [node, str(cli), "--mode", "rpc", "--thinking", "off"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "cwd": corpus_text,
        "environment": json.dumps(
            environment,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "evidence_root": evidence_text,
        "max_turns": GRID_MAX_TURNS,
        "tools": "read,bash",
        "provider": provider,
        "model": model,
        "context_policy": GRID_CONTEXT_POLICY,
    }
    return GridLiveOptions(
        runtime_options=runtime_options,
        host_service_options={"corpus.local-root": {"root": corpus_text}},
        run_id=chosen,
        evidence_file=answer_evidence_path(evidence_text, chosen),
    )


class LiveGridResearch:
    """Pi research for one desk question. Construction does not spawn or read a file."""

    def __init__(
        self,
        env: Mapping[str, str],
        *,
        evidence_root: Path,
        repo: Path,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._env = {str(key): str(value) for key, value in env.items()}
        self._evidence_root = Path(evidence_root)
        self._repo = Path(repo)
        self._which = which

    async def run(
        self,
        *,
        corpus: Path,
        prompt: str,
        signal: CancellationSignal | None,
    ) -> tuple[str, Mapping[str, object], tuple[str, ...]]:
        if signal is not None and signal.cancelled:
            _fail()
        progress_var = None
        progress_token = None
        try:
            plan = build_grid_options(
                corpus,
                self._env,
                evidence_root=self._evidence_root,
                which=self._which,
                repo=self._repo,
            )
            cancel = signal if signal is not None else _Cancel()
            from asterion.agents.native.application import (
                NativeApplicationSpec,
                NativeOperatorContext,
                prepare_native_application,
            )
            from asterion.runtime.defaults import default_runtime_factory_registry

            application = prepare_native_application(
                NativeApplicationSpec(
                    application_id="native.dci-research",
                    application_version="1.0.0",
                ),
                NativeOperatorContext(
                    runtime_factories=default_runtime_factory_registry(),
                    runtime_options=plan.runtime_options,
                    host_service_options=plan.host_service_options,
                    managed_host_services={},
                ),
            )
            from asterion.runtimes.pi import PI_PROGRESS

            progress_var = PI_PROGRESS
            progress_token = progress_var.set(_desk_progress)
            result = await application.run(prompt, run_id=plan.run_id, signal=cancel)
            reply = plan.evidence_file.read_text(encoding="utf-8")
            return _opened(reply, result)
        except RegulationCitationError:
            raise
        except Exception:
            _fail()
        finally:
            if progress_var is not None and progress_token is not None:
                progress_var.reset(progress_token)


def _fail() -> NoReturn:
    raise RegulationCitationError(_UNAVAILABLE) from None


def _identity(value: object) -> str:
    if type(value) is not str or _IDENTITY.fullmatch(value) is None:
        _fail()
    return value


def _real_directory(path: Path) -> bool:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode)


def _regular_file(path: Path) -> bool:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(details.st_mode) and not stat.S_ISLNK(details.st_mode)


def _checkout(repo: Path, env: Mapping[str, str]) -> Path:
    configured = env.get("DCI_PI_DIR")
    candidates: list[Path] = []
    if isinstance(configured, str) and configured.strip():
        candidates.append(Path(configured).expanduser())
    candidates.append(repo / "pi")
    for checkout in candidates:
        cli = checkout / "packages/coding-agent/dist/cli.js"
        if _real_directory(checkout) and _regular_file(cli):
            return checkout
    _fail()


def _node_path(which: Callable[[str], str | None]) -> str:
    found = which("node")
    if not isinstance(found, str) or not found:
        _fail()
    node = Path(found).resolve()
    text = exact_directory(str(node), require_directory=False)
    try:
        details = node.stat(follow_symlinks=False)
    except OSError:
        _fail()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o111 == 0
        or not os.access(node, os.X_OK)
    ):
        _fail()
    return text


def _agent_directory(env: Mapping[str, str]) -> str:
    raw = env.get("DCI_PI_AGENT_DIR")
    agent = (
        Path(raw).expanduser()
        if isinstance(raw, str) and raw
        else Path("~/.pi/agent").expanduser()
    )
    try:
        resolved = agent.resolve()
    except OSError:
        _fail()
    return exact_directory(str(resolved), require_directory=True)


def _corpus_directory(corpus: Path | str) -> str:
    try:
        resolved = Path(corpus).resolve()
    except OSError:
        _fail()
    return exact_directory(str(resolved), require_directory=True)


def _evidence_directory(corpus: str, evidence_root: Path) -> str:
    try:
        resolved = evidence_root.resolve()
    except OSError:
        _fail()
    if _overlaps(Path(corpus), resolved):
        _fail()
    try:
        resolved.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(resolved, 0o700)
    except OSError:
        _fail()
    return exact_directory(str(resolved), require_directory=False)


def _overlaps(left: Path, right: Path) -> bool:
    return _within(left, right) or _within(right, left)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _opened(
    reply: str, result: object
) -> tuple[str, Mapping[str, object], tuple[str, ...]]:
    artifacts = getattr(result, "artifacts", None)
    if not isinstance(artifacts, tuple):
        _fail()
    locations: Mapping[str, object] | None = None
    calls: tuple[str, ...] | None = None
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            _fail()
        artifact_id = artifact.get("artifact_id")
        value = artifact.get("value")
        if artifact_id == "dci-research-locations":
            if not isinstance(value, Mapping):
                _fail()
            locations = value
        elif artifact_id == "dci-research-trajectory":
            if not isinstance(value, Mapping):
                _fail()
            found = value.get("calls")
            if not isinstance(found, tuple) or any(
                type(name) is not str for name in found
            ):
                _fail()
            calls = found
    if locations is None or calls is None:
        _fail()
    return reply, locations, calls
