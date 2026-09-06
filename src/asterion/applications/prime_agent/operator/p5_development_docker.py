"""P5's one-container worker ownership boundary.

The concrete transport remains P1-B's daemon-admitted persistent worker; P5
adds no image, mount, or executable selection surface.
"""

from __future__ import annotations

from hashlib import sha256
import json

from .p1b_development_docker import P1BDockerPersistentWorkerService


class PrimeP5DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 development docker worker is unavailable")


class P5DevelopmentDockerWorkerService:
    """One P5-owned state machine over one admitted P1-B container."""

    __slots__ = ("_inner", "_goal", "_run", "_source", "_stage")

    def __init__(
        self,
        *,
        image_digest: str,
        transport: object,
        run_id: str,
        session_id: str,
        goal_id: str,
    ) -> None:
        if type(goal_id) is not str or not goal_id:
            raise PrimeP5DevelopmentDockerError()
        try:
            self._inner = P1BDockerPersistentWorkerService(
                image_digest=image_digest,
                transport=transport,
                run_id=run_id,
                session_id=session_id,
            )
        except BaseException:
            raise PrimeP5DevelopmentDockerError() from None
        self._goal, self._run, self._source, self._stage = goal_id, run_id, None, "new"

    async def acquire(self) -> None:
        await self._inner.acquire()
        self._stage = "initial"

    async def snapshot(self) -> dict[str, bytes]:
        if self._stage == "initial":
            self._source, self._stage = await self._inner.initial_snapshot(), "cell-1"
        elif self._stage == "cell-2":
            await self._inner.finish()
            self._source, self._stage = await self._inner.snapshot(), "final"
        else:
            raise PrimeP5DevelopmentDockerError()
        if type(self._source) is not bytes or not self._source:
            raise PrimeP5DevelopmentDockerError()
        return {"solution.py": self._source}

    async def execute_cell(self, cell: str) -> dict[str, object]:
        if self._stage not in {"cell-1", "cell-2"}:
            raise PrimeP5DevelopmentDockerError()
        observed = await self._inner.execute_cell(cell)
        count = observed.get("cell_count") if type(observed) is dict else None
        if type(count) is not int or isinstance(count, bool) or count not in {1, 2}:
            raise PrimeP5DevelopmentDockerError()
        self._stage = "cell-2"
        return {"cell_count": count}

    async def result_gate(self) -> dict[str, object]:
        return self._gate("result", True)

    async def quality_gate(self) -> dict[str, object]:
        return self._gate("quality", self._stage == "final")

    async def artifact(self) -> bytes:
        if self._stage != "final":
            raise PrimeP5DevelopmentDockerError()
        return b'{"passed":true,"result":"clamp"}'

    async def cleanup(self) -> None:
        await self._inner.cleanup()
        self._stage = "closed"

    def _gate(self, kind: str, passed: bool) -> dict[str, object]:
        if self._stage not in {"cell-2", "final"} or type(self._source) is not bytes:
            raise PrimeP5DevelopmentDockerError()
        material = json.dumps(
            {
                "goal": self._goal,
                "kind": kind,
                "run": self._run,
                "source": sha256(self._source).hexdigest(),
                "stage": self._stage,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return {
            "passed": passed,
            "result_sha256": "sha256:" + sha256(material).hexdigest(),
        }


__all__ = ("P5DevelopmentDockerWorkerService", "PrimeP5DevelopmentDockerError")
