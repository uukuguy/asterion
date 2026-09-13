# Asterion Prime P1-P7 Native Detachment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every legacy Prime Agent execution edge from the Asterion
distribution, and replace the narrow source-detachment gate with a semantic
release-surface gate that proves the removal is complete.

**Architecture:** The gate is written first and becomes the executable
definition of "removal complete". Legacy surfaces are then deleted until the
gate is green. This ordering means the plan never enumerates the removal in
prose — the gate's scan roots and forbidden-edge rules are the specification,
and the gate's own tests pin the semantics.

**Tech Stack:** Python 3.12+ (`unittest`), `uv`, hatchling, GNU Make,
TypeScript (npm workspaces), Rust (untouched by this phase).

**Spec:** `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`
**Decision:** `docs/status/DECISIONS.md` D-2026-09-12-01

---

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include
these.

- Formal P1-P7 paths must contain **none** of: a Prime checkout locator or
  source-root environment variable; imports or dynamic imports from Prime Agent
  packages or build output; Prime SDK session/daemon/child-agent/model-registry/
  settings/resource/auth/compaction/tool implementation; Prime Gateway bridges
  that execute an application through those internals; preparation or setup
  commands for Prime Agent; artifact or source locks whose subject is Prime
  Agent; package data or entry points for a Prime-backed provider/runtime; or
  tests that require a Prime checkout to pass.
- **The rule is semantic, not string-specific.** Renaming or relocating a
  checkout does not make it an allowed dependency.
- The distributed application provider is `prime-applications`. The formal agent
  runtime is `asterion.prime`.
- Legacy release surfaces are **removed rather than retained as fallbacks**.
  Missing native capability returns an explicit unavailable result and never
  falls back to Prime Agent.
- Before an application is migrated, its selector is **omitted** from
  `prime-applications` and from `asterion.application_index`, so metadata lookup
  rejects it before importing a runtime or starting a process. No executable
  unavailable stub is added.
- Prime Agent may exist only outside the trust boundary as a black-box
  historical baseline. A neutral comparison tool may read an **exported log**;
  it may not accept a Prime checkout locator or start a Prime process.
- Public output must not include prompts, model prose, generated code, worker
  output, credentials, provider bodies, private paths, source locations, or raw
  external logs.
- `3th-party/prime-agent.git` is strictly off-limits: never read, listed,
  launched, locked, or retargeted through configuration. `../external-prime/` is
  a separate external resource and is **not** covered by that prohibition.
- **Verification is research-weight.** This is research development, not a
  production release exercise. Do not revive the multi-thousand-test promotion
  suite as a P1-P7 gate.

---

## Program roadmap

Nine phases, in the spec's mandated order. Phase 1 is detailed in this plan.
Phases 3-9 receive their own plans when reached — each is an independently
testable deliverable and must not be pre-choreographed here.

| # | Phase | Depends on | Acceptance (spec-derived) | Plan |
|---|---|---|---|---|
| 1 | Legacy release-surface removal + expanded detachment gate | — | Gate scans the complete release surface and fails on representative forbidden references; no legacy execution edge remains | **this plan** |
| 2 | Conversion of research presets to installed-wheel invocation | 1 | `asterion-prime-p7-solve` runs from a wheel, no `PYTHONPATH=<src>` | pending |
| 3 | P7 native revalidation (anchor) | 2 | Expanded detachment + wheel + installed-route + focused native regression pass with no Prime checkout | pending |
| 4 | P1 rebuild (`prime.ipython-coding`) | 3 | Spec P1 witness: two model-driven cells share one restricted worker; stage-one file bytes survive Asterion-owned compaction and host reconstruction; oracle passes; cleanup precedes public terminal | pending |
| 5 | P2 rebuild (`prime.programmatic-long-context`) | 4 | Source material stays outside the prompt; ≥1 bounded programmatic retrieval/transform through an injected service; answer oracle passes within caps | pending |
| 6 | P4 rebuild (`prime.long-session-continuity`) | 5 | Committed checkpoint detached, controlling process replaced, new host attaches at higher generation, continuation completes without replaying a committed effect | pending |
| 7 | P3 rebuild (`prime.recursive-workflow`) | 6 | One root run starts an admitted child via `prime.child-runner`; child result joined; depth/concurrency/budget limits reject further spawning | pending |
| 8 | P5 rebuild (`prime.bounded-autonomy`) | 7 | Finite propose/verify/repair with ≥1 failed verification and ≥1 bounded repair; stops on success or exact cap; no autonomous continuation | pending |
| 9 | P6 rebuild (`prime.continual-improvement`) | 8 | Candidate evaluated against fixed baseline; non-improving rejected without promotion; improving requires explicit admitted promotion | pending |

P7 is the implementation anchor. Its application logic is **not** rewritten —
only revalidated after the legacy release surfaces are gone. P1-P6 are rebuilt
on the shared substrate; they do not create a parallel agent/runtime.

Shared-substrate changes run only the relevant application witness plus the P7
provider-free native anchor. They do not trigger every live preset.

---

## Phase 1: Legacy release-surface removal + detachment gate

### Verified starting inventory (evidence-backed, 2026-09-13)

Recorded so the implementer does not re-derive it. Line numbers are pre-change.

**`pyproject.toml`**
- `:24-25` `[project.scripts]` — both KEEP.
- `:30` `asterion.applications` → `prime-applications` KEEP; `:31` `prime-agent` **REMOVE**.
- `:33-46` `asterion.application_index`, 13 rows. **REMOVE 8**: `:38` `prime.capability-program`, `:39` `prime.arc-agi-3`, `:41` `prime.bounded-autonomy`, `:42` `prime.continual-improvement`, `:44` `prime.programmatic-long-context`, `:45` `prime.recursive-workflow`, `:46` `prime.long-session-continuity` — all → `prime_agent.provider`. **REMOVE 1 more**: `:43` `prime.ipython-coding__1.0.0` → `asterion.applications.prime` — its assembly requires five host services (`prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend`) that have **no entry point**; only the forbidden legacy `prime.ipython-production` supplies P1 today. **KEEP**: `:40` `prime.arc-agi-3-solving__1.0.0` (native P7) and the four `code.quality`/`dci.*` rows.
- `:48-58` `asterion.host_services`. **REMOVE 8**: `:51` `model.bounded-session`, `:52` `prime.ipython-production`, `:53-58` the six `prime.*-development` rows. **KEEP** `:49-50`.
- `:16` optional-dependency extra `prime` — consumed only by the legacy Make targets; becomes dead. Confirm no other consumer before removing.
- `:62-74` wheel `artifacts` — **REMOVE** `:65-66` (`applications/prime_agent/operator/resources/*.json|*.txt`), `:71-73` (`control/providers/prime/resources/control-plane.json` + `skills/asterion-control/**`). **KEEP** `:63-64` (native prime + p7 run_story), `:67-68` (dci pi), `:69-70` (native/asterion_prime control-plane).
- `:78-90` wheel `force-include` — **REMOVE all of `:79-90`**. `:81-90` are `prime-gateway/resources/*` → `control/providers/prime/resources/*`, including `:90` which ships a **test fixture** into the wheel. `:79-80` (`pi-compaction-lock.json`, `pi-compaction-verifier.mjs`) were initially marked KEEP as native but are a **Prime Agent checkout lock** — see Task 3 Step 2 for the evidence.
- `:91+` schema force-includes — see Task 9 (audit-gated).

