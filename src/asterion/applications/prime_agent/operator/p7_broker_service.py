"""Host-owned lifecycle wrapper for the isolated P7 broker process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time

from .p7_broker_process import p7_model_client_module_bytes
from .p7_development_workload import P7_DEVELOPMENT_GAME_ID


class P7BrokerServiceError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 broker service is unavailable")


def _canonical(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


class P7BrokerService:
    """One host-owned external process; model code receives only client bytes."""

    def __init__(self, *, interpreter: Path, asterion_src: Path, resource_root: Path, private_dir: Path | None = None) -> None:
        if not all(isinstance(item, Path) and item.is_absolute() for item in (interpreter, asterion_src, resource_root)):
            raise P7BrokerServiceError()
        if not interpreter.is_file() or not asterion_src.is_dir() or not resource_root.is_dir():
            raise P7BrokerServiceError()
        self._interpreter = interpreter
        self._source = asterion_src
        self._resource = resource_root
        self._temporary = private_dir is None
        self._private = Path(tempfile.mkdtemp(prefix="asterion-p7-")) if private_dir is None else private_dir
        self._process: subprocess.Popen[bytes] | None = None
        self._model_socket = self._private / "model.sock"
        self._control_socket = self._private / "control.sock"
        self._model_token = secrets.token_hex(32)
        self._control_token = secrets.token_hex(32)
        self._control_sequence = 0

    def __repr__(self) -> str:
        return "P7BrokerService(redacted)"

    def start(self, *, client_socket_path: str = "/broker/model.sock") -> bytes:
        if self._process is not None:
            raise P7BrokerServiceError()
        if (
            type(client_socket_path) is not str
            or client_socket_path != "/broker/model.sock"
        ):
            raise P7BrokerServiceError()
        try:
            if self._temporary:
                os.chmod(self._private, 0o711)
            else:
                self._private.mkdir(mode=0o711, parents=True, exist_ok=False)
            entrypoint = self._source / "asterion/applications/prime_agent/operator/p7_broker_process.py"
            command = (str(self._interpreter), str(entrypoint), "--asterion-src", str(self._source), "--resource-root", str(self._resource), "--private-dir", str(self._private), "--model-socket", str(self._model_socket), "--control-socket", str(self._control_socket), "--model-token", self._model_token, "--control-token", self._control_token, "--game-id", P7_DEVELOPMENT_GAME_ID)
            self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise ValueError
                if self._control_socket.exists():
                    if stat.S_IMODE(self._private.stat().st_mode) != 0o711 or stat.S_IMODE(self._control_socket.stat().st_mode) != 0o600:
                        raise ValueError
                    if self._control("ready") == {"ready": True}:
                        # The model runs in a container: never disclose the host-private
                        # socket pathname in the generated module.
                        return p7_model_client_module_bytes(client_socket_path, self._model_token)
                time.sleep(.02)
            raise ValueError
        except BaseException:
            self.close()
            raise P7BrokerServiceError() from None

    def _control(self, method: str) -> dict[str, object]:
        self._control_sequence += 1
        request = {"token": self._control_token, "sequence": self._control_sequence, "method": method, "data": {}}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(10)
                client.connect(str(self._control_socket))
                client.sendall(_canonical(request) + b"\n")
                raw = client.makefile("rb").readline(65537)
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {"ok", "result"} or value["ok"] is not True or type(value["result"]) is not dict:
                raise ValueError
            return value["result"]
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            raise P7BrokerServiceError() from None

    def seal(self) -> dict[str, object]: return self._control("seal")
    def replay(self) -> dict[str, object]: return self._control("replay")

    def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        self._control("close")
                    except P7BrokerServiceError:
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
                for path in (self._model_socket, self._control_socket):
                    try:
                        path.unlink()
                    except OSError:
                        pass
        if self._temporary:
            shutil.rmtree(self._private, ignore_errors=True)


__all__ = ("P7BrokerService", "P7BrokerServiceError")
