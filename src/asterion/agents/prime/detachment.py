"""Release-surface regression guard for the Asterion Prime detachment phase.

Rejects Prime Agent checkout locators, source-root environment variables, and
Prime Agent execution edges in the surface this project ships.

What a green result means, stated precisely, because a trust-boundary component
must not overstate what it proves: no forbidden token appears as a contiguous
literal on one line, in a readable file with a scanned suffix under a scanned
root.

The walk is exhaustive only relative to a hand-maintained allowlist of roots,
suffixes and names, minus skipped directory names, minus symlinked directories,
minus case variants of those names, minus extensionless files. This is a
regression guard, not an adversarial control; a green run is not a security
guarantee.

Known, accepted evasions, kept beside that claim so the two are never read
apart: a token assembled at runtime ("prime" + "SourceRoot"), built through
importlib, formatted into an f-string, or split across lines is not detected.
Enforcement is the deletion work this gate schedules, not the matching here.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


SCAN_ROOTS = (
    "src/asterion",
    "packages/typescript",
    "tools",
    "tests",
    ".github",
    "Makefile",
    "pyproject.toml",
)

# Skipped by NAME at any depth: build inputs and caches, never release surface.
# This filter is applied BEFORE symlink detection, and the order is the
# semantics rather than an implementation detail: node_modules holds symlinked
# directories that are build input, so asking the symlink question first would
# record them and get the rule deleted by the next person.
SKIP_DIRS = frozenset({"node_modules", "dist", "build", "__pycache__", ".venv"})
# Compared case-insensitively: a Windows-authored .YML file is release surface.
SCAN_SUFFIXES = frozenset(
    {".py", ".ts", ".mjs", ".json", ".toml", ".mk", ".txt", ".yml", ".yaml"}
)
SCAN_NAMES = frozenset({"makefile", "gnumakefile"})


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

# A reference to the Prime Gateway package by path. The package is a removal
# target, so after it is gone a surviving reference is a dangling build input;
# the path itself is the finding even though it carries no execution edge.
FORBIDDEN_PACKAGE_PATHS = (_joined("packages/typescript/", "prime-gateway"),)

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


def _is_scanned_name(name: str) -> bool:
    """Case-insensitive suffix/name test for a candidate surface file."""
    return name.lower() in SCAN_NAMES or Path(name).suffix.lower() in SCAN_SUFFIXES


def _structural(root: Path, target: object, rule: str) -> Violation:
    """Build a line-0 violation for something the walk could not look inside."""
    path = Path(target)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    return Violation(rel, 0, rule)


def _walk_surface_root(root: Path, base: Path):
    """Yield scanned Paths under ``base``, plus a Violation per unusable
    directory and per entry that cannot be stat'd.

    ``os.walk`` replaces ``Path.rglob`` because rglob catches a permission error
    while descending and drops the whole subtree in silence: the scan finishes
    and reports nothing for a directory it never entered. ``onerror`` covers
    ``os.scandir`` failures only, so a failed ``stat`` on an individual entry is
    caught separately - a rule that guards half a failure mode reads as though
    the whole mode is covered.
    """
    pending: list[Violation] = []

    def on_error(exc: OSError) -> None:
        pending.append(
            _structural(
                root,
                getattr(exc, "filename", None) or base,
                "unreadable-surface-directory",
            )
        )

    for dirpath, dirnames, filenames in os.walk(
        base, followlinks=False, onerror=on_error
    ):
        yield from pending
        pending.clear()
        # 1. Skip build inputs first; 2. only then ask about symlinks.
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        survivors = []
        for name in dirnames:
            child = Path(dirpath) / name
            if os.path.islink(child):
                yield _structural(root, child, "symlinked-directory")
            else:
                survivors.append(name)
        dirnames[:] = survivors
        for name in filenames:
            if not _is_scanned_name(name):
                continue
            child = Path(dirpath) / name
            try:
                mode = child.stat().st_mode
            except OSError:
                yield _structural(root, child, "unreadable-surface-file")
                continue
            if not stat.S_ISREG(mode):
                continue
            yield child
    yield from pending


def _iter_surface_entries(root: Path):
    """Yield every scanned Path, interleaved with structural Violations.

    Entries are ``Path`` for files to scan and ``Violation`` for something the
    walk could not use. A ``SCAN_ROOT`` that does not exist is legitimately
    absent (a built-wheel-only surface has no packages/typescript); any other
    failure to reach it is a violation. Following ``followlinks=False`` means a
    symlinked directory is recorded rather than traversed, so a subtree cannot
    be hidden by a link and cannot be counted twice either.
    """
    for rel in SCAN_ROOTS:
        base = root / rel
        try:
            mode = base.stat().st_mode
        except FileNotFoundError:
            if os.path.islink(base):
                # A dangling symlinked root is undeclared indirection, not an
                # absent root.
                yield Violation(rel, 0, "symlinked-directory")
            continue
        except OSError:
            yield Violation(rel, 0, "unreadable-surface-directory")
            continue
        if stat.S_ISREG(mode):
            yield base
            continue
        yield from _walk_surface_root(root, base)


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
    for entry in _iter_surface_entries(root):
        if isinstance(entry, Violation):
            violations.append(entry)
            continue
        path = entry
        rel = path.relative_to(root).as_posix()
        text = _read_surface_text(path)
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
            if any(path_token in scrubbed for path_token in FORBIDDEN_PACKAGE_PATHS):
                violations.append(Violation(rel, number, "prime-gateway-reference"))
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
