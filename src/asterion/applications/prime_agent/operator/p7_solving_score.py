"""Runtime-bound official partial-game score projection for P7a."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import importlib
import importlib.util
import math
from pathlib import Path
import sys
import sysconfig
from typing import Callable
import zipfile

from .p7_solving_workload import (
    P7_SOLVING_ACTION_CAP,
    P7_SOLVING_ARC_AGI_WHEEL_SHA256,
    P7_SOLVING_BASELINE_ACTIONS,
    P7_SOLVING_GAME_ID,
)


class P7SolvingScoreError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 solving score is unavailable")


class P7SolvingScoreCalculator:
    """A calculator class loaded only after the current runtime passes its lock."""

    __slots__ = ("_calculator_type", "_runtime_sha256")

    def __init__(self, *_: object, **__: object) -> None:
        raise P7SolvingScoreError()

    @classmethod
    def _from_verified(
        cls, calculator_type: Callable[[], object], runtime_sha256: str
    ) -> P7SolvingScoreCalculator:
        value = object.__new__(cls)
        value._calculator_type = calculator_type
        value._runtime_sha256 = runtime_sha256
        return value

    def calculate(
        self,
        action_count: object,
        *,
        baseline_actions: object = P7_SOLVING_BASELINE_ACTIONS,
    ) -> str:
        return _calculate_p7_partial_score(
            action_count,
            baseline_actions=baseline_actions,
            calculator_factory=self._calculator_type,
        )

    def __repr__(self) -> str:
        return "P7SolvingScoreCalculator(redacted)"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def bind_p7_solving_score_calculator(
    runtime_root: object, *, runtime_sha256: object
) -> P7SolvingScoreCalculator:
    """Verify and bind the exact current interpreter's locked calculator code."""

    if "arc_agi" in sys.modules or "arc_agi.scorecard" in sys.modules:
        raise P7SolvingScoreError()
    try:
        from .p7_runtime_lock import verify_p7_development_runtime

        if (
            not isinstance(runtime_root, Path)
            or not runtime_root.is_absolute()
            or runtime_root.resolve(strict=True) != runtime_root
            or type(runtime_sha256) is not str
        ):
            raise ValueError
        verified = verify_p7_development_runtime(runtime_root)
        if verified.runtime_sha256 != runtime_sha256:
            raise ValueError
        venv = runtime_root / "venv"
        interpreter = venv / "bin/python3"
        purelib = Path(sysconfig.get_path("purelib"))
        venv_resolved = venv.resolve(strict=True)
        if (
            Path(sys.executable) != interpreter
            or Path(sys.prefix).resolve(strict=True) != venv_resolved
            or not purelib.is_absolute()
            or not _inside(purelib.resolve(strict=True), venv_resolved)
        ):
            raise ValueError
        package_path = purelib / "arc_agi/__init__.py"
        scorecard_path = purelib / "arc_agi/scorecard.py"
        package_spec = importlib.util.find_spec("arc_agi")
        if package_spec is None or package_spec.origin != str(package_path):
            raise ValueError
        wheel = runtime_root / "wheels/arc_agi-0.9.9-py3-none-any.whl"
        with zipfile.ZipFile(wheel) as archive:
            if archive.read("arc_agi/scorecard.py") != scorecard_path.read_bytes():
                raise ValueError
        module = importlib.import_module("arc_agi.scorecard")
        calculator_type = getattr(module, "EnvironmentScoreCalculator")
        if (
            Path(getattr(module, "__file__", "")).resolve(strict=True)
            != scorecard_path
            or getattr(calculator_type, "__module__", None) != "arc_agi.scorecard"
        ):
            raise ValueError
        return P7SolvingScoreCalculator._from_verified(
            calculator_type, verified.runtime_sha256
        )
    except BaseException:
        for name in ("arc_agi.scorecard", "arc_agi"):
            sys.modules.pop(name, None)
        raise P7SolvingScoreError() from None


def _calculate_p7_partial_score(
    action_count: object,
    *,
    baseline_actions: object,
    calculator_factory: Callable[[], object],
) -> str:
    if (
        type(action_count) is not int
        or not 1 <= action_count <= P7_SOLVING_ACTION_CAP
        or type(baseline_actions) is not tuple
        or baseline_actions != P7_SOLVING_BASELINE_ACTIONS
        or any(type(item) is not int for item in baseline_actions)
    ):
        raise P7SolvingScoreError()
    try:
        calculator = calculator_factory()
        add_level = getattr(calculator, "add_level")
        for index, baseline in enumerate(P7_SOLVING_BASELINE_ACTIONS, 1):
            add_level(
                index,
                index == 1,
                action_count if index == 1 else 0,
                baseline,
                P7_SOLVING_GAME_ID,
            )
        score = getattr(getattr(calculator, "to_score")(), "score")
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 100
        ):
            raise ValueError
        value = Decimal(str(score)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_EVEN
        )
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("100"):
            raise ValueError
        return format(value, ".6f")
    except (AttributeError, InvalidOperation, TypeError, ValueError, ArithmeticError):
        raise P7SolvingScoreError() from None


def official_p7_partial_score(
    action_count: object,
    *,
    calculator: object = None,
    baseline_actions: object = P7_SOLVING_BASELINE_ACTIONS,
) -> str:
    """Score through a calculator already bound to the verified current runtime."""

    if type(calculator) is not P7SolvingScoreCalculator:
        raise P7SolvingScoreError()
    return calculator.calculate(action_count, baseline_actions=baseline_actions)


__all__ = (
    "P7SolvingScoreCalculator",
    "P7SolvingScoreError",
    "P7_SOLVING_ARC_AGI_WHEEL_SHA256",
    "P7_SOLVING_BASELINE_ACTIONS",
    "bind_p7_solving_score_calculator",
    "official_p7_partial_score",
)
