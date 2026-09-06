"""Private standalone process for the one-game P7 development episode."""
# ruff: noqa: E701, E702

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import stat
import sys
import threading
from typing import Callable

_CAP = 65536
_DEADLINE = 10.0


class P7BrokerProcessError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 broker process is unavailable")


def p7_arcade_environment_root(resource_root: object) -> Path:
    if (
        not isinstance(resource_root, Path)
        or not resource_root.is_absolute()
        or resource_root.name != "9607627b"
        or resource_root.parent.name != "ls20"
    ):
        raise P7BrokerProcessError()
    return resource_root.parent.parent


class _ArcadeEngine:
    def __init__(self, resource_root: Path, private_dir: Path) -> None:
        try:
            from arc_agi import Arcade, OperationMode
            from arcengine import GameAction
            arcade = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(p7_arcade_environment_root(resource_root)), recordings_dir=str(private_dir))
            self._env = arcade.make("ls20-9607627b", seed=0, include_frame_data=True)
            if self._env is None:
                raise ValueError
            self._action = GameAction
        except BaseException:
            raise P7BrokerProcessError() from None

    @staticmethod
    def _observation(raw: object) -> dict[str, object]:
        try:
            return {"state": raw.state.value, "levels_completed": raw.levels_completed, "win_levels": raw.win_levels, "available_actions": sorted(int(item.value if hasattr(item, "value") else item) for item in raw.available_actions), "frame": [item.tolist() for item in raw.frame]}
        except BaseException:
            raise P7BrokerProcessError() from None

    def observe(self) -> dict[str, object]: return self._observation(self._env.observation_space)
    def act(self, action_id: int) -> dict[str, object]: return self._observation(self._env.step(self._action["ACTION" + str(action_id)], data={}))
    def status(self) -> bool:
        try: return self._env.observation_space.state.value != "NOT_FINISHED"
        except BaseException: raise P7BrokerProcessError() from None

    def close(self) -> None:
        try:
            close = getattr(self._env, "close", None)
            if callable(close):
                close()
        except BaseException:
            pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _read(connection: socket.socket) -> object:
    data = bytearray()
    while len(data) <= _CAP:
        chunk = connection.recv(min(4096, _CAP + 1 - len(data)))
        if not chunk: break
        data.extend(chunk)
        if data.endswith(b"\n"): break
    if not data.endswith(b"\n") or len(data) > _CAP: raise ValueError
    raw = bytes(data[:-1]); value = json.loads(raw.decode("utf-8", "strict"))
    if _canonical(value) != raw: raise ValueError
    return value


def _reply(connection: socket.socket, result: object) -> None:
    connection.sendall(_canonical({"ok": True, "result": result}) + b"\n")


class _SocketServer:
    def __init__(self, path: Path, handler: Callable[[object], object], stop: threading.Event, model: bool = False) -> None:
        self._path, self._handler, self._stop = path, handler, stop
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path)); os.chmod(path, 0o600)
        if model and os.geteuid() == 0:
            os.chown(path, 65534, 65534)
        self._listener.listen(8); self._listener.settimeout(.2)
    def serve(self) -> None:
        try:
            while not self._stop.is_set():
                try: connection, _ = self._listener.accept()
                except TimeoutError: continue
                with connection:
                    connection.settimeout(_DEADLINE)
                    try: _reply(connection, self._handler(_read(connection)))
                    except BaseException: connection.sendall(b'{"ok":false}\n')
        finally:
            self._listener.close()
            try: self._path.unlink()
            except OSError: pass