**`Makefile`**
- **REMOVE variables** `:5` `ASTERION_PRIME_SOURCE_ROOT ?= 3th-party/prime-agent`, `:6` `ASTERION_PRIME_AUTHORITY`, `:7` `ASTERION_PRIME_MAX_COST_MICROS`.
- **KEEP variables** `:8` `ASTERION_PRIME_NODE` (npm-resolved node 22 executable path — not a Prime locator), `:9` `ASTERION_PROMOTION_NPM_CACHE`, `:10` `PRIME_ORB_MACHINE`, `:2` `ASTERION_PROVIDER`.
- **REMOVE targets** `:200-201` `prime-check`, `:203-204` `prime-setup`, `:209-219` `prime-p1-run`, `:221-231` `prime-p2-run`, `:233-243` `prime-p3-run`, `:245-255` `prime-p4-run`, `:257-267` `prime-p5-run`, `:269-279` `prime-p6-run`, `:281-291` `prime-p7-run`, `:304-305` `prime-apps-preflight`, `:497-498` `prime-verify-bounded`, `:500-501` `prime-verify-native-rlm-bounded`, `:336-337` `test.prime-long-running.bounded`, `:346-350` `test.prime-continual-harness.bounded` (note `:349` hardcodes `3th-party/prime-agent`, bypassing the variable).
- **`promotion-check` `:115-116`** currently forwards `ASTERION_PRIME_SOURCE_ROOT` into `tools/check_promotion.py` — it is the only KEEP target that must have the variable stripped from its recipe.
- **`help` `:48-68`** advertises 9 REMOVE targets at `:62-66`.
- **Breakage** (KEEP targets whose recipes die when REMOVE artifacts go): `:113` `check` → `:186-191` `test-typescript` → prime-gateway build; `:307-314`, `:320-323`, `:327-332`, `:339-344`, `:358-360`, `:362-367`, `:369-373`, `:405-410`, `:412-418`, `:420-425`, `:427-432`, `:434-439`, `:441-447`, `:449-455`, `:396-403`, `:457-464` (all invoke `prime-gateway test` or `--provider asterion.prime-gateway`); `:509-510` `prime-parity-inventory`, `:512-513` `prime-verify-system-parity`.
- **Python-only, survive cleanly**: `:352-356`, `:375-378`, `:380-383`, `:385-389`, `:391-394`.
- **Presets**: `:293-295` `asterion-prime-p7-solve` uses `export PYTHONPATH="$(CURDIR)/src"` + `../external-prime/arc-agi-3/venv/bin/python tools/run_asterion_prime_p7.py` → **source-tree invocation, must convert** (Task 2 of the program roadmap). `:297-302` `asterion-prime-p1-run` is already an installed-wheel invocation (`uv build --wheel` → `uv run --isolated --with <wheel>`), and `src/asterion/applications/prime/p1/operator.py:987-991` already refuses source execution of the *asterion* package.

**Native P1 operator (`src/asterion/applications/prime/p1/operator.py`)** — the
split-brain that motivates the gate. It runs installed-wheel, yet reaches into
Prime source at runtime:
- `:918` field `source_root: Path`
- `:934-935` dynamic `import(pathToFileURL(root + '/packages/coding-agent/dist/config.js'))` and `.../core/compaction/compaction.js`
- `:963` launches `<source>/packages/coding-agent/dist/main.js`
- `:1019` defaults `ASTERION_PRIME_SOURCE_ROOT` to `root / "3th-party/prime-agent"`
- `:1035` locks `package_resources.files("asterion.control.providers.prime")`
- `:1154` threads `source_root` downstream

**Existing gate (`src/asterion/agents/prime/detachment.py`)** scans only
`src/asterion/agents/prime/` and `src/asterion/runtimes/asterion_prime.py`
against 5 literal tokens. It is green today **while `applications/prime/p1/operator.py`
carries six forbidden edges** — this is the coverage gap Phase 1 closes.

**Test suite** — 428 modules; ~180 reference a legacy surface
(`asterion.applications.prime_agent`, `asterion.capabilities.prime_agent`,
`asterion.runtimes.prime_agent`, `asterion.control.providers.prime`, the
`prime-agent`/`prime.agent` selector, or a `3th-party/prime-agent` default).
`tests/fixtures/` trees `prime_gateway/` and `prime-parity/` are legacy-coupled;
`asterion_prime/`, `asterion_prime_p1/`, `operation/`, `session_context/`,
`agent_client/` need the Task 9 audit.

**Baseline before Phase 1:** `make docs-check` PASS (207 markdown files, 57
local links). Working tree clean; `main == origin/main == f1d28b9e`.

---

### Task 1: Expand the detachment gate into a semantic release-surface scanner

**Files:**
- Modify: `src/asterion/agents/prime/detachment.py`
- Create: `tests/test_prime_source_detachment.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `assert_asterion_prime_source_detached(root: Path) -> None` — raises
  `AssertionError` with a message naming the offending `path:line` and the rule
  that fired. Also `find_source_detachment_violations(root: Path) -> list[Violation]`
  where `Violation` is a frozen dataclass with fields `path: str`, `line: int`,
  `rule: str`. Later tasks and the Make target call these.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prime_source_detachment.py
"""Boundary tests for the semantic source-detachment gate.

Every forbidden token below is assembled from parts. The gate scans this file
too, so a literal token here would make the gate flag its own test suite.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.agents.prime.detachment import (
    find_source_detachment_violations,
)


def _t(*parts: str) -> str:
    """Assemble a forbidden token without writing it literally."""
    return "".join(parts)


CHECKOUT = _t("3th-party/", "prime-agent")
CODING_AGENT_DIST = _t("packages/", "coding-agent/dist")
LEGACY_PROVIDER = _t("asterion.applications.", "prime_agent")
SOURCE_ROOT_ENV = _t("ASTERION_PRIME_", "SOURCE_ROOT")


class TestDetachmentGate(unittest.TestCase):
    def _scan(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, body in files.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
            return [v.rule for v in find_source_detachment_violations(root)]

    def test_flags_prime_checkout_locator(self) -> None:
        rules = self._scan(
            {"src/asterion/applications/prime/p1/operator.py": f'PRIME = "{CHECKOUT}"\n'}
        )
        self.assertIn("prime-source-locator", rules)

    def test_flags_source_root_environment_variable(self) -> None:
        rules = self._scan(
            {"src/asterion/x.py": f'root = environment["{SOURCE_ROOT_ENV}"]\n'}
        )
        self.assertIn("prime-source-locator", rules)

    def test_flags_legacy_package_import(self) -> None:
        rules = self._scan({"src/asterion/x.py": f"from {LEGACY_PROVIDER} import provider\n"})
        self.assertIn("legacy-prime-import", rules)

    def test_flags_prime_coding_agent_launch(self) -> None:
        rules = self._scan(
            {"src/asterion/x.py": f'MAIN = root + "/{CODING_AGENT_DIST}/main.js"\n'}
        )
        self.assertIn("prime-source-locator", rules)

    def test_allows_asterion_owned_operator_root(self) -> None:
        # ASTERION_PRIME_OPERATOR_ROOT resolves to the Asterion repo/install
        # root and ASTERION_PRIME_NODE to a node executable path. Neither is a
        # Prime checkout, so a substring rule would false-positive here.
        rules = self._scan(
            {
                "src/asterion/applications/prime/p1/operator.py": (
                    'root = Path(environment["ASTERION_PRIME_OPERATOR_ROOT"])\n'
                    'node = Path(environment["ASTERION_PRIME_NODE"])\n'
                )
            }
        )
        self.assertEqual(rules, [])

    def test_flags_makefile_source_root_variable(self) -> None:
        rules = self._scan({"Makefile": f"{SOURCE_ROOT_ENV} ?= {CHECKOUT}\n"})
        self.assertIn("prime-source-locator", rules)

    def test_flags_pyproject_legacy_entry_point(self) -> None:
        rules = self._scan(
            {
                "pyproject.toml": (
                    f'"prime-agent" = "{LEGACY_PROVIDER}.provider:create_provider"\n'
                )
            }
        )
        self.assertIn("legacy-prime-import", rules)

    def test_flags_prime_sdk_identifiers(self) -> None:
        # The gate this one replaces enforced these three tokens. Dropping any
        # of them is a coverage regression: the Prime SDK session factory and
        # loader are precisely the "Prime SDK session" execution edge the
        # design forbids, and the camel-case source-root getter is a checkout
        # locator under another name. Never spell them literally here.
        for token in (
            _t("createAgent", "Session"),
            _t("loadPrime", "Sdk"),
            _t("prime", "SourceRoot"),
        ):
            with self.subTest(token=token):
                rules = self._scan({"src/asterion/x.py": f"await {token}\n"})
                self.assertIn("prime-sdk-edge", rules)

    def test_undecodable_file_fails_closed(self) -> None:
        # Returning "" for an undecodable file would treat it as clean. A
        # trust-boundary gate must fail closed instead.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src/asterion/x.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\xff\xff\xff")
            with self.assertRaises(AssertionError):
                find_source_detachment_violations(root)

    def test_scan_is_not_silenced_by_an_ancestor_directory_name(self) -> None:
        # A checkout under a directory named build/ must still be scanned.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "build" / "asterion"
            target = root / "src/asterion/x.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f'BAD = "{CHECKOUT}"\n', encoding="utf-8")
            rules = [v.rule for v in find_source_detachment_violations(root)]
            self.assertIn("prime-source-locator", rules)

    def test_reports_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src/asterion/x.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"ok = 1\nBAD = '{CHECKOUT}'\n", encoding="utf-8")
            violations = find_source_detachment_violations(root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].line, 2)


if __name__ == "__main__":
    unittest.main()
```

