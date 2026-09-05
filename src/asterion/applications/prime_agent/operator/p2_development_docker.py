"""Private fixed Docker adapter for the P2 one-cell development preset."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from time import monotonic

from .docker_cli import DockerCliEngineTransport, _CLEARED_BASE_IMAGE_ENVIRONMENT, _ENVIRONMENT, _TMPFS
from .docker_worker import _LifecycleCallControl

_RESULT_CAP = 4 * 1024
_CELL_CAP = 16 * 1024
_CELL_OUTPUT_CAP = 4 * 1024
_PROVISIONAL_SETTLE_SECONDS = 30.0
_PROVISIONAL_SETTLE_INTERVAL_SECONDS = 0.5
_PROVISIONAL_FINAL_GRACE_SECONDS = 5.0


class PrimeP2DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P2 development docker worker is unavailable")


@dataclass(frozen=True, repr=False)
class P2DevelopmentContainer:
    container_id: str
    run_id: str
    session_id: str

    def __repr__(self) -> str:
        return "P2DevelopmentContainer(redacted)"


class PrimeP2DevelopmentDockerTransport(DockerCliEngineTransport):
    """A no-network, non-root, fixed-image P2 container transport."""

    async def create(self, *, image_digest: str, run_id: str, session_id: str, control: _LifecycleCallControl) -> P2DevelopmentContainer:
        if not all(isinstance(item, str) and item for item in (image_digest, run_id, session_id)) or not image_digest.startswith("sha256:"):
            raise PrimeP2DevelopmentDockerError()
        name = "prime-p2-" + secrets.token_hex(16)
        fd, self._seccomp_profile_fd = self._seccomp_profile_fd, None  # type: ignore[attr-defined]
        if not isinstance(fd, int):
            raise PrimeP2DevelopmentDockerError()
        try:
            await self._preflight(control)  # type: ignore[attr-defined]
            argv = self._prefix + (  # type: ignore[attr-defined]
                "create", "--name", name, "--pull=never", "--platform", "/".join(x for x in (self._platform.os, self._platform.architecture, self._platform.variant) if x is not None),  # type: ignore[attr-defined]
                "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--security-opt", "seccomp=/proc/self/fd/" + str(fd), "--tmpfs", _TMPFS,
                "--env", _ENVIRONMENT[0], "--env", _ENVIRONMENT[1], "--env", _ENVIRONMENT[2],
                "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[0], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[1], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[2], "--env", _CLEARED_BASE_IMAGE_ENVIRONMENT[3],
                "--pids-limit", "64", "--memory", "268435456", "--memory-swap", "268435456", "--cpus", "1", "--restart", "no", image_digest,
            )
            result = await self._call(argv, control, pass_fds=(fd,))  # type: ignore[attr-defined]
            return P2DevelopmentContainer(self._parse_daemon_id(result.stdout), run_id, session_id)  # type: ignore[attr-defined]
        except BaseException as error:
            cleanup = asyncio.create_task(self._remove_name(name))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    pass
            try:
                cleanup.result()
            except BaseException:
                raise PrimeP2DevelopmentDockerError() from None
            if isinstance(error, asyncio.CancelledError):
                raise
            raise PrimeP2DevelopmentDockerError() from None
        finally:
            self._close_fd(fd)  # type: ignore[attr-defined]

    async def start(self, container: P2DevelopmentContainer, control: _LifecycleCallControl) -> None:
        await self._call(self._prefix + ("container", "start", container.container_id), control)  # type: ignore[attr-defined]

    async def execute_cell(self, container: P2DevelopmentContainer, cell: str, control: _LifecycleCallControl) -> None:
        if not isinstance(cell, str) or not cell or len(cell.encode("utf-8")) > _CELL_CAP:
            raise PrimeP2DevelopmentDockerError()
        # The SDK's sole ipython tool maps to this fixed IPython cell entrypoint.
        # Bounded output stays private; the SDK receives only a fixed success value.
        await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", "--env", "HOME=/workspace", container.container_id, "/usr/local/bin/ipython", "--no-banner", "--no-confirm-exit", "-c", cell), control, max_output_bytes=_CELL_OUTPUT_CAP)  # type: ignore[attr-defined]

    async def read_result(self, container: P2DevelopmentContainer, control: _LifecycleCallControl) -> bytes:
        result = await self._call(self._prefix + ("container", "exec", "--user", "65534:65534", container.container_id, "cat", "/workspace/result.json"), control, max_output_bytes=_RESULT_CAP)  # type: ignore[attr-defined]
        if len(result.stdout) > _RESULT_CAP or result.stderr:
            raise PrimeP2DevelopmentDockerError()
        return result.stdout

    async def remove(self, container: P2DevelopmentContainer, control: _LifecycleCallControl) -> None:
        result = await self._call(
            self._prefix
            + ("container", "rm", "--force", container.container_id),
            control,
        )  # type: ignore[attr-defined]
        if result.stdout not in (b"", (container.container_id + "\n").encode()) or result.stderr:
            raise PrimeP2DevelopmentDockerError()

    async def assert_absent(self, container: P2DevelopmentContainer, control: _LifecycleCallControl) -> None:
        result = await self._call_raw(
            self._prefix
            + (
                "container",
                "inspect",
                "--format",
                "{{.Id}}",
                container.container_id,
            ),
            control,
        )  # type: ignore[attr-defined]
        absent_errors = {
            ("Error: No such object: " + container.container_id + "\n").encode(),
            ("Error: No such container: " + container.container_id + "\n").encode(),
            (
                "Error response from daemon: No such container: "
                + container.container_id
                + "\n"
            ).encode(),
            ("No such container: " + container.container_id).encode(),
        }
        if (
            result.returncode != 1
            or result.stdout not in (b"", b"\n")
            or result.stderr not in absent_errors
        ):
            raise PrimeP2DevelopmentDockerError()

    async def _remove_name(self, name: str) -> None:
        deadline = monotonic() + _PROVISIONAL_SETTLE_SECONDS

        while monotonic() < deadline:
            await self._remove_then_inspect_name(
                name, _LifecycleCallControl(deadline, None)
            )
            remaining = deadline - monotonic()
            if remaining > 0:
                await asyncio.sleep(
                    min(_PROVISIONAL_SETTLE_INTERVAL_SECONDS, remaining)
                )
        final_deadline = monotonic() + _PROVISIONAL_FINAL_GRACE_SECONDS
        while True:
            if await self._remove_then_inspect_name(
                name, _LifecycleCallControl(final_deadline, None)
            ):
                return
            remaining = final_deadline - monotonic()
            if remaining <= 0:
                raise PrimeP2DevelopmentDockerError()
            await asyncio.sleep(
                min(_PROVISIONAL_SETTLE_INTERVAL_SECONDS, remaining)
            )

    async def _remove_then_inspect_name(
        self, name: str, control: _LifecycleCallControl
    ) -> bool:
        missing = (b"", b"\n")
        absent_errors = _absent_errors(name)
        removed = await self._call_raw(
            self._prefix + ("container", "rm", "--force", name), control
        )  # type: ignore[attr-defined]
        if removed.returncode == 0:
            if removed.stdout not in (b"", (name + "\n").encode()) or removed.stderr:
                raise PrimeP2DevelopmentDockerError()
        elif (
            removed.returncode != 1
            or removed.stdout not in missing
            or removed.stderr not in absent_errors
        ):
            raise PrimeP2DevelopmentDockerError()
        inspected = await self._call_raw(
            self._prefix
            + ("container", "inspect", "--format", "{{.Id}}", name),
            control,
        )  # type: ignore[attr-defined]
        if (
            inspected.returncode == 1
            and inspected.stdout in missing
            and inspected.stderr in absent_errors
        ):
            return True
        if inspected.returncode == 0 and not inspected.stderr:
            self._parse_daemon_id(inspected.stdout)  # type: ignore[attr-defined]
            return False
        raise PrimeP2DevelopmentDockerError()


def _absent_errors(identity: str) -> set[bytes]:
    return {
        ("Error: No such object: " + identity + "\n").encode(),
        ("Error: No such container: " + identity + "\n").encode(),
        (
            "Error response from daemon: No such container: " + identity + "\n"
        ).encode(),
        ("No such container: " + identity).encode(),
    }


__all__ = ("P2DevelopmentContainer", "PrimeP2DevelopmentDockerError", "PrimeP2DevelopmentDockerTransport")
