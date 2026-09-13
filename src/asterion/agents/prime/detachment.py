"""Semantic source-detachment gate for the Asterion Prime release path.

Rejects Prime Agent checkout locators, source-root environment variables, and
Prime Agent execution edges anywhere in an Asterion-owned release surface.

The rule is semantic, not string-specific. Renaming or relocating a checkout
does not make it an allowed dependency, and an allowed Asterion-owned root must
not be rejected merely for containing the word "prime".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCAN_ROOTS = (
    "src/asterion",
    "packages/typescript",
    "tools",
    "tests",
    "Makefile",
    "pyproject.toml",
)

SKIP_DIRS = frozenset({"node_modules", "dist", "build", "__pycache__", ".venv"})
SCAN_SUFFIXES = frozenset({".py", ".ts", ".mjs", ".json", ".toml", ".mk", ".txt"})
SCAN_NAMES = frozenset({"Makefile"})


def _joined(*parts: str) -> str:
    """Assemble a forbidden token without writing it literally.

    This module lives under a scanned root, so a literal token here would make
    the gate flag its own source and never pass.
    """
    return "".join(parts)


# Paths/locators that identify a Prime Agent checkout or its build output.
FORBIDDEN_LOCATORS = (
    _joined("3th-party/", "prime-agent"),
    _joined("packages/", "coding-agent/dist"),
    _joined("prime-gateway/resources/", "prime-"),
)

# Environment variables whose value is a Prime source root.
FORBIDDEN_ENV_VARS = (
    _joined("ASTERION_PRIME_", "SOURCE_ROOT"),
    _joined("ASTERION_OPERATIONAL_PRIME_", "SOURCE_ROOT"),
    _joined("PRIME_AGENT_", "CODING_AGENT_DIR"),
    _joined("PRIME_AGENT_", "KERNEL_PYTHON"),
    _joined("PRIME_AGENT_", "KERNEL_VENV"),
)

# Modules that carry a Prime Agent execution edge.
FORBIDDEN_IMPORTS = (
    _joined("asterion.applications.", "prime_agent"),
    _joined("asterion.capabilities.", "prime_agent"),
    _joined("asterion.runtimes.", "prime_agent"),
    _joined("asterion.control.providers.", "prime"),
)

# Prime SDK identifiers. These three were enforced by the gate this one
# replaces; dropping any of them is a coverage regression, because the Prime
# SDK session factory and the SDK loader are exactly the execution edge the
# design forbids, and the source-root getter is a checkout locator under
# another name.
FORBIDDEN_SDK_TOKENS = (
    _joined("prime", "SourceRoot"),
    _joined("createAgent", "Session"),
    _joined("loadPrime", "Sdk"),
)

# Asterion-owned values that legitimately contain "prime" and must never be
# rejected: ASTERION_PRIME_OPERATOR_ROOT is the Asterion repo/install root and
# ASTERION_PRIME_NODE is a resolved node executable path.
ALLOWED_ENV_VARS = ("ASTERION_PRIME_OPERATOR_ROOT", "ASTERION_PRIME_NODE")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str


def _iter_surface_files(root: Path):
    for rel in SCAN_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for child in base.rglob("*"):
            if not child.is_file():
                continue
            # Skip decisions must use the path RELATIVE to root. Using absolute
            # parts means a checkout under a directory named build/, dist/ or
            # .venv/ silences the entire scan.
            if SKIP_DIRS.intersection(child.relative_to(root).parts):
                continue
            if child.suffix in SCAN_SUFFIXES or child.name in SCAN_NAMES:
                yield child


def _read_surface_text(path: Path) -> str | None:
    """Decode a release-surface file, or return None if it cannot be read safely.

    Returning "" would treat an unreadable file as clean, which is a fail-open:
    a forbidden token would only have to sit in a file with one bad byte.

    Returning None instead of raising is deliberate. The caller records the file
    as a violation, which still fails closed at the assertion boundary but does
    not abort the scan - raising here would let one unreadable file mask every
    other finding, which is exactly the wrong property while a phase is deleting
    thousands of files.

    Only ASCII-compatible codecs are accepted. A codec that pairs bytes (utf-16,
    utf-32) splits ASCII tokens behind NULs and hides them from the scan, so it
    is refused unless a real BOM declares it.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        # Unreadable: permissions, a racing delete, or an I/O error. The
        # contract above is that a file which cannot be read safely is
        # reported, not that it aborts the scan.
        return None
    # Explicit BOMs are the only byte-pairing encodings we accept.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
    encoding = "utf-8"
    if path.suffix == ".py":
        # Honour a PEP 263 declared source encoding, but only when it is
        # ASCII-compatible.
        import codecs
        import tokenize

        try:
            with path.open("rb") as handle:
                encoding, _ = tokenize.detect_encoding(handle.readline)
            info = codecs.lookup(encoding)
            # CodecInfo.encode is the stateless encoder and returns
            # (bytes, length), NOT bytes. Unpack it. Comparing the tuple
            # against b"..." is True for every codec, including utf-8, which
            # would refuse every .py file in the tree.
            probe = "AZaz09/._"
            encoded, _ = info.encode(probe)
            transparent = (
                encoded == probe.encode("ascii")
                and probe.encode("ascii").decode(encoding) == probe
            )
        except (SyntaxError, TypeError, ValueError, UnicodeError, LookupError, OSError):
            # Several stdlib codecs (base64, hex, zlib, uu, quopri, bz2,
            # undefined and aliases) raise from encode(); refuse rather than
            # leaking their exception type. OSError covers a racing delete
            # between read_bytes and open.
            return None
        if not transparent:
            return None
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


def find_source_detachment_violations(root: Path) -> list[Violation]:
    """Return every forbidden Prime Agent execution edge under ``root``."""
    violations: list[Violation] = []
    for path in _iter_surface_files(root):
        text = _read_surface_text(path)
        rel = path.relative_to(root).as_posix()
        if text is None:
            violations.append(Violation(rel, 0, "undecodable-surface-file"))
            continue
        for number, body in enumerate(text.splitlines(), start=1):
            scrubbed = body
            for allowed in ALLOWED_ENV_VARS:
                scrubbed = scrubbed.replace(allowed, "")
            if any(token in scrubbed for token in FORBIDDEN_LOCATORS):
                violations.append(Violation(rel, number, "prime-source-locator"))
                continue
            if any(name in scrubbed for name in FORBIDDEN_ENV_VARS):
                violations.append(Violation(rel, number, "prime-source-locator"))
                continue
            if any(name in scrubbed for name in FORBIDDEN_IMPORTS):
                violations.append(Violation(rel, number, "legacy-prime-import"))
                continue
            if any(token in scrubbed for token in FORBIDDEN_SDK_TOKENS):
                violations.append(Violation(rel, number, "prime-sdk-edge"))
    return violations


def assert_asterion_prime_source_detached(root: Path) -> None:
    """Reject Prime Agent execution edges in any Asterion release surface."""
    violations = find_source_detachment_violations(root)
    if violations:
        shown = ", ".join(f"{v.path}:{v.line} ({v.rule})" for v in violations[:10])
        extra = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
        raise AssertionError(
            f"Asterion-prime source dependency is forbidden: {shown}{extra}"
        )
