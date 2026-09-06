from __future__ import annotations
import argparse
from pathlib import Path
from asterion.applications.prime_agent.operator.development_preparation import (
    PrimeDevelopmentPreparationError,
    prepare_prime_development,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", choices=[f"p{i}" for i in range(1, 8)], action="append"
    )
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    scenarios = (
        tuple(f"p{i}" for i in range(1, 8)) if args.all else tuple(args.scenario or ())
    )
    if not scenarios:
        parser.error("one --scenario or --all is required")
    try:
        prepared = prepare_prime_development(
            Path(__file__).resolve().parents[1],
            scenarios,
            emit=lambda c, s: print(
                f"[prepare] {c}: {s}", file=__import__("sys").stderr
            ),
        )
    except PrimeDevelopmentPreparationError:
        return 1
    for scenario in prepared:
        print(f"prime-{scenario} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
