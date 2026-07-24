#!/usr/bin/env python3
"""Prepare or validate external Asterion DCI resources."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from asterion.dci.resource_setup import ResourceSetupError, prepare_resources


PROJECT = Path(__file__).resolve().parents[1]


def _resource_root(value: str | None) -> Path:
    configured = value or os.environ.get("ASTERION_DCI_RESOURCE_ROOT", "").strip()
    return PROJECT if not configured else Path(configured)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or validate external Asterion DCI resources"
    )
    parser.add_argument("--profile", choices=("basic", "benchmark"), default="basic")
    parser.add_argument("--resource-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    try:
        result = prepare_resources(
            profile=arguments.profile,
            resource_root=_resource_root(
                None
                if arguments.resource_root is None
                else str(arguments.resource_root)
            ),
            source_root=arguments.source_root,
            check_only=arguments.check,
        )
    except ResourceSetupError as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "profile": arguments.profile,
                        "status": "FAIL",
                        "error": str(error),
                        "provider_backed_operation_count": 0,
                        "judge_operation_count": 0,
                        "full_dataset_ran": False,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"ERROR: {error}")
        return 2

    payload = {
        **asdict(result),
        "provider_backed_operation_count": 0,
        "judge_operation_count": 0,
        "full_dataset_ran": False,
    }
    if arguments.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"{result.status}: resource profile {result.profile}; "
            f"prepared={len(result.prepared)} present={len(result.present)} "
            f"missing={len(result.missing)}; Agent operations=0; "
            "Judge operations=0; full dataset=no"
        )
        for resource_id in result.missing:
            print(f"MISSING: {resource_id}")
        for diagnostic in result.diagnostics:
            print(f"REPAIR: {diagnostic}")
    return 0 if result.status == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
