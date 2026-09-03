"""Fixed command construction for the sealed P2 Docker facade."""

from __future__ import annotations
import re
from asterion.services.restricted_worker import RestrictedWorkerError

_CONTAINER = re.compile(r"prime-p2-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ProgrammaticLongContextDockerCli:
    def __init__(
        self, *, docker_executable: str, socket_path: str, seccomp_profile: str
    ) -> None:
        if not all(
            type(v) is str and v.startswith("/") and "\x00" not in v
            for v in (docker_executable, socket_path, seccomp_profile)
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._prefix, self._seccomp = (
            (docker_executable, "--host", "unix://" + socket_path),
            seccomp_profile,
        )

    def create_argv(
        self, *, container_id: str, image_digest: str
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        if (
            _CONTAINER.fullmatch(container_id) is None
            or _DIGEST.fullmatch(image_digest) is None
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return (
            self._prefix
            + (
                "create",
                "--name",
                container_id,
                "--pull=never",
                "--network",
                "none",
                "--read-only",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--security-opt",
                "seccomp=" + self._seccomp,
                "--tmpfs",
                "/workspace:rw,nodev,noexec,nosuid,size=67108864",
                "--pid",
                "private",
                "--ipc",
                "private",
                "--uts",
                "private",
                "--pids-limit",
                "256",
                "--memory",
                "536870912",
                "--memory-swap",
                "536870912",
                "--cpus",
                "1",
                "--restart",
                "no",
                "--entrypoint",
                "/usr/local/bin/prime-programmatic-long-context.mjs",
                image_digest,
            ),
            {},
        )