> Every test here scans a temporary tree, so all 8 pass on the unmodified
> repository. The real-tree assertion lives in Task 2.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest -v tests.test_prime_source_detachment`
Expected: FAIL — `ImportError: cannot import name 'find_source_detachment_violations'`.

- [ ] **Step 3: Write the implementation**

```python
# src/asterion/agents/prime/detachment.py
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
# replaces; dropping them would be a coverage regression, because the Prime
# SDK session factory and SDK loader are exactly the "Prime SDK session"
# execution edge the design forbids.
#
# NOTE: comments are scanned too. Never spell these tokens literally anywhere
# in this module or its test - a literal in a comment makes the gate flag its
# own source, and Task 2's self-consistency test can then never pass.
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
            # Skip decisions must use the path RELATIVE to root. Using
            # absolute parts means a repository checked out under a directory
            # named build/, dist/ or .venv/ silences the entire scan.
            if SKIP_DIRS.intersection(child.relative_to(root).parts):
                continue
            if child.suffix in SCAN_SUFFIXES or child.name in SCAN_NAMES:
                yield child


def _read_surface_text(path: Path) -> str:
    """Decode a release-surface file, failing closed on ambiguity.

    Returning "" for an undecodable file would treat it as clean, which is a
    fail-open in a trust-boundary gate: a forbidden token would only have to be
    placed in a file with one bad byte.

    Do NOT fall back to UTF-16 unless a BOM actually declares it. Decoding a
    non-UTF-16 file as UTF-16 pairs the bytes, so ASCII tokens are split by NULs
    and evade the scan - the same fail-open in a different disguise.
    """
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise AssertionError(f"undecodable release-surface file: {path}") from exc
    encoding = "utf-8"
    if path.suffix == ".py":
        # Honour a PEP 263 declared source encoding.
        import tokenize

        try:
            with path.open("rb") as handle:
                encoding, _ = tokenize.detect_encoding(handle.readline)
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AssertionError(f"undecodable release-surface file: {path}") from exc
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise AssertionError(f"undecodable release-surface file: {path}") from exc


def find_source_detachment_violations(root: Path) -> list[Violation]:
    """Return every forbidden Prime Agent execution edge under ``root``."""
    violations: list[Violation] = []
    for path in _iter_surface_files(root):
        lines = _read_surface_text(path).splitlines()
        rel = path.relative_to(root).as_posix()
        for number, body in enumerate(lines, start=1):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest -v tests.test_prime_source_detachment`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/agents/prime/detachment.py tests/test_prime_source_detachment.py
git commit -m "feat(prime): replace literal detachment check with semantic release-surface gate"
```

---

### Gate limitations — deliberate, and to be stated rather than implied

The gate is a release-surface scanner, not a proof of detachment. Its known
limits, recorded so later phases do not mistake a green gate for a stronger
claim than it is:

1. **Line-local, literal matching.** A forbidden token assembled at runtime
   (the same `_joined` technique the gate itself uses) is invisible. The gate
   catches spelled-out references only; actual enforcement is the removal work
   in Tasks 3-9.
2. **`SCAN_ROOTS` is an allowlist.** `docs/`, `scripts/`, `schemas/`, and
   top-level `*.py` are not scanned, so a checkout path written into a plan or
   guide passes untouched. This is intentional — `docs/` is history and is not
   shipped in the wheel — but it means the gate does not cover the docs corpus.
   If a future phase ships docs, add them to `SCAN_ROOTS`.
3. **`ALLOWED_ENV_VARS` scrubbing can manufacture a false positive.** The
   scrub runs before matching, so a line containing an allowed name spliced
   into a forbidden one could be reported. Contrived, but if it fires, fix the
   scrub rather than deleting the rule.
4. **No line-continuation awareness.** A token split across two source lines is
   invisible. Accepted; Python and TypeScript both permit it, but the removal
   tasks verify by deletion, not by scan.
5. **The scan skips `node_modules`/`dist`/`build`.** Task 9 Step 3b closes the
   shipping half of this by scanning the built wheel with the same rule set.

### Task 2: Establish the red baseline on the real tree

**Files:**
- Test: `tests/test_prime_source_detachment_real_tree.py`

**Interfaces:**
- Consumes: `assert_asterion_prime_source_detached` and
  `find_source_detachment_violations` from Task 1.
- Produces: nothing. This task exists to prove the gate detects the known
  violations, so Task 5's green run is meaningful rather than vacuous.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prime_source_detachment_real_tree.py
"""Proves the gate fails on the real tree until Phase 1 removal completes."""

from __future__ import annotations

import unittest
from pathlib import Path

from asterion.agents.prime.detachment import (
    assert_asterion_prime_source_detached,
    find_source_detachment_violations,
)

ROOT = Path(__file__).resolve().parent.parent


class TestRealTreeDetachment(unittest.TestCase):
    def test_release_surface_is_source_detached(self) -> None:
        assert_asterion_prime_source_detached(ROOT)

    def test_gate_does_not_flag_its_own_source(self) -> None:
        # The gate module and this test both live under a scanned root. If the
        # gate's own literals are not assembled from parts, it flags itself and
        # can never pass.
        rules = [v.rule for v in find_source_detachment_violations(ROOT)]
        self.assertEqual(rules, [])

    def test_gate_detects_the_known_p1_operator_edges(self) -> None:
        paths = {v.path for v in find_source_detachment_violations(ROOT)}
        self.assertIn("src/asterion/applications/prime/p1/operator.py", paths)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and record the red baseline**

