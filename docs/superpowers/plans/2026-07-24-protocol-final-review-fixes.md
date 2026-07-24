# Protocol Final Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the final catalog TOCTOU, public-error redaction, architecture-documentation, and recovery-checkpoint findings without changing the public catalog or protocol contracts.

**Architecture:** Package discovery will pin explicit root and direct-child filesystem objects with descriptor-relative, no-follow opens and will derive provenance from the pinned root descriptor. Runtime and adapter failures will report structural lifecycle locations only. Documentation will mirror checked-in declarations and validate documented `asterion.*` imports, while the live checkpoint will distinguish completed protocol work from approved future application tasks.

**Tech Stack:** Python 3.10+, POSIX descriptor APIs, `unittest`, Markdown contract checking, Git.

## Global Constraints

- Preserve `CLI/host → selected provider → assembly → catalog/composer → exact implementations → runner → runtime/host services`.
- Catalogs use explicit local roots, direct JSON children, exact `package_id@version`, deterministic ordering, and no symlink traversal.
- Fail closed when descriptor-relative no-follow primitives or pinned-descriptor provenance are unavailable.
- Public protocol and adapter errors must not expose provider-controlled keys, call IDs, or payload values.
- Keep `executor.controlled` host-owned and declarative; do not add fictional host events or host artifacts.
- Do not implement Application Authority Tasks 2–8 while repairing the live checkpoint.
- Run no provider-backed operations.

---

## File Structure

- `src/asterion/packages/catalog.py` — pinned filesystem discovery and immutable catalog entries.
- `tests/test_package_catalog.py` — deterministic document/root replacement races and portability failure.
- `src/asterion/runtime/protocol.py` — structural-only closed-field and lifecycle errors.
- `src/asterion/adapters/pi.py` — structural-only Pi tool lifecycle errors.
- `src/asterion/adapters/claude_code.py` — structural-only Claude tool lifecycle errors.
- `tests/test_runtime_protocol.py` — direct validator sentinel-redaction coverage.
- `tests/test_runtime_adapter_redaction.py` — direct Pi/Claude adapter sentinel-redaction coverage.
- `tools/check_docs.py` — validates importable `asterion.*` APIs used in Python documentation snippets.
- `tests/test_standalone_repository.py` — documentation checker regression coverage.
- `docs/architecture/controlled-code-validation-packages.md` — actual controlled-code graph and host boundary.
- `docs/architecture/composable-packages.md` — actual composer import.
- `docs/architecture/local-package-catalog.md` — actual catalog and composer imports.
- `docs/status/RESUME-NEXT-SESSION.md` — cumulative time-qualified recovery state.
- `.superpowers/sdd/protocol-final-fix-report.md` — final findings-to-fixes and verification evidence.

### Task 1: Pin catalog filesystem objects

**Files:**
- Modify: `tests/test_package_catalog.py`
- Modify: `src/asterion/packages/catalog.py`

**Interfaces:**
- Consumes: `discover_packages(roots: Iterable[Path])`.
- Produces: the existing `PackageCatalog` API, with `CatalogEntry.source` constructed from a pinned canonical root and an enumerated direct-child name.

- [ ] **Step 1: Add deterministic replacement and portability tests**

Patch both the old `Path.is_symlink()` boundary and the new `os.open()` boundary so the same tests replace a JSON child or root with an external symlink immediately before use. Assert `PackageCatalogError`, assert sentinel identities are absent from public errors, and guard descriptor reads by external device/inode. Patch the safe-primitive availability flag false and assert discovery fails closed.

- [ ] **Step 2: Run the tests red**

```bash
uv run python -m unittest -v tests.test_package_catalog
```

Expected: the document and root replacement cases fail because the current path checks and later reads/resolves are separate operations.

- [ ] **Step 3: Implement pinned discovery**

