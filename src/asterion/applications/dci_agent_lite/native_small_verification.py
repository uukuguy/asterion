"""Application-owned configuration bridge for Native small verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import os
import secrets
import subprocess
import sys

from dotenv import dotenv_values

from asterion.control.authority import BudgetUsage
from asterion.control.providers.native.bounded import (
    NativeBoundedReservation,
    NativeBoundedTurnHost,
)
from asterion.control.providers.native.model import NativeTurnRequest, NativeTurnResult


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
class PrimeNativeSmallVerificationHost:
    """Project one controlled Prime run into a bounded Native turn."""

    runner: Callable[[], Mapping[str, object]] = field(
        default=lambda: _run_prime_native_small_verification(Path.cwd()), repr=False
    )

    async def execute(
        self,
        reservation: NativeBoundedReservation,
        request: NativeTurnRequest,
    ) -> NativeTurnResult:
        try:
            report = self.runner()
            usage = _validated_bounded_usage(report, reservation.max_cost_micros)
            tokens = usage["aggregate_tokens"]
            return NativeTurnResult(
                request.turn_id,
                (),
                BudgetUsage(tokens, 0, 0, tokens, usage["cost_micros"]),
            )
        except (KeyError, TypeError, ValueError):
            raise NativeSmallVerificationApplicationError from None


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


def _run_prime_native_small_verification(repo_root: Path) -> Mapping[str, object]:
    """Invoke the existing explicit bounded runner without returning its output."""

    try:
        completed = subprocess.run(
            (
                sys.executable,
                "tools/verify_prime_loop.py",
                "--level",
                "native-rlm-bounded",
                "--native-rlm-experiment",
                "--source-root",
                "3th-party/prime-agent",
            ),
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=660,
        )
        if completed.returncode != 0:
            raise ValueError
        report = json.loads(completed.stdout)
        if not isinstance(report, Mapping):
            raise ValueError
        return report
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        raise NativeSmallVerificationApplicationError from None


def _validated_bounded_usage(
    report: Mapping[str, object], max_cost_micros: int
) -> Mapping[str, int]:
    """Accept only an exact body-free completion report from that runner."""

    try:
        usage = report["usage"]
        if (
            set(report) != {
                "status", "level", "terminal", "child_started",
                "message_delivered", "child_deleted", "checkpoint_recovered",
                "detach_attached", "cancelled", "budget_limited",
                "child_model_selected", "generated_program_admitted",
                "recursion_depth_limited", "provider_operations",
                "application_operations", "usage", "full_dataset_ran",
            }
            or report["status"] != "PASS"
            or report["level"] != "native-rlm-bounded"
            or report["terminal"] != "completed"
            or report["generated_program_admitted"] is not True
            or report["provider_operations"] != 1
            or report["application_operations"] != 1
            or report["full_dataset_ran"] is not False
            or not isinstance(usage, Mapping)
            or set(usage) != {"aggregate_tokens", "cost_micros"}
        ):
            raise ValueError
        tokens = usage["aggregate_tokens"]
        cost = usage["cost_micros"]
        if (
            isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 1
            or isinstance(cost, bool) or not isinstance(cost, int) or cost < 0
            or cost > max_cost_micros
        ):
            raise ValueError
        return {"aggregate_tokens": tokens, "cost_micros": cost}
    except (KeyError, TypeError, ValueError):
        raise NativeSmallVerificationApplicationError from None


__all__ = (
    "NativeSmallVerificationApplicationError",
    "NativeSmallVerificationOperatorResolver",
    "PrimeNativeSmallVerificationHost",
)