Run: `uv run python -m unittest -v tests.test_prime_source_detachment_real_tree`
Expected: FAIL on `test_release_surface_is_source_detached`,
`test_gate_does_not_flag_its_own_source`, and
`test_gate_detects_the_known_p1_operator_edges` — the last of these is the
meaningful one. If `test_gate_detects_the_known_p1_operator_edges` does **not**
fail, the gate has a coverage hole: fix Task 1 before continuing. Do not proceed
on a gate that misses the documented P1 edges.

All three are expected red here: the release surface still carries legacy edges,
and the legacy test modules that assert them are still present. They turn green
at Task 11 Step 3.

- [ ] **Step 3: Commit the red test**

```bash
git add tests/test_prime_source_detachment_real_tree.py
git commit -m "test(prime): assert release surface is source-detached (red baseline)"
```

---

### Task 3: Remove the legacy packaging surface

**Files:**
- Modify: `pyproject.toml` (lines listed in the verified inventory)

**Interfaces:**
- Consumes: nothing.
- Produces: the `prime-agent` provider, the eight legacy `application_index`
  rows, the `prime.ipython-coding__1.0.0` row, and the eight legacy
  `host_services` rows are gone. Task 9's gates depend on this.

- [ ] **Step 1: Delete the legacy entry points**

Remove from `pyproject.toml`:
- the `"prime-agent"` key under `[project.entry-points."asterion.applications"]`;
- under `[project.entry-points."asterion.application_index"]`:
  `prime.capability-program__1.0.0`, `prime.arc-agi-3__1.0.0`,
  `prime.bounded-autonomy__1.0.0`, `prime.continual-improvement__1.0.0`,
  `prime.ipython-coding__1.0.0`, `prime.programmatic-long-context__1.0.0`,
  `prime.recursive-workflow__1.0.0`, `prime.long-session-continuity__1.0.0`;
- under `[project.entry-points."asterion.host_services"]`:
  `model.bounded-session`, `prime.ipython-production`, and the six
  `prime.*-development` rows.

Do **not** touch `prime-applications`, `prime.arc-agi-3-solving__1.0.0`,
`corpus.local-root`, `evaluation.answer-judge`, or the `dci.*` / `code.quality`
rows.

- [ ] **Step 1b: Read the rest of the packaging block before editing**

Beyond the ranges already listed, `pyproject.toml` carries:
- `:91-108` schema force-includes — audited in Task 9, **not** deleted here;
- `:110-115` `[tool.hatch.build.targets.sdist] artifacts` —
  `.asterion-prime-extension-build.json`,
  `src/asterion/applications/prime/resources/ipython-extension.mjs`,
  `src/asterion/applications/prime/p7/run_story/assets/*`. All three are
  **native; KEEP**. Do not delete the sdist block.

- [ ] **Step 2: Delete the legacy wheel content mappings**

- from `[tool.hatch.build.targets.wheel] artifacts`: the two
  `applications/prime_agent/operator/resources/*` entries and the three
  `control/providers/prime/resources/...` entries;
- from `[tool.hatch.build.targets.wheel.force-include]`: the nine
  `packages/typescript/prime-gateway/resources/...` entries, the
  `tests/fixtures/prime_gateway/v1/real-prime-operations.mjs` entry, **and the
  two compaction entries at `:79-80`**.

**Correcting an earlier misclassification.** `:79-80` were initially marked
KEEP because their filenames say "asterion"/"pi". They are a Prime Agent source
lock. Evidence:

- `packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json`
  is 394 KB / 2891 file digests with `format: asterion.pi-compaction-lock/v1`,
  `package_name: @earendil-works/pi-coding-agent`, `package_version: 0.7.1`,
  `source_commit: a18809e00ea30638584d87b3afea7285a9d7296c`, and `entry_points`
  under `packages/coding-agent/dist/*`.
- `CURRENT-STATE.md` calls that same commit "the pinned Prime source".
- `docs/superpowers/plans/2026-09-10-asterion-prime-native-p1-shared-kernel.md:48`
  resolves `@earendil-works/pi-coding-agent@0.7.1` **beneath
  `ASTERION_PRIME_SOURCE_ROOT`**.
- `tools/check_promotion.py:963-966` maps `pi-coding-agent`, `pi-ai`,
  `pi-agent-core`, `pi-tui` to `external_prime_root/packages/*`.
- `docs/superpowers/specs/2026-08-10-asterion-prime-gateway-daemon-delta.md:62`
  records `npm view @earendil-works/pi-coding-agent@0.7.1` → `E404`: the package
  is not published, so the checkout is its only source.

The detachment spec anticipates exactly this relabeling: "A Prime Agent checkout
is not the Pi runtime and cannot be reintroduced under a Pi label."

Keep the `dci` / `native` / `asterion_prime` control-plane entries.

- [ ] **Step 3: Verify the metadata is still coherent**

Run: `uv run python -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); eps=d['project']['entry-points']; print({k: len(v) for k, v in eps.items()})"`
Expected: `asterion.applications` has 3 keys; `asterion.application_index` has
5; `asterion.host_services` has 2.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "refactor(prime): remove legacy Prime Agent packaging surface"
```

---

### Task 4: Remove the legacy Make surface

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: nothing.
- Produces: no Make target locates or propagates a Prime source root. Task 9
  depends on this.

- [ ] **Step 1: Delete the variables and targets**

Delete variables `ASTERION_PRIME_SOURCE_ROOT`, `ASTERION_PRIME_AUTHORITY`,
`ASTERION_PRIME_MAX_COST_MICROS`; and targets `prime-check`, `prime-setup`,
`prime-p1-run` … `prime-p7-run`, `prime-apps-preflight`, `prime-verify-bounded`,
`prime-verify-native-rlm-bounded`, `test.prime-long-running.bounded`,
`test.prime-continual-harness.bounded`.

Keep `ASTERION_PRIME_NODE`, `ASTERION_PROMOTION_NPM_CACHE`, `PRIME_ORB_MACHINE`,
`ASTERION_PROVIDER`.

- [ ] **Step 2: Strip the variable from the surviving recipe**

In the `promotion-check` recipe (`:115-116`), remove the
`ASTERION_PRIME_SOURCE_ROOT="$(ASTERION_PRIME_SOURCE_ROOT)"` prefix so it no
longer forwards a source root.

- [ ] **Step 3: Update `.PHONY` and `help`**

Remove the deleted target names from the `.PHONY` lines (`:27-32`) and from the
`help` text (`:62-66`). `make help` must not advertise a target that no longer
exists.

- [ ] **Step 4: Verify no dangling references**

Run: `grep -nE 'ASTERION_PRIME_SOURCE_ROOT|ASTERION_PRIME_AUTHORITY|ASTERION_PRIME_MAX_COST_MICROS|prime-p[1-7]-run|prime-apps-preflight|prime-check|prime-setup' Makefile`
Expected: no output.

Run: `make help`
Expected: exits 0, lists no `prime-pN-run` / `prime-check` / `prime-setup`.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "refactor(prime): remove legacy Prime Agent make surface"
```

---

### Task 5: Excise the Prime execution edges from the native P1 operator

**Files:**
- Modify: `src/asterion/applications/prime/p1/operator.py:918,934-935,963,1019,1035,1154`

**Interfaces:**
- Consumes: nothing.
- Produces: `applications/prime/p1/operator.py` no longer resolves a Prime
  source root, imports Prime build output, launches Prime's coding agent, or
  locks a Prime Gateway artifact. Task 2's test turns green for this file.

- [ ] **Step 1: Remove the source-root field and its threading**