Open each root with `O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`, validate it with `fstat`, and obtain its canonical provenance from the descriptor (`F_GETPATH` on Darwin or `/proc/self/fd` on Linux). Keep all root descriptors open while sorting and discovering. Enumerate with `os.listdir(root_fd)`, open each direct JSON name using `dir_fd=root_fd` plus `O_NOFOLLOW`, validate `stat.S_ISREG(os.fstat(fd).st_mode)`, and parse only from that descriptor. Construct source paths as `pinned_root / child_name`; never call `resolve()` on a child after enumeration.

- [ ] **Step 4: Run green and commit**

```bash
uv run python -m unittest -v tests.test_package_catalog
uv run ruff check src/asterion/packages/catalog.py tests/test_package_catalog.py
git add src/asterion/packages/catalog.py tests/test_package_catalog.py
git commit -m "fix: pin package catalog filesystem objects"
```

Expected: catalog tests pass, including deterministic races and unavailable-primitive rejection.

### Task 2: Redact provider-controlled protocol values

**Files:**
- Modify: `tests/test_runtime_protocol.py`
- Create: `tests/test_runtime_adapter_redaction.py`
- Modify: `src/asterion/runtime/protocol.py`
- Modify: `src/asterion/adapters/pi.py`
- Modify: `src/asterion/adapters/claude_code.py`

**Interfaces:**
- Consumes: direct validator and adapter calls using provider-controlled mappings.
- Produces: precise structural `ProtocolError` messages that contain no unexpected key or tool call ID.

- [ ] **Step 1: Add direct sentinel tests**

For runtime manifests, run requests, events, and nested payloads, insert `SECRET-UNEXPECTED-KEY` and assert rejection plus absence from the error string. Build duplicate call, unmatched result, and duplicate result streams using `SECRET-PROVIDER-CALL-ID`, assert the structural failure class remains identifiable, and assert the sentinel is absent. Exercise equivalent duplicate/unmatched paths directly through both adapters.

- [ ] **Step 2: Run the tests red**

```bash
uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_runtime_adapter_redaction
```

Expected: sentinel keys and call IDs appear in existing exception messages.

- [ ] **Step 3: Make errors structural only**

Change unknown-field errors to `"<label> has unknown fields"` and lifecycle errors to fixed duplicate/unmatched messages. Preserve required-field labels, closed-contract checks, ordering, and all lifecycle state checks.

- [ ] **Step 4: Run green and commit**

```bash
uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_runtime_adapter_redaction \
  tests.test_asterion_pi_runtime \
  tests.test_asterion_claude_runtime
uv run ruff check \
  src/asterion/runtime/protocol.py \
  src/asterion/adapters/pi.py \
  src/asterion/adapters/claude_code.py \
  tests/test_runtime_protocol.py \
  tests/test_runtime_adapter_redaction.py
git add src/asterion/runtime/protocol.py \
  src/asterion/adapters/pi.py src/asterion/adapters/claude_code.py \
  tests/test_runtime_protocol.py tests/test_runtime_adapter_redaction.py
git commit -m "fix: redact provider-controlled protocol identifiers"
```

Expected: direct validator and adapter tests reject the same structures without exposing sentinels.

### Task 3: Align architecture docs and check imports

**Files:**
- Modify: `docs/architecture/controlled-code-validation-packages.md`
- Modify: `docs/architecture/composable-packages.md`
- Modify: `docs/architecture/local-package-catalog.md`
- Modify: `tools/check_docs.py`
- Modify: `tests/test_standalone_repository.py`

**Interfaces:**
- Consumes: checked-in controlled-code manifests and Python fenced-code imports.
- Produces: documentation for direct `input_text`, injected `executor.controlled`, runtime `filesystem.read`, and real package-produced report/event edges; docs-check rejection for unimportable `asterion.*` examples.

- [ ] **Step 1: Add a failing docs checker test**

Copy the checker into a temporary project with a Python fenced block importing a missing symbol from an importable temporary `asterion.fixture` module. Run it with that temporary source directory on `PYTHONPATH` and assert a nonzero exit. Replace the symbol with a real one and assert success.

- [ ] **Step 2: Run the test red**

```bash
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets
```

Expected: the current link-only checker accepts the nonexistent documented API.

- [ ] **Step 3: Implement import validation and correct the docs**

