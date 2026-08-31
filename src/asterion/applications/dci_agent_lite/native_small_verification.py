"""Application-owned configuration bridge for Native small verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import os
import secrets

from dotenv import dotenv_values

from asterion.control.providers.native.bounded import (
    NativeBoundedReservation,
    NativeBoundedTurnHost,
)


_MODEL_ENV = "ASTERION_PRIME_EXPERIMENT_MODEL"
_CREDENTIAL_ENV = "DEEPSEEK_API_KEY"
_ALLOWED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-flash-0731"})
_MAX_COST_MICROS = 500_000
_DEADLINE_MS = 600_000


class NativeSmallVerificationApplicationError(ValueError):
    """Raised without exposing private operator configuration."""

    def __init__(self, *_: object) -> None:
        super().__init__("native small verification is unavailable")
        self.__cause__ = None
        self.__context__ = None


@dataclass(frozen=True, repr=False)
class NativeSmallVerificationOperatorResolver:
    """Resolve the fixed private preset and an explicitly injected host."""

    environment_loader: Callable[[], Mapping[str, str]] = field(repr=False)
    host: NativeBoundedTurnHost = field(repr=False)

    @classmethod
    def from_repository(
        cls, repo_root: Path, host: NativeBoundedTurnHost
    ) -> NativeSmallVerificationOperatorResolver:
        root = Path(repo_root).resolve()
        return cls(
            environment_loader=lambda: _load_private_backend_environment(root),
            host=host,
        )

    def resolve(self) -> tuple[NativeBoundedReservation, NativeBoundedTurnHost]:
        try:
            environment = self.environment_loader()
            model = environment[_MODEL_ENV]
            credential = environment[_CREDENTIAL_ENV]
            if (
                not isinstance(model, str)
                or model not in _ALLOWED_MODELS
                or not isinstance(credential, str)
                or not credential
                or not callable(getattr(self.host, "execute", None))
            ):
                raise ValueError
            return (
                NativeBoundedReservation(
                    reservation_id="native-small-" + secrets.token_hex(16),
                    provider_digest=sha256(b"deepseek").hexdigest(),
                    model_digest=sha256(model.encode("utf-8")).hexdigest(),
                    max_turns=1,
                    max_cost_micros=_MAX_COST_MICROS,
                    deadline_ms=_DEADLINE_MS,
                ),
                self.host,
            )
        except (KeyError, TypeError, ValueError):
            raise NativeSmallVerificationApplicationError from None


def _load_private_backend_environment(repo_root: Path) -> Mapping[str, str]:
    """Read only the application-owned backend inputs needed by this preset."""

    try:
        values = dotenv_values(repo_root / ".env")
        process = os.environ
        environment = {
            key: process.get(key, values.get(key))
            for key in (_MODEL_ENV, _CREDENTIAL_ENV)
        }
        if any(not isinstance(value, str) or not value for value in environment.values()):
            raise ValueError
        return {key: value for key, value in environment.items() if isinstance(value, str)}
    except (OSError, TypeError, ValueError):
        raise NativeSmallVerificationApplicationError from None


__all__ = (
    "NativeSmallVerificationApplicationError",
    "NativeSmallVerificationOperatorResolver",
)