Delete the `source_root: Path` field at `:918` and its use at `:1154`. Delete
the `ASTERION_PRIME_SOURCE_ROOT` default at `:1019`.

- [ ] **Step 2: Remove the Prime dynamic imports and launch**

Delete the dynamic imports at `:934-935` (`coding-agent/dist/config.js`,
`core/compaction/compaction.js`) and the `main.js` launch at `:963`. Session
compaction semantics come from the Asterion-owned compaction verifier already
shipped as `applications/prime/resources/pi-compaction-verifier.mjs`
(`pyproject.toml:80`) — do **not** substitute a Prime internal module.

- [ ] **Step 3: Remove the Prime Gateway artifact lock**

Delete the `package_resources.files("asterion.control.providers.prime")` lock at
`:1035`, and the compaction-lock resolution that feeds the `:934-935` imports —
the shipped `asterion/applications/prime/resources/pi-compaction-lock.json` is a
Prime checkout lock (see Task 3), so the operator must not resolve or verify it.

> **This is the compaction-detachment step the spec requires.** The spec states
> "No Prime internal module may supply compaction semantics" and lists "Prime
> compaction imports" for removal. Both the import (`:934-935`) and the lock it
> verifies must go together: removing one without the other leaves a verifier
> checking a lock no longer produced, or an import with nothing to validate.

Compaction semantics for the rebuilt P1 come from an Asterion-owned
implementation. Phase 4 owns building it; Phase 1 only removes the Prime
dependency and leaves P1 unavailable, which is the spec's required intermediate
state.

- [ ] **Step 4: Verify the file is clean and the package still imports**

Run: `grep -nE 'source_root|SOURCE_ROOT|coding-agent/dist|control\.providers\.prime|3th-party' src/asterion/applications/prime/p1/operator.py`
Expected: no output.

Run: `uv run python -c "import asterion.applications.prime.p1.operator"`
Expected: exits 0.

Run: `uv run python -m unittest -v tests.test_asterion_prime_p1_operator`
Expected: the tests that asserted Prime-source behavior now fail. **Rewrite or
delete those specific tests** in this task — an assertion that the operator
resolves a Prime checkout is itself a forbidden edge. Commit the test change
with the implementation.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p1/operator.py tests/test_asterion_prime_p1_operator.py
git commit -m "refactor(prime): remove Prime source execution from native P1 operator"
```

---

### Task 6: Remove the legacy Python packages

**Files:**
- Delete: `src/asterion/applications/prime_agent/`,
  `src/asterion/capabilities/prime_agent/`, `src/asterion/runtimes/prime_agent.py`,
  `src/asterion/runtimes/prime_agent_host.py`,
  `src/asterion/control/providers/prime/`
- Modify: `src/asterion/applications/first_party_packages.py`,
  `tests/core_module_allowlist.py`

**Interfaces:**
- Consumes: Tasks 3-5 (nothing may still reference these).
- Produces: no importable legacy Prime execution edge.

- [ ] **Step 1: Confirm nothing outside the deletion set still imports them**

Run: `grep -rn -E 'asterion\.(applications\.prime_agent|capabilities\.prime_agent|runtimes\.prime_agent|control\.providers\.prime)' src/ tools/ --include='*.py' 2>/dev/null | grep -vE 'src/asterion/(applications/prime_agent|capabilities/prime_agent|runtimes/prime_agent|control/providers/prime)'`
Expected: no output. Any hit must be resolved before deleting.

- [ ] **Step 2: Remove the first-party registration — precisely**

In `src/asterion/applications/first_party_packages.py` delete only:
`:21` `PRIME_AGENT_PACKAGE = CapabilityPackageRef("prime-agent", "1.0.0")`,
the registration tuple entry at `:43-47`, the factory
`create_prime_agent_package()` at `:99-104`, and the two `__all__` names at
`:131` and `:137`.

**Preserve** `CONTROLLED_CODE_PACKAGE` (`:18`, `:33-37`, factory `:61-88`),
`DCI_PACKAGE` (`:20`, `:38-42`, factory `:91-96`),
`builtin_capability_registrations()` itself (`:28`), **and critically**
`PRIME_ARC_AGI_3_SOLVER_PACKAGE` (`:22`) and
`PRIME_IPYTHON_CODING_NATIVE_PACKAGE` (`:23-25`) — those two bind *native*
payloads (`capabilities/prime_arc_agi_3_solver`,
`capabilities/prime_ipython_coding_native`) whose assemblies set
`runtime_id: asterion.prime`. They are not Prime Agent execution edges. Verify
each of the two has `runtime_id: asterion.prime` in its assembly before leaving
it in place.

- [ ] **Step 3: Drop the modules from the core allowlist**

`tests/core_module_allowlist.py:172-183` lists nine legacy prefixes
(`applications.prime_agent`, `capabilities.prime_agent`,
`control.providers.prime`, `runtimes.prime_agent`, `runtimes.prime_agent_host`,
and others) consumed only by `tests/test_core_only_install.py:14-15`.

Remove the legacy prefixes in the same commit, or the core-only import gate
fails on a module that no longer exists. **Do not delete the file, and do not
drop** `capabilities.prime_arc_agi_3_solver` or
`capabilities.prime_ipython_coding_native` — those name retained native
packages (design's exact native application map). The edit is "drop legacy
prefixes, keep native ones", not "delete the list".

- [ ] **Step 4: Delete the trees**

```bash
git rm -r src/asterion/applications/prime_agent src/asterion/capabilities/prime_agent src/asterion/control/providers/prime
git rm src/asterion/runtimes/prime_agent.py src/asterion/runtimes/prime_agent_host.py
```

> `prime_agent_host.py` is removable because **every** consumer of its seam
> names (`PrimeSmallVerification*`, `PrimePresetExecution*`,
> `PrimeP7DevelopmentHostService`) is either legacy source
> (`applications/prime_agent/runtime_binding.py`, `operator/p1..p7_cli_host.py`)
> or a legacy test (`test_prime_p*_cli_host.py`,
> `test_prime_p*_installed_route.py`, `test_prime_package_runtime_closure.py`,
> `test_prime_preset_runtime.py`). No native module under
> `applications/prime/` or `agents/prime/` references them. Re-verify with
> `grep -rn 'PrimeSmallVerification\|PrimePresetExecution\|PrimeP7DevelopmentHostService' src/asterion tools/ --include='*.py'`
> before deleting; if a native hit appears, keep the module and report it.

- [ ] **Step 5: Verify the framework still imports**

Run: `uv run python -c "import asterion; import asterion.applications.prime; import asterion.runtimes.asterion_prime"`
Expected: exits 0.

Run: `uv run python -m unittest -v tests.test_project_boundary tests.test_default_runtime_factory`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A src/asterion tests/core_module_allowlist.py
git commit -m "refactor(prime): delete legacy Prime Agent provider, runtime, capability and control packages"
```

---

### Task 7: Remove the Prime Gateway TypeScript surface

**Files:**
- Delete: `packages/typescript/prime-gateway/`
- Delete: `packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json`
  and `packages/typescript/asterion-prime-extension/test/context-witness-harness.mjs`
- Modify: any workspace manifest that lists them.

**Interfaces:**
- Consumes: Task 3 (force-includes already removed).
- Produces: `make test-typescript` builds only surviving packages, and no
  surviving TypeScript package carries a Prime checkout reference.

