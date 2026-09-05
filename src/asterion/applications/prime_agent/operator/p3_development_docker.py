"""P3 role-isolated worker identities (operator transport is injected)."""
from __future__ import annotations
from dataclasses import dataclass

_ROLES = frozenset({"root", "implementation", "review"})

class PrimeP3DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None: super().__init__("prime P3 development docker worker is unavailable")

@dataclass(frozen=True, repr=False)
class PrimeP3DevelopmentWorker:
    role: str
    workspace: str
    rlm_socket: str | None
    def __post_init__(self) -> None:
        if self.role not in _ROLES or not self.workspace.startswith("/") or (self.role == "root") != (self.rlm_socket is not None):
            raise PrimeP3DevelopmentDockerError()

def p3_worker_identities(workspace: object, rlm_socket: object) -> tuple[PrimeP3DevelopmentWorker, ...]:
    if type(workspace) is not str or type(rlm_socket) is not str or not workspace.startswith("/") or not rlm_socket.startswith("/"):
        raise PrimeP3DevelopmentDockerError()
    return (PrimeP3DevelopmentWorker("root", workspace, rlm_socket), PrimeP3DevelopmentWorker("implementation", workspace, None), PrimeP3DevelopmentWorker("review", workspace, None))

__all__ = ("PrimeP3DevelopmentDockerError", "PrimeP3DevelopmentWorker", "p3_worker_identities")
