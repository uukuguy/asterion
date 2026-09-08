"""Static source-detachment gate for the Asterion-prime release path."""

from __future__ import annotations

from pathlib import Path


FORBIDDEN = tuple(
    "".join(parts)
    for parts in (
        ("prime", "SourceRoot"),
        ("ASTERION_", "PRIME_SOURCE_ROOT"),
        ("createAgent", "Session"),
        ("loadPrime", "Sdk"),
        ("3th-party/", "prime-agent"),
    )
)


def assert_asterion_prime_source_detached(root: Path) -> None:
    """Reject Prime Agent source references in Asterion-prime release code."""
    owned = (
        root / "src/asterion/agents/prime",
        root / "src/asterion/runtimes/asterion_prime.py",
    )
    for path in (
        child
        for base in owned
        if base.exists()
        for child in ([base] if base.is_file() else base.rglob("*"))
    ):
        if path.is_file() and path.suffix in {".py", ".ts", ".mjs", ".json"}:
            body = path.read_text(encoding="utf-8")
            if any(token in body for token in FORBIDDEN):
                raise AssertionError("Asterion-prime source dependency is forbidden")