> `asterion-prime-extension/src/*` (`context-projection.ts`, `context-witness.ts`,
> `context-counter.ts`, `ipython-extension.ts`) is Asterion-owned and is **not**
> in scope here — only its Prime-checkout lock resource and the harness that
> imports `packages/coding-agent/dist/core/*` are. Confirm with the gate after
> the deletion: `packages/typescript/asterion-prime-extension` must drop from
> 262 violations to 0.

- [ ] **Step 1: Confirm the consumer set**

Run: `grep -rn 'prime-gateway' --include='package.json' --include='*.mk' --include='Makefile' --include='*.toml' . 2>/dev/null | grep -v node_modules | grep -v '^./3th-party'`
Expected: only `Makefile` targets already slated for rework (Task 9) and
possibly a workspace manifest line.

- [ ] **Step 2: Delete the package and de-list it**

```bash
git rm -r packages/typescript/prime-gateway
```

There is **no npm workspace list** — this repo declares no `workspaces` in any
`package.json`; each package is built standalone via `--prefix`. Nothing to
prune.

`packages/typescript/asterion-runtime/` and `packages/typescript/dci-context-extension/`
survive and are depended on by surviving Make targets (`asterion-runtime` at
`:96-97`, `:187-188`, `:313`; `dci-context-extension` at `:189`). Do not remove
them.

- [ ] **Step 3: Verify the surviving TypeScript still builds**

