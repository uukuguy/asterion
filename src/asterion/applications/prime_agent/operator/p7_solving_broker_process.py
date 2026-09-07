"""Isolated SDK process for the bounded P7 solving broker."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import stat
import sys
import threading
from typing import Callable

_REQUEST_CAP = 65536
_RESPONSE_CAP = 1048576
_DEADLINE = 30.0


class P7SolvingBrokerProcessError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving broker process is unavailable")


def p7_solving_arcade_root(resource_root: object) -> Path:
    if (
        not isinstance(resource_root, Path)
        or not resource_root.is_absolute()
        or resource_root.name != "9607627b"
        or resource_root.parent.name != "ls20"
    ):
        raise P7SolvingBrokerProcessError()
    return resource_root.parent.parent


def verify_p7_solving_process_resource(resource_root: object) -> object:
    """Recheck the exact LS20 resource inside the SDK-owning process."""

    try:
        from asterion.applications.prime_agent.operator.p7_resource_lock import (
            verify_p7_development_resources,
        )
        from asterion.applications.prime_agent.operator.p7_solving_workload import (
            P7_SOLVING_GAME_ID,
            P7_SOLVING_RESOURCE_SHA256,
        )

        locked = verify_p7_development_resources(resource_root)
        if (
            locked.root != resource_root
            or locked.game_id != P7_SOLVING_GAME_ID
            or locked.resource_sha256 != P7_SOLVING_RESOURCE_SHA256
        ):
            raise ValueError
        return locked
    except BaseException:
        raise P7SolvingBrokerProcessError() from None


class _ArcadeEngine:
    def __init__(self, resource_root: Path, private_dir: Path) -> None:
        try:
            from arc_agi import Arcade, OperationMode
            from arcengine import GameAction

            arcade = Arcade(
                operation_mode=OperationMode.OFFLINE,
                environments_dir=str(p7_solving_arcade_root(resource_root)),
                recordings_dir=str(private_dir),
            )
            environment = arcade.make(
                "ls20-9607627b", seed=0, include_frame_data=True, save_recording=True
            )
            if environment is None:
                raise ValueError
            self._environment = environment
            self._game_action = GameAction
            self._last = environment.reset()
        except BaseException:
            raise P7SolvingBrokerProcessError() from None

    @staticmethod
    def _observation(raw: object) -> dict[str, object]:
        try:
            state = raw.state.value if hasattr(raw.state, "value") else raw.state.name
            return {
                "available_actions": sorted(
                    int(item.value if hasattr(item, "value") else item)
                    for item in raw.available_actions
                ),
                "frame": [
                    item.tolist() if hasattr(item, "tolist") else item
                    for item in raw.frame
                ],
                "levels_completed": raw.levels_completed,
                "state": state,
                "win_levels": raw.win_levels,
            }
        except BaseException:
            raise P7SolvingBrokerProcessError() from None

    def observe(self) -> dict[str, object]:
        return self._observation(self._last)

    def act(self, action: dict[str, object]) -> dict[str, object]:
        try:
            name, data = action["name"], action["data"]
            self._last = self._environment.step(self._game_action[name], data)
            return self._observation(self._last)
        except BaseException:
            raise P7SolvingBrokerProcessError() from None

    def close(self) -> None:
        try:
            close = getattr(self._environment, "close", None)
            if callable(close):
                close()
        except BaseException:
            pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _read(connection: socket.socket) -> object:
    data = bytearray()
    while len(data) <= _REQUEST_CAP:
        chunk = connection.recv(min(4096, _REQUEST_CAP + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if data.endswith(b"\n"):
            break
    if not data.endswith(b"\n") or len(data) > _REQUEST_CAP:
        raise P7SolvingBrokerProcessError()
    raw = bytes(data[:-1])
    try:
        value = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise P7SolvingBrokerProcessError() from None
    if _canonical(value) != raw:
        raise P7SolvingBrokerProcessError()
    return value


def _reply(connection: socket.socket, result: object) -> None:
    raw = _canonical({"ok": True, "result": result}) + b"\n"
    if len(raw) > _RESPONSE_CAP:
        raise P7SolvingBrokerProcessError()
    connection.sendall(raw)


class _SocketServer:
    def __init__(
        self,
        path: Path,
        handler: Callable[[object], object],
        stop: threading.Event,
        *,
        model: bool,
    ) -> None:
        if path.exists() or path.is_symlink():
            raise P7SolvingBrokerProcessError()
        self._path, self._handler, self._stop = path, handler, stop
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        os.chmod(path, 0o600)
        if model and os.geteuid() == 0:
            os.chown(path, 65534, 65534)
        info = path.lstat()
        expected_uid = 65534 if model and os.geteuid() == 0 else os.geteuid()
        if (
            not stat.S_ISSOCK(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != expected_uid
        ):
            self._listener.close()
            raise P7SolvingBrokerProcessError()
        self._listener.listen(8)
        self._listener.settimeout(0.2)

    def serve(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    connection, _ = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(_DEADLINE)
                    try:
                        _reply(connection, self._handler(_read(connection)))
                    except BaseException:
                        connection.sendall(b'{"ok":false}\n')
        finally:
            self._listener.close()
            try:
                self._path.unlink()
            except OSError:
                pass


def _serve(args: argparse.Namespace) -> None:
    source, resource, private = (
        Path(args.asterion_src),
        Path(args.resource_root),
        Path(args.private_dir),
    )
    if (
        not source.is_absolute()
        or not source.is_dir()
        or not resource.is_absolute()
        or not resource.is_dir()
        or not private.is_absolute()
        or not private.is_dir()
        or private.is_symlink()
        or stat.S_IMODE(private.stat().st_mode) != 0o711
        or private.stat().st_uid != os.geteuid()
    ):
        raise P7SolvingBrokerProcessError()
    from asterion.applications.prime_agent.operator.p7_solving_broker import (
        P7SolvingBroker,
    )
    from asterion.applications.prime_agent.operator.p7_solving_score import (
        bind_p7_solving_score_calculator,
    )
    from asterion.applications.prime_agent.operator.p7_solving_workload import (
        P7_SOLVING_ARC_AGI_WHEEL_SHA256,
        P7_SOLVING_GAME_ID,
        P7_SOLVING_RESOURCE_SHA256,
    )

    if (
        args.game_id != P7_SOLVING_GAME_ID
        or args.resource_sha256 != P7_SOLVING_RESOURCE_SHA256
        or args.arc_agi_wheel_sha256 != P7_SOLVING_ARC_AGI_WHEEL_SHA256
    ):
        raise P7SolvingBrokerProcessError()
    verify_p7_solving_process_resource(resource)
    score_calculator = bind_p7_solving_score_calculator(
        Path(args.runtime_root), runtime_sha256=args.runtime_sha256
    )
    engine = _ArcadeEngine(resource, private)
    broker = P7SolvingBroker(
        engine=engine,
        token=args.model_token,
        resource_sha256=args.resource_sha256,
        arc_agi_wheel_sha256=args.arc_agi_wheel_sha256,
        score_calculator=score_calculator,
    )
    stop = threading.Event()
    control_sequence = 0

    def model(raw: object) -> object:
        return broker.request(raw)

    def control(raw: object) -> object:
        nonlocal control_sequence
        if (
            type(raw) is not dict
            or set(raw) != {"data", "method", "sequence", "token"}
            or raw["token"] != args.control_token
            or type(raw["sequence"]) is not int
            or raw["sequence"] != control_sequence + 1
            or raw["method"] not in {"close", "presentation", "ready", "replay", "seal"}
            or raw["data"] != {}
        ):
            raise P7SolvingBrokerProcessError()
        control_sequence += 1
        if raw["method"] == "ready":
            return {"ready": True}
        if raw["method"] == "seal":
            return asdict(broker.seal())
        if raw["method"] == "presentation":
            return broker.presentation()
        if raw["method"] == "replay":
            return broker.replay(
                lambda: _ArcadeEngine(resource, private),
                resource_sha256=args.resource_sha256,
                arc_agi_wheel_sha256=args.arc_agi_wheel_sha256,
            )
        stop.set()
        return {"closed": True}

    servers = (
        _SocketServer(Path(args.model_socket), model, stop, model=True),
        _SocketServer(Path(args.control_socket), control, stop, model=False),
    )
    threads = [threading.Thread(target=server.serve, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        while not stop.wait(0.1):
            pass
    finally:
        engine.close()
        for thread in threads:
            thread.join(_DEADLINE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    for name in (
        "arc-agi-wheel-sha256",
        "asterion-src",
        "control-socket",
        "control-token",
        "game-id",
        "model-socket",
        "model-token",
        "private-dir",
        "resource-root",
        "resource-sha256",
        "runtime-root",
        "runtime-sha256",
    ):
        parser.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args(argv)
        source = Path(args.asterion_src)
        if not source.is_absolute():
            raise ValueError
        sys.path.insert(0, str(source))
        _serve(args)
        return 0
    except BaseException:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
