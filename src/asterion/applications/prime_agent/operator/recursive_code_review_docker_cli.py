"""Fixed command construction for the sealed P3 recursive-review worker."""

from __future__ import annotations

import re

from asterion.services.restricted_worker import RestrictedWorkerError


_CONTAINER = re.compile(r"prime-p3-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ENTRYPOINT = "/usr/local/bin/prime-recursive-code-review.mjs"


class RecursiveCodeReviewDockerCli:
    """Construct the one fixed P3 Docker create request, with no options surface."""

    def __init__(
        self, *, docker_executable: str, socket_path: str, seccomp_profile: str
    ) -> None:
        if not all(
            type(value) is str and value.startswith("/") and "\x00" not in value
            for value in (docker_executable, socket_path, seccomp_profile)
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._prefix = (docker_executable, "--host", "unix://" + socket_path)
        self._seccomp = seccomp_profile

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
                "create", "--name", container_id, "--pull=never", "--network", "none",
                "--read-only", "--user", "65534:65534", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--security-opt",
                "seccomp=" + self._seccomp, "--tmpfs",
                "/workspace:rw,nodev,noexec,nosuid,size=67108864", "--pid", "private",
                "--ipc", "private", "--uts", "private", "--pids-limit", "256",
                "--memory", "536870912", "--memory-swap", "536870912", "--cpus", "1",
                "--restart", "no", "--entrypoint", _ENTRYPOINT, image_digest,
            ),
            {},
        )