Run: `npm ci --prefix packages/typescript && npm run build --prefix packages/typescript/asterion-prime-extension`
Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add -A packages/typescript package.json
git commit -m "refactor(prime): remove Prime Gateway TypeScript execution surface"
```

---

### Task 8: Remove or rewrite the coupled tests and fixtures

**Files:**
- Delete / rewrite: the ~180 modules and the `tests/fixtures/prime_gateway/`,
  `tests/fixtures/prime-parity/` trees identified in the verified inventory.
- Modify: `tests/prime_release_test_support.py`, `tests/core_module_allowlist.py`

**Interfaces:**
- Consumes: Tasks 3-7.
- Produces: a test suite that collects and passes with no Prime checkout.

- [ ] **Step 1: Delete the tests whose subject is a removed surface**

Enumerate the coupled set (this is the authoritative list; do not work from
memory):

```bash
# Modules importing a removed package.
grep -rln -E 'asterion\.(applications\.prime_agent|capabilities\.prime_agent|runtimes\.prime_agent|control\.providers\.prime)' tests/ | sort > /tmp/coupled_imports.txt
# Modules asserting the legacy selector.
grep -rln -E '"prime-agent"|prime\.agent["\x27]|prime\.arc-agi-3@' tests/ | sort > /tmp/coupled_selector.txt
# Modules defaulting to a Prime checkout.
grep -rln '3th-party/prime-agent' tests/ | sort > /tmp/coupled_checkout.txt
cat /tmp/coupled_imports.txt /tmp/coupled_selector.txt /tmp/coupled_checkout.txt | sort -u
```

As of 2026-09-13 that is ~180 of 428 modules. Delete every module whose
*subject under test* is a removed surface (the `test_prime_p1..p7_*_development_*`,
`*_cli_host`, `*_development_gateway`, `*_development_sdk_provider`,
`*_authority_*`, `test_prime_source_lock`, `test_prime_development_preparation`,
`test_setup_prime_agent`, and the `prime_gateway` fixture consumers).

Of the 26 fixture trees under `tests/fixtures/`, **only two are coupled**:
`prime_gateway/` (31 hits, force-included at `pyproject.toml:90`) and
`prime-parity/` (5 hits, `ledger_id: "prime-agent-0.7.1"` in every `v1/*.json`).
Delete those two. The other 23 survive — including `prime_ecosystem/`, whose
*content is clean* (0 hits); only `test_prime_ecosystem_real_process.py:11,15`
couples it, so keep the fixture tree and delete the test.

Modules in that list whose subject is *native* are not deleted here — they go to
Step 2. Sort each grep hit into one bucket deliberately; do not bulk-delete by
filename prefix.

- [ ] **Step 2: Rewrite the tests that are native in subject but coupled by default**

These keep their subject and drop the Prime default:
- `tests/test_native_prime_differential.py` — spec rule: the neutral comparison
  reads an **exported log**. It must take a log path, never a checkout locator,
  and must not start a Prime process.
- `tests/test_prime_client_core.py`, `test_prime_client_interactive.py`,
  `test_prime_client_protocols.py`, `test_prime_client_export_share.py`,
  `test_pi_runtime_extensions.py`, `test_pi_extension_loader.mjs` — replace the
  `3th-party/prime-agent` default with an explicitly injected Asterion-owned
  resource root, or mark the Prime-dependent variant skipped with a named
  reason.
- `tests/test_distribution.py`, `test_check_promotion.py`,
  `test_standalone_repository.py`, `test_prime_make_presets.py` — update to the
  post-removal distribution and the new preset set.

- [ ] **Step 2b: Resolve the chained imports before deleting anything**

Several modules in the SURVIVES bucket import modules in the REMOVE bucket.
Deleted-but-imported modules break collection for the *surviving* file, so the
damage is silent until the suite runs:

- `tests/test_native_prime_differential.py` → imports `tests.test_prime_verified_loop` (REMOVE)
- `tests/test_native_verified_differential.py` → imports `test_native_prime_differential`
- `tests/test_control_ecosystem_mcp.py:17,21` → imports `_node_22` from `test_prime_ecosystem_real_process` (REMOVE)
- `tests/test_prime_recursive_workflow_compat.py`, `tests/test_prime_rlm_messaging_parity.py` → import `test_prime_session_context_parity` and `test_prime_verified_loop` (both REMOVE)

Resolve each by inlining the helper, promoting it to a shared neutral module, or
reclassifying the importer as REMOVE — decide per file and record which. Do not
leave a SURVIVES module importing a deleted one.

Expect the buckets to be roughly **192 REMOVE / 10 REWRITE-NATIVE / ~205
SURVIVES**, plus these must be handled explicitly or they stay red:

- `tests/test_asterion_prime_architecture.py` — the gate-assertion half is
  repaired in Task 1; `test_distribution_and_commands_have_no_p7_sdk_wrapper`
  reads `applications/prime_agent/provider.py` and seven
  `packages/typescript/prime-gateway/src/p7-solving-*.ts`, so it **crashes**
  once those are deleted. Rewrite it against the detached distribution.
- `tests/test_setup_pi.py:36,193` — uses `packages/coding-agent/dist/cli.js`,
  which is a live `FORBIDDEN_LOCATORS` entry. It is a Pi-path test, so decide
  whether the string is a real Prime edge (then it is REMOVE) or a stale path
  (then rewrite it). Do not silence it by weakening the gate.
- `tests/test_builtin_capability_source.py`, `test_builtin_controlled_code_application.py`,
  `test_default_runtime_factory.py`, `test_asterion_dci_verification.py` — drop
  the `prime-agent` / `prime.agent` expectations, keep the native ones.
- `tests/test_asterion_prime_pi_contract.py:10` and
  `tests/test_prime_operational_packaging.py:19` import
  `tools.setup_prime_agent` helpers. Move the helper to a neutral module or
  reclassify; a Prime-commit pin is itself a forbidden source-lock subject.

- [ ] **Step 3: Verify collection is clean**

Run: `uv run python -m unittest discover -s tests -t . 2>&1 | tail -5`
Expected: no ImportError / ModuleNotFoundError. Residual failures must be named
in the task's report, not silently skipped.

- [ ] **Step 4: Commit**

```bash
git add -A tests
git commit -m "test(prime): remove Prime-coupled suites and rewrite native suites without source defaults"
```

---

### Task 9: Audit the retained-but-ambiguous surfaces

**Files:**
- Audit: schema force-includes `pyproject.toml:91+`; `tools/`;
  `tests/fixtures/{operation,session_context,agent_client}/`
- Modify: `pyproject.toml`, `tools/`, `tests/fixtures/` per audit outcome.

**Interfaces:**
- Consumes: Tasks 3-8.
- Produces: a written retention decision per surface.

**Rule (spec):** source-independent schemas, generic control protocols, and
neutral log comparison code are retained **only after** an import and
package-data audit proves they have no execution edge to the removed surfaces.

- [ ] **Step 1: Audit the non-core v1 schemas**

The four closed contracts are `agent-runtime/v1`, `capability/v1`,
`capability-package/v1`, `application-assembly/v1`; those are retained
unconditionally (D-2026-09-06-02). For each of `agent-client/v1`,
`agent-control/v1`, `agent-system/v1`, `control-plane/v1`, `session-context/v1`,
`operation/v1`, `benchmark-suite/v1`, determine whether any **surviving** module
consumes it:

Run: `grep -rn '<schema-name>' src/ tests/ tools/ schemas/ --include='*.py' --include='*.ts' --include='*.json' | grep -v '^tests/fixtures/'`

Retain if a surviving consumer exists; otherwise remove the force-include and
its `schemas/` source. Record the verdict per schema in the task report.

**Watch item:** `agent-client/v1` is described in `CURRENT-STATE.md` as an
approved projection above `ControlHost`. Its *evidence* was Prime Gateway-backed
(H-035) but the contract itself may be framework-level. If the audit finds a
surviving non-Prime consumer, retain; if it does not, removal is correct and the
`CURRENT-STATE.md` sentence must be corrected in Task 10. Flag this one
explicitly rather than deciding silently.

- [ ] **Step 2: Audit `tools/`**

The classification rule: REMOVE if the tool locates, prepares, locks, or
launches a Prime checkout, or is a Prime-backed smoke/experiment/loop runner;
RETAIN if it is a neutral reducer over *recorded* evidence that starts no
process; otherwise AUDIT-LATER with a named reason.

Already resolved by evidence — do not re-litigate, just verify:

| File | Verdict | Evidence |
|---|---|---|
| `tools/setup_prime_agent.py` | REMOVE | locates/verifies/installs the pinned checkout (`--source-root`, `verify_prime_source`) |
| `tools/verify_prime_loop.py` | REMOVE | imports `setup_prime_agent`; drives `prime-agent.daemon` |
| `tools/check_prime_parity.py` | **REMOVE** | `:21,27` import `verify_prime_checkout`; `:74,84,322,330` take `--source-root` and call it. It **requires a checkout to run**, so it does not qualify for the neutral-reducer allowance |
| `tools/run_asterion_prime_p7.py` | REMOVE | `Popen`-driven P7 launcher (its replacement is the Phase 2 installed-wheel preset) |
| `tools/prime_core_smoke.py`, `tools/run_prime_core_smoke.py`, `tools/run_prime_readme_smoke.py` | REMOVE | Prime-backed smoke runners |
| `tools/prime_bounded_loop_experiment.py` | REMOVE | Prime-backed experiment |
| `tools/prime_continual_harness_experiment.py` | REMOVE | `:26` imports `control.providers.prime.harness_parity_testing` |
| `tools/prime_long_running_experiment.py` | REMOVE | `:20` imports `control.providers.prime.parity_testing` |
| `tools/prime_native_rlm_experiment.py` | REMOVE | `:38-44` imports six modules from `control.providers.prime` |
| `tools/build_prime_ipython_image.py` | REMOVE | `:21` imports `applications.prime_agent.source_lock`; builds from `operator/image` |
| `tools/materialize_prime_ipython_inputs.py` | REMOVE | `:14,19,26` import three `applications.prime_agent.operator.*` |
| `tools/generate_prime_ipython_release_spec.py` | REMOVE | `:13` imports `operator.release_spec_generation` |
| `tools/generate_prime_development_lock.py` | REMOVE | generates a Prime development lock |
| `tools/prepare_prime_development.py` | REMOVE | invoked by every `prime-pN-run` target |
| `tools/check_promotion.py` | **RETAIN, re-point** | `:240,242` reference legacy assembly paths as string literals only — no import edge. Re-point at the post-removal distribution; do not delete |
| `tools/compare_prime_p7_runs.py` | RETAIN if neutral | the spec explicitly permits neutral external-log normalization. Keep only if it reads an exported log and starts no process |
| `tools/preflight_prime_apps.py` | AUDIT | read it; it selects a legacy application set (also a REMOVE Make target) |
| `tools/check_docs.py` | RETAIN | 0 hits; survives |

Also check `tools/climb/` and `tools/build_asterion_prime_compaction_lock.mjs`.
The latter is force-included into the wheel as the **native** compaction
verifier (`pyproject.toml:80`) — RETAIN. Record the final table in the task
report, including any file not listed here.

- [ ] **Step 3: Verify the wheel contains no legacy resource**

Run: `uv build --wheel --out-dir /tmp/detach-wheel && uv run python -c "import zipfile,glob; z=zipfile.ZipFile(glob.glob('/tmp/detach-wheel/*.whl')[0]); print([n for n in z.namelist() if 'prime_gateway' in n or 'prime_agent' in n or 'providers/prime/resources' in n])"`
Expected: `[]`.

- [ ] **Step 3b: Scan the built wheel, not only the source tree**

The source scan skips `node_modules`/`dist`/`build`. A force-include that
sources a file from one of those directories would therefore be shipped
unscanned. Close that gap by running the same rule set over the wheel's own
contents:

```bash
uv run python - <<'PY'
import glob, zipfile
from asterion.agents.prime.detachment import (
    FORBIDDEN_LOCATORS, FORBIDDEN_ENV_VARS, FORBIDDEN_IMPORTS,
    FORBIDDEN_SDK_TOKENS,
)
wheel = glob.glob("/tmp/detach-wheel/*.whl")[0]
rules = FORBIDDEN_LOCATORS + FORBIDDEN_ENV_VARS + FORBIDDEN_IMPORTS + FORBIDDEN_SDK_TOKENS
hits = []
with zipfile.ZipFile(wheel) as z:
    for name in z.namelist():
        try:
            body = z.read(name).decode("utf-8", errors="replace")
        except Exception:
            continue
        for line_no, line in enumerate(body.splitlines(), 1):
            if any(tok in line for tok in rules):
                hits.append(f"{name}:{line_no}")
print(f"{len(hits)} wheel hits")
for h in hits[:20]:
    print(" ", h)
PY
```

Expected: `0 wheel hits`. Any hit means a forbidden reference is shipping inside
the distribution even though the source tree scanned clean.

- [ ] **Step 4: Commit**

```bash
git add -A pyproject.toml tools tests/fixtures schemas
git commit -m "refactor(prime): retain only audited source-independent resources"
```

---

### Task 10: Repair the surviving gates

**Files:**
- Modify: `Makefile` (`test-typescript`, `check`, `promotion-check`, and the
  `test.prime-*.provider-free` targets that invoked `prime-gateway`)

**Interfaces:**
- Consumes: Tasks 3-9.
- Produces: `make check` and `make promotion-check` run against the post-removal
  distribution without touching a removed surface.

- [ ] **Step 1: Retarget `test-typescript`**

Point it at the surviving TypeScript packages only.

- [ ] **Step 2: Resolve the `prime-gateway`-executing test targets**

For each of the ~17 targets that invoked `prime-gateway test` or
`--provider asterion.prime-gateway`: if a surviving Python-only equivalent
covers the same boundary, fold it in; otherwise delete the target and remove it
from `.PHONY` and `help`. Record which survived and which were deleted.

- [ ] **Step 3: Handle the legacy evidence reducers**

`prime-parity-inventory` and `prime-verify-system-parity` reduce Prime Gateway
parity evidence (H-035…H-037). Per the spec's Evidence correction section this
evidence is historical, so these targets are removed. **Do not** rename or
reclassify their output as native evidence.

- [ ] **Step 3b: Repair the surfaces that hard-fail on removed text**

These assert the text of files this phase deletes, so they fail at assertion
time with a misleading message rather than at import:

| Surface | Anchor | Action |
|---|---|---|
| `.github/workflows/ci.yml` | `:26` `hashFiles(...)` names `packages/typescript/prime-gateway/package-lock.json` and `.../resources/prime-artifact-lock.json`; `:27-29` **exits 1 when the cache key misses** | must be edited, and the CI npm cache repopulated, or the job hard-fails. Also `:33-34` runs `make first-run-check` + `make promotion-check`, which consume the rewritten targets |
| `tests/test_standalone_repository.py` | `:436-450` asserts those ci.yml paths; `:174-197` asserts Makefile `prime-pN-run` recipes contain `--provider prime-agent --runtime prime.agent` | rewrite both assertions to the post-removal distribution |
| `tools/climb/cycle.sh` | step list runs the prime-gateway build/test and `check_prime_parity.py --provider asterion.prime-gateway` | drop those steps; the remaining climb steps are Prime-free |
| `docs/guides/prime-control-operator-guide.md` | `:46,52,84,103,129` document `make prime-check` / `prime-setup` / `prime-verify-*` and `3th-party/prime-agent` | its link target `docs/README.md:29` must not dangle — rewrite or remove the guide and its link together |
| `docs/architecture/runtime-provider-boundaries.md`, `docs/architecture/core-only-boundary.md` | `:29,78` and `:67-68` document `prime.agent` / `prime_agent` as live | correct to the detached distribution |

`tools/check_docs.py` exempts `docs/status`, `docs/superpowers/plans` and
`docs/superpowers/specs` from *import* checks but **not** from link checks, so a
dangling link fails `make docs-check`.

- [ ] **Step 4: Verify**

Run: `make docs-check`
Expected: PASS (count will drop from 207; that is expected).

Run: `make test-typescript`
Expected: exits 0.

Run: `make promotion-check`
Expected: exits 0 and reports no Prime source root.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "refactor(prime): retarget surviving gates at the detached distribution"
```

---

### Task 11: Evidence correction

**Files:**
- Modify: `docs/status/CURRENT-STATE.md`, `docs/status/INDEX.md`,
  `docs/status/DECISIONS.md`, `docs/status/PRIME-PARITY-LEDGER.md`,
  `docs/status/PRIME-TYPICAL-APPLICATIONS.md`,
  `docs/status/FRAMEWORK-PUBLIC-INVENTORY.md`

**Interfaces:**
- Consumes: Tasks 3-10.
- Produces: status documents that distinguish the four evidence classes the spec
  names.

- [ ] **Step 1: Reclassify**

Per spec §Evidence correction, every affected claim becomes exactly one of:
P7 native verified evidence; P1-P6 historical Prime-backed compatibility
evidence; implemented-but-not-yet-live native components; unavailable
applications awaiting native replacement.

Specifically:
- `CURRENT-STATE.md` "Verified Boundary": the H-035, H-036, H-037,
  `interfaces.operations` 15/15, and system-parity 61-passed claims are
  Prime Gateway-backed → move to historical. Also correct the now-false
  "`origin/main` remains unchanged" sentence (`main == origin/main == f1d28b9e`).
- `CURRENT-STATE.md` "Current Architecture": the `agent-client/v1` sentence is
  corrected per Task 9's audit outcome.
- `INDEX.md`: add rows for the new plan and mark `PRIME-TYPICAL-APPLICATIONS.md`
  / `FRAMEWORK-INTEGRATION-WORKLIST.md` consistently with their role.
- `PRIME-PARITY-LEDGER.md` / `PRIME-TYPICAL-APPLICATIONS.md`: state the
  historical boundary explicitly.

- [ ] **Step 2: Verify documentation links**

Run: `make docs-check`
Expected: PASS.

- [ ] **Step 3: Run the phase acceptance gate**

Run: `uv run python -m unittest -v tests.test_prime_source_detachment_real_tree`
Expected: PASS — the red baseline from Task 2 is now green.

Run: `uv run python -m unittest -v tests.test_prime_source_detachment`
Expected: PASS.

- [ ] **Step 4: Journal and commit**

```bash
git add -A docs
git commit -m "docs: correct evidence classification after native detachment"
```

Then: `project-state journal "Phase 1 完成：legacy Prime 执行面移除，语义 detachment 门禁转绿"`

---

## Phase 1 completion criteria

Phase 1 is complete only when all of these hold:

- `assert_asterion_prime_source_detached` scans the complete release surface
  (`src/asterion`, `packages/typescript`, `tools`, `tests`, `Makefile`,
  `pyproject.toml`) and fails on representative forbidden references (Task 1
  tests) while not false-positiving on `ASTERION_PRIME_OPERATOR_ROOT` /
  `ASTERION_PRIME_NODE`.
- The real-tree test passes with no Prime checkout present.
- `pyproject.toml`, `Makefile`, and the wheel contain no Prime-backed provider,
  runtime, host-service, preset, or packaged Prime resource.
- `make check`, `make promotion-check`, `make docs-check`, and
  `make test-typescript` pass against the detached distribution.
- P1 and P2-P6 are **unavailable** by metadata lookup, with no fallback path and
  no executable stub.
- No historical Prime-backed result is reclassified as native evidence.

Phase 1 does **not** deliver: P7 revalidation, any rebuilt P1-P6 application, or
any new live run. Those are Phases 2-9.

---

## Risks carried into later phases

1. **P7 may currently depend on the Prime checkout lock.** The
   `pi-compaction-lock.json` identified in Task 3 is verified by
   `tools/check_promotion.py:167-187` against `external_prime_root`, and the
   native P7 preset (`Makefile:293-295`) runs from a source tree. If the native
   `asterion.prime` path resolves compaction through the same lock, Phase 3
   (P7 revalidation) will fail until an Asterion-owned replacement exists.
   **This is expected, not a regression**: the spec's migration order places P7
   revalidation after removal precisely to surface this. Do not restore the
   Prime lock to make P7 pass.
2. **The "separately pinned Pi runtime" the spec calls an allowed foundation
   has not been shown to exist in detached form.** Every artifact inspected so
   far that is named "pi" resolves under `ASTERION_PRIME_SOURCE_ROOT`. Phase 3
   must either name the genuinely detached Pi artifact or report that one does
   not exist — this is an evidence question, not a relabeling exercise.

## Open questions carried forward

1. **`agent-client/v1` retention** — resolved by Task 9's audit, flagged for
   explicit reporting rather than silent decision.
2. **`../external-prime/arc-agi-3/venv/bin/python`** in `asterion-prime-p7-solve`
   (`Makefile:295`) — an external venv path outside the repo. It is not
   `3th-party/prime-agent.git` and is not covered by that prohibition, but
   Phase 2 must decide whether the ARC broker is injected as a host service
   rather than referenced as a sibling venv path.
3. **Rust surface** — this plan does not touch `executor.controlled`; confirm in
   Phase 2 that no Rust path references a Prime surface.
