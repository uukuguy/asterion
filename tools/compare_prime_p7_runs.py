from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceEntry
from asterion.applications.prime.p7.comparison import compare_runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asterion", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    return parser


def _load_trace(path: Path) -> tuple[PrimeTraceEntry, ...]:
    entries: list[PrimeTraceEntry] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(raw)
        if type(value) is not dict:
            raise ValueError("P7 trace is invalid")
        entries.append(
            PrimeTraceEntry(
                sequence=value["sequence"],
                kind=value["kind"],
                identities=value["identities"],
                payload=value["payload"],
                previous_sha256=value["previous_sha256"],
                sha256=value["sha256"],
            )
        )
    return tuple(entries)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asterion = _load_trace(Path(args.asterion).resolve(strict=True))
        baseline = _load_trace(Path(args.baseline).resolve(strict=True))
        comparison = compare_runs(asterion, baseline)
        report = {
            "schema": "asterion.prime.p7-live-comparison/v1",
            "asterion_label": "asterion-prime-live",
            "baseline_label": "operator-stopped",
            "comparison": asdict(comparison),
        }
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, allow_nan=False, separators=(",", ":"), sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