Parse Python fenced blocks with `ast`, import each `asterion.*` module, and verify every explicitly imported symbol exists. Update examples to:

```python
from asterion.packages.catalog import PackageRef, discover_packages
from asterion.packages.composition import compose_packages
```

Replace the controlled-code JSON and graph with the exact checked-in declarations: no host events/artifacts, `executor.controlled` remains the injected host capability, `filesystem.read` remains the runtime capability, `input_text` is passed directly to each package invocation, and evaluation/observability consume the workflow-produced report and completion event.

- [ ] **Step 4: Run green**

```bash
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets \
  tests.test_controlled_code_application
make docs-check
```

Expected: all documented `asterion.*` imports resolve and the controlled-code declaration test remains green.

### Task 4: Refresh recovery checkpoint, report, and full gates

**Files:**
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Create: `.superpowers/sdd/protocol-final-fix-report.md`

**Interfaces:**
- Consumes: final fixes and fresh verification evidence.
- Produces: a time-qualified live checkpoint and review report with actual commit hashes and command counts.

- [ ] **Step 1: Rewrite the cumulative checkpoint**

Remove closed red counterexamples and gates, remove the false Task 5 registry claim, state that Protocol Tasks 1–8 and pulled-forward Application Task 1 are implemented, state that Application Tasks 2–8 remain approved future work, and set the immediate next action to final re-review followed by Application Task 2. Do not change prior journal lines.

- [ ] **Step 2: Commit documentation and checkpoint**

```bash
git add docs/architecture/controlled-code-validation-packages.md \
  docs/architecture/composable-packages.md \
  docs/architecture/local-package-catalog.md \
  docs/status/RESUME-NEXT-SESSION.md \
  tools/check_docs.py tests/test_standalone_repository.py \
  docs/superpowers/plans/2026-07-24-protocol-final-review-fixes.md
git commit -m "docs: align protocol architecture and recovery state"
```

- [ ] **Step 3: Run the complete provider-free verification**

```bash
uv run python -m unittest -v \
  tests.test_protocol_canonical_ordering \
  tests.test_runtime_protocol \
  tests.test_package_composition \
  tests.test_package_catalog \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_dci_research_capability \
  tests.test_controlled_code_application
uv run python -m unittest -v tests.test_runtime_adapter_redaction
npm --prefix packages/typescript/asterion-runtime test
make test
make check
make lint
make docs-check
make promotion-check
git diff --check a607d6a794694b1400eee355be243a50a6fe648d..HEAD
```

Expected: the former 67-test protocol gate passes with five added regressions
(72 total), both direct adapter-redaction tests pass, TypeScript passes 13
tests, and every repository/provider-free gate passes.

- [ ] **Step 4: Write and commit the final report**

Record finding-to-fix mappings, failing pre-fix probes, portability decisions, changed files, commit hashes, exact command counts, and remaining concerns in `.superpowers/sdd/protocol-final-fix-report.md`.

```bash
git add .superpowers/sdd/protocol-final-fix-report.md
git commit -m "docs: record protocol final fix evidence"
git diff --check a607d6a794694b1400eee355be243a50a6fe648d..HEAD
git status --short
```

Expected: the report is committed, the branch diff is whitespace-clean, and the worktree is clean.

---

## Final Re-review Follow-up

### Task 5: Reject intermediate catalog symlinks and close every descriptor

**Files:**
- Modify: `tests/test_package_catalog.py`
- Modify: `src/asterion/packages/catalog.py`
- Modify: `docs/architecture/local-package-catalog.md`

**Interfaces:**
- Consumes: explicit absolute or relative physical root paths.
- Produces: the existing `discover_packages()` API with component-by-component
  no-follow root pinning and unconditional descriptor cleanup.

- [x] **Step 1: Add failing path and ownership tests**

Create an external manifest under a physical directory, point an intermediate
`alias` symlink at its parent, and assert `discover_packages(alias / "packages")`
rejects without exposing or accepting the sentinel identity. Pass a root
containing `..` and assert structural rejection. Patch root provenance to raise
`KeyboardInterrupt`, record every descriptor returned by `os.open`, and assert
all recorded descriptors are closed after unwinding.

