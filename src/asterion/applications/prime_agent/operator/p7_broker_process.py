"""Standalone offline broker process entrypoint; no public game output."""

from __future__ import annotations
import os
from pathlib import Path
from .p7_development_workload import P7_DEVELOPMENT_GAME_ID


class P7BrokerProcessError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("P7 broker process is unavailable")


def p7_arcade_environment_root(resource_root: object) -> Path:
    if (
        not isinstance(resource_root, Path)
        or not resource_root.is_absolute()
        or resource_root.name != "9607627b"
        or resource_root.parent.name != "ls20"
    ):
        raise P7BrokerProcessError()
    return resource_root.parent.parent


def main() -> int:
    # Deliberately require an operator-owned external venv and explicit root.
    root = os.environ.get("ASTERION_P7_RESOURCE_ROOT")
    if root is None:
        return 1
    try:
        p7_arcade_environment_root(Path(root))
        if os.environ.get("ASTERION_P7_GAME_ID") != P7_DEVELOPMENT_GAME_ID:
            return 1
    except P7BrokerProcessError:
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
