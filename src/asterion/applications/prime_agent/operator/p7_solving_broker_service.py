"""Host-owned lifetime and private control channel for P7 solving."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time

from .p7_solving_client import p7_solving_client_module_bytes
from .p7_solving_workload import (
    P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    P7_SOLVING_GAME_ID,
    P7_SOLVING_RESOURCE_SHA256,
)

_FRAME_CAP = 1048576
_PUBLIC_SEAL_FIELDS = {
    "action_count",
    "levels_completed",
    "score",
    "score_sha256",
    "terminal_reason",
    "transcript_sha256",
}
_PUBLIC_REPLAY_FIELDS = {
    "action_count",
    "levels_completed",
    "replay_sha256",
    "score",
    "score_sha256",
    "terminal_reason",
}
_PRESENTATION_FIELDS = {
    "action_count",
    "applied_actions",
    "completion_grid",
    "initial_grid",
    "levels_completed",
    "score",
    "terminal_reason",
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SCORE = re.compile(r"(?:0|[1-9][0-9]?|100)\.[0-9]{6}\Z")


class P7SolvingBrokerServiceError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving broker service is unavailable")


class _StartupTransient(Exception):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _socket_is_private(path: Path, *, model: bool) -> bool:
    try:
        info = path.lstat()
        expected_uid = 65534 if model and os.geteuid() == 0 else os.geteuid()
        return (
            not path.is_symlink()
            and stat.S_ISSOCK(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == expected_uid
        )
    except OSError:
        return False


class P7SolvingBrokerService:
    """One process, one model socket, and one host-private control socket."""

    def __init__(
        self,
        *,
        interpreter: Path,
        asterion_src: Path,
        resource_root: Path,
        private_dir: Path | None = None,
        resource_sha256: str = P7_SOLVING_RESOURCE_SHA256,
        arc_agi_wheel_sha256: str = P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    ) -> None:
        if (
            not all(
                isinstance(item, Path) and item.is_absolute()
                for item in (interpreter, asterion_src, resource_root)
            )
            or not interpreter.is_file()
            or not os.access(interpreter, os.X_OK)
            or not asterion_src.is_dir()
            or asterion_src.is_symlink()
            or not resource_root.is_dir()
            or resource_root.is_symlink()
            or resource_root.name != "9607627b"
            or resource_root.parent.name != "ls20"
            or private_dir is not None
            and (
                not isinstance(private_dir, Path)
                or not private_dir.is_absolute()
                or private_dir.exists()
                or private_dir.is_symlink()
            )
            or resource_sha256 != P7_SOLVING_RESOURCE_SHA256
            or arc_agi_wheel_sha256 != P7_SOLVING_ARC_AGI_WHEEL_SHA256
        ):
            raise P7SolvingBrokerServiceError()
        self._interpreter = interpreter
        self._runtime_root = interpreter.parent.parent.parent
        if interpreter != self._runtime_root / "venv/bin/python3":
            raise P7SolvingBrokerServiceError()
        self._source = asterion_src
        self._resource = resource_root
        self._resource_sha256 = resource_sha256
        self._wheel_sha256 = arc_agi_wheel_sha256
        self._private = (
            Path(tempfile.mkdtemp(prefix="asterion-p7-solving-"))
            if private_dir is None
            else private_dir
        )
        self._private_created = private_dir is None
        self._model_socket = self._private / "model.sock"
        self._control_socket = self._private / "control.sock"
        self._pycache = self._private / "pycache"
        self._model_token = secrets.token_hex(32)
        self._control_token = secrets.token_hex(32)
        self._control_sequence = 0
        self._process: subprocess.Popen[bytes] | None = None

    def __repr__(self) -> str:
        return "P7SolvingBrokerService(redacted)"

    @property
    def private_dir(self) -> Path:
        return self._private

    @property
    def model_socket(self) -> Path:
        return self._model_socket

    def start(self, *, client_socket_path: str = "/broker/model.sock") -> bytes:
        if self._process is not None or client_socket_path != "/broker/model.sock":
            raise P7SolvingBrokerServiceError()
        try:
            if self._private_created:
                os.chmod(self._private, 0o711)
            else:
                self._private.mkdir(mode=0o711, parents=True, exist_ok=False)
                self._private_created = True
            info = self._private.lstat()
            if (
                self._private.is_symlink()
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o711
                or info.st_uid != os.geteuid()
            ):
                raise ValueError
            entrypoint = (
                self._source
                / "asterion/applications/prime_agent/operator/p7_solving_broker_process.py"
            )
            if (
                not entrypoint.is_file()
                or entrypoint.is_symlink()
                or self._pycache.exists()
                or self._pycache.is_symlink()
            ):
                raise ValueError
            from .p7_runtime_lock import verify_p7_development_runtime

            runtime = verify_p7_development_runtime(self._runtime_root)
            command = (
                str(self._interpreter),
                "-I",
                "-X",
                f"pycache_prefix={self._pycache}",
                str(entrypoint),
                "--arc-agi-wheel-sha256",
                self._wheel_sha256,
                "--asterion-src",
                str(self._source),
                "--control-socket",
                str(self._control_socket),
                "--control-token",
                self._control_token,
                "--game-id",
                P7_SOLVING_GAME_ID,
                "--model-socket",
                str(self._model_socket),
                "--model-token",
                self._model_token,
                "--private-dir",
                str(self._private),
                "--resource-root",
                str(self._resource),
                "--resource-sha256",
                self._resource_sha256,
                "--runtime-root",
                str(self._runtime_root),
                "--runtime-sha256",
                runtime.runtime_sha256,
            )
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise ValueError
                if self._control_socket.exists():
                    if not _socket_is_private(self._control_socket, model=False):
                        raise ValueError
                    try:
                        ready = self._control("ready")
                    except _StartupTransient:
                        time.sleep(0.02)
                        continue
                    if ready != {"ready": True} or not _socket_is_private(
                        self._model_socket, model=True
                    ):
                        raise ValueError
                    return p7_solving_client_module_bytes(
                        client_socket_path, self._model_token
                    )
                time.sleep(0.02)
            raise ValueError
        except BaseException:
            self.close()
            raise P7SolvingBrokerServiceError() from None

    def _control(self, method: str) -> dict[str, object]:
        if method not in {"close", "presentation", "ready", "replay", "seal"}:
            raise P7SolvingBrokerServiceError()
        sequence = self._control_sequence + 1
        raw = (
            _canonical(
                {
                    "data": {},
                    "method": method,
                    "sequence": sequence,
                    "token": self._control_token,
                }
            )
            + b"\n"
        )
        if len(raw) > _FRAME_CAP or not _socket_is_private(
            self._control_socket, model=False
        ):
            raise P7SolvingBrokerServiceError()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(30)
                client.connect(str(self._control_socket))
                client.sendall(raw)
                response = client.makefile("rb").readline(_FRAME_CAP + 1)
            if not response.endswith(b"\n") or len(response) > _FRAME_CAP:
                raise ValueError
            body = response[:-1]
            value = json.loads(body.decode("utf-8", "strict"))
            if (
                _canonical(value) != body
                or type(value) is not dict
                or set(value) != {"ok", "result"}
                or value["ok"] is not True
                or type(value["result"]) is not dict
            ):
                raise ValueError
            self._control_sequence = sequence
            return value["result"]
        except OSError as error:
            if error.errno in (errno.ECONNREFUSED, errno.ENOENT):
                raise _StartupTransient() from None
            raise P7SolvingBrokerServiceError() from None
        except (UnicodeError, ValueError, json.JSONDecodeError):
            raise P7SolvingBrokerServiceError() from None

    @staticmethod
    def _allow_public(
        value: dict[str, object], fields: set[str], digest_field: str
    ) -> dict[str, object]:
        if (
            type(value) is not dict
            or set(value) != fields
            or type(value["action_count"]) is not int
            or not 0 <= value["action_count"] <= 500
            or type(value["levels_completed"]) is not int
            or value["levels_completed"] not in (0, 1)
            or type(value["score"]) is not str
            or _SCORE.fullmatch(value["score"]) is None
            or type(value["score_sha256"]) is not str
            or _DIGEST.fullmatch(value["score_sha256"]) is None
            or type(value[digest_field]) is not str
            or _DIGEST.fullmatch(value[digest_field]) is None
            or value["terminal_reason"]
            not in {"action-cap", "engine-invalid", "level-completed"}
            or (value["terminal_reason"] == "level-completed")
            != (value["levels_completed"] == 1)
        ):
            raise P7SolvingBrokerServiceError()
        return value

    def seal(self) -> dict[str, object]:
        return self._allow_public(
            self._control("seal"), _PUBLIC_SEAL_FIELDS, "transcript_sha256"
        )

    def replay(self) -> dict[str, object]:
        return self._allow_public(
            self._control("replay"), _PUBLIC_REPLAY_FIELDS, "replay_sha256"
        )

    def presentation(self) -> dict[str, object]:
        value = self._control("presentation")
        if type(value) is not dict or set(value) != _PRESENTATION_FIELDS:
            raise P7SolvingBrokerServiceError()
        try:
            from .p7_solving_broker import _valid_grid, normalize_p7_action

            actions = value["applied_actions"]
            if (
                type(value["action_count"]) is not int
                or not 0 <= value["action_count"] <= 500
                or type(actions) is not list
                or len(actions) != value["action_count"]
                or any(normalize_p7_action(item) != item for item in actions)
                or type(value["levels_completed"]) is not int
                or value["levels_completed"] not in (0, 1)
                or type(value["score"]) is not str
                or _SCORE.fullmatch(value["score"]) is None
                or value["terminal_reason"]
                not in {"action-cap", "engine-invalid", "level-completed"}
                or (value["terminal_reason"] == "level-completed")
                != (value["levels_completed"] == 1)
                or not _valid_grid(value["initial_grid"])
                or not _valid_grid(value["completion_grid"])
            ):
                raise ValueError
            _canonical(value)
        except BaseException:
            raise P7SolvingBrokerServiceError() from None
        return value

    def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        self._control("close")
                    except (P7SolvingBrokerServiceError, _StartupTransient):
                        pass
                    try:
                        process.wait(2)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(2)
            finally:
                pass
        if self._private_created:
            shutil.rmtree(self._private, ignore_errors=True)


__all__ = ("P7SolvingBrokerService", "P7SolvingBrokerServiceError")