def p7_model_client_module_bytes(socket_path: str, token: str) -> bytes:
    """Return a self-contained client with exactly observe/act/status."""
    if type(socket_path) is not str or not socket_path.startswith("/") or type(token) is not str or not token: raise P7BrokerProcessError()
    source = '''import json as _j\nimport os as _o\nimport socket as _s\n_PATH=%r\n_TOKEN=%r\n# Each IPython cell is a new process.  The immutable public stage artifacts\n# are the sole sequence handoff; no hidden state file is permitted.\nif not _o.path.exists("/workspace/initial.json"): _SEQUENCE=0\nelif not _o.path.exists("/workspace/actions.json"): _SEQUENCE=1\nelif not _o.path.exists("/workspace/status.json"): _SEQUENCE=5\nelse: raise RuntimeError("P7 model client unavailable")\ndef _call(method,data):\n global _SEQUENCE\n _SEQUENCE+=1\n request={"token":_TOKEN,"sequence":_SEQUENCE,"method":method,"data":data}\n raw=_j.dumps(request,allow_nan=False,separators=(",",":"),sort_keys=True).encode()+b"\\n"\n if len(raw)>65536: raise RuntimeError("P7 model client unavailable")\n try:\n  with _s.socket(_s.AF_UNIX,_s.SOCK_STREAM) as c:\n   c.settimeout(10); c.connect(_PATH); c.sendall(raw); response=c.makefile("rb").readline()\n  value=_j.loads(response)\n  if type(value) is not dict or set(value)!={"ok","result"} or value["ok"] is not True or type(value["result"]) is not dict: raise ValueError\n  return value["result"]\n except Exception: raise RuntimeError("P7 model client unavailable") from None\ndef observe(): return _call("observe",{})\ndef act(action_id):\n if type(action_id) is not int: raise RuntimeError("P7 model client unavailable")\n return _call("act",{"action_id":action_id,"data":{}})\ndef status(): return _call("status",{})\n''' % (socket_path, token)
    return source.encode()


def _serve(args: argparse.Namespace) -> None:
    source, resource, private = Path(args.asterion_src), Path(args.resource_root), Path(args.private_dir)
    if not source.is_absolute() or not source.is_dir() or not private.is_absolute() or not private.is_dir() or stat.S_IMODE(private.stat().st_mode) != 0o711: raise P7BrokerProcessError()
    from asterion.applications.prime_agent.operator.p7_development_broker import P7DevelopmentBroker
    from asterion.applications.prime_agent.operator.p7_development_workload import P7_DEVELOPMENT_GAME_ID
    if args.game_id != P7_DEVELOPMENT_GAME_ID: raise P7BrokerProcessError()
    engine = _ArcadeEngine(resource, private)
    broker = P7DevelopmentBroker(engine=engine, token=args.model_token)
    stop = threading.Event(); model_sequence = control_sequence = 0
    def model(raw: object) -> object:
        nonlocal model_sequence
        if type(raw) is not dict or raw.get("token") != args.model_token or raw.get("sequence") != model_sequence + 1 or raw.get("method") not in {"observe", "act", "status"}: raise P7BrokerProcessError()
        result = broker.request(raw); model_sequence += 1; return result
    def control(raw: object) -> object:
        nonlocal control_sequence
        if type(raw) is not dict or set(raw) != {"token", "sequence", "method", "data"} or raw["token"] != args.control_token or raw["sequence"] != control_sequence + 1 or raw["method"] not in {"ready", "seal", "replay", "close"} or raw["data"] != {}: raise P7BrokerProcessError()
        control_sequence += 1
        if raw["method"] == "ready": return {"ready": True}
        if raw["method"] == "seal":
            seal = broker.seal(); return {"transcript_sha256": seal.transcript_sha256, "score_sha256": seal.score_sha256, "terminal_reason": seal.terminal_reason, "action_count": seal.action_count}
        if raw["method"] == "replay": return broker.replay(lambda: _ArcadeEngine(resource, private))
        stop.set(); return {"closed": True}
    servers = (_SocketServer(Path(args.model_socket), model, stop, model=True), _SocketServer(Path(args.control_socket), control, stop))
    threads = [threading.Thread(target=item.serve, daemon=True) for item in servers]
    for thread in threads: thread.start()
    try:
        while not stop.wait(.1): pass
    finally:
        engine.close()
        for thread in threads: thread.join(_DEADLINE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    for name in ("asterion-src", "resource-root", "private-dir", "model-socket", "control-socket", "model-token", "control-token", "game-id"): parser.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args(argv); source = Path(args.asterion_src)
        if not source.is_absolute(): raise ValueError
        sys.path.insert(0, str(source)); _serve(args); return 0
    except BaseException: return 1


if __name__ == "__main__":
    raise SystemExit(main())