- [x] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_package_catalog
```

Expected: intermediate alias traversal is accepted, `..` is accepted, and the
provenance descriptor remains open after `KeyboardInterrupt`.

- [x] **Step 3: Implement anchored component walking**

Use one `ExitStack` for all root descriptors. Open `/` for absolute paths or `.`
for relative paths, register each descriptor immediately, reject every `..`
component, ignore normalized `.`/empty components, and open each remaining
component relative to the previous descriptor with
`O_DIRECTORY | O_NOFOLLOW`. Obtain provenance only from the final pinned
descriptor. Update temporary tests to use `Path(...).resolve()` because callers
must provide a physical path and discovery must not resolve attacker-controlled
aliases.

- [x] **Step 4: Run GREEN and commit**

```bash
uv run python -m unittest -v tests.test_package_catalog
uv run ruff check src/asterion/packages/catalog.py tests/test_package_catalog.py
git add src/asterion/packages/catalog.py tests/test_package_catalog.py \
  docs/architecture/local-package-catalog.md
git commit -m "fix: reject intermediate catalog symlinks"
```

### Task 6: Make documentation import validation static and total

**Files:**
- Modify: `tests/test_standalone_repository.py`
- Modify: `tools/check_docs.py`

**Interfaces:**
- Consumes: Python fenced snippets containing explicit `asterion.*` imports.
- Produces: static module/symbol existence checks that never execute imported
  code and always convert malformed import syntax into a docs error.

- [x] **Step 1: Add failing static-import tests**

Create a temporary `asterion.fixture` module with a file-writing import side
effect and a statically declared `DOCUMENTED_API`. Assert direct
`import asterion.fixture` and `from asterion.fixture import DOCUMENTED_API`
pass without creating the marker. Assert
`import asterion.definitely_missing` fails. Assert an incomplete multiline
`from asterion.fixture import (` returns a structural docs error without a
traceback.

- [x] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets
```

Expected: direct missing imports pass, side-effectful modules execute, or the
malformed fallback raises `SyntaxError`.

- [x] **Step 3: Implement static validation**

Resolve module specs component-by-component with `PathFinder.find_spec()` and
their `submodule_search_locations`, without importing packages. For explicit
symbols, parse the resolved source file and collect top-level bound names; accept a child
module as an importable symbol when present. Handle both `ast.Import` and
`ast.ImportFrom`. If a full fenced block is incomplete, parse only candidate
Asterion import statements; catch every `SyntaxError` and append a structural
documentation error.

- [x] **Step 4: Run GREEN and commit**

```bash
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_handles_links_and_rejects_unsafe_targets
make docs-check
uv run ruff check tools/check_docs.py tests/test_standalone_repository.py
git add tools/check_docs.py tests/test_standalone_repository.py \
  docs/superpowers/plans/2026-07-24-protocol-final-review-fixes.md
git commit -m "fix: make documentation import checks total"
```

### Task 7: Append evidence and rerun final provider-free gates

**Files:**
- Modify: `.superpowers/sdd/protocol-final-fix-report.md`

- [ ] **Step 1: Append follow-up evidence**

Record the three re-review findings, RED/green evidence, physical-root contract,
descriptor lifecycle audit, static docs-import design, follow-up commits, and
final command counts.

- [ ] **Step 2: Run all gates**

```bash
uv run python -m unittest -v \
  tests.test_protocol_canonical_ordering \
  tests.test_runtime_protocol \
  tests.test_package_composition \
  tests.test_package_catalog \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_dci_research_capability \
  tests.test_controlled_code_application
uv run python -m unittest -v tests.test_runtime_adapter_redaction
npm --prefix packages/typescript/asterion-runtime test
make test
make check
make lint
make docs-check
make promotion-check
git diff --check
```

Expected: the expanded protocol gate, two adapter tests, TypeScript 13 tests,
all repository tests/builds, 18-command provider-free promotion, and whitespace
validation pass.
