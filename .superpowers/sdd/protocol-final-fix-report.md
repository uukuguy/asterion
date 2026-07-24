# Protocol Final Review Fix Report

Date: 2026-07-24
Base: `a607d6a794694b1400eee355be243a50a6fe648d`
Cost boundary: provider-free only

## Outcome

All four findings in `.superpowers/sdd/protocol-final-review.md` are addressed.
The catalog no longer re-resolves checked pathnames for discovery, direct
runtime/adapter errors do not echo provider-controlled keys or call IDs,
architecture documents match the shipped controlled-code graph and APIs, and
the recovery checkpoint distinguishes implemented work from approved future
application tasks.

## Finding-to-fix mapping

### 1. Catalog root/document replacement TOCTOU

Commit: `798591bb735d9f094dae0f966acde63fa5dbf41c`

Changed:

- `src/asterion/packages/catalog.py`
- `tests/test_package_catalog.py`

Fix:

- Requires descriptor-relative `open`, descriptor `listdir`, no-follow `stat`,
  `O_DIRECTORY`, and `O_NOFOLLOW`; discovery raises
  `secure package discovery is unavailable` when the platform cannot supply the
  complete safe primitive set.
- Opens every explicit root with `O_DIRECTORY | O_NOFOLLOW` and keeps all root
  descriptors pinned through sorting and discovery.
- Derives canonical root provenance from the descriptor, not a later pathname:
  Darwin uses `F_GETPATH`; Linux uses `/proc/self/fd/<fd>`.
- Enumerates names from `os.listdir(root_fd)`, filters only direct `.json`
  children, opens each name relative to the same `root_fd` with `O_NOFOLLOW`,
  validates the opened object as a regular file with `fstat`, and parses JSON
  only through that descriptor.
- Constructs `CatalogEntry.source` from the pinned canonical root plus the
  enumerated child name. It never resolves a child pathname after a possible
  replacement.
- Preserves exact refs, immutable manifest snapshots, stable sorting, duplicate
  root/identity rejection, local provenance, chained local exceptions, and the
  public catalog API. It adds no scanning, range, registry, or precedence rule.

Deterministic regression coverage:

- Document replacement patches both the old `Path.is_symlink()` boundary and
  new descriptor-open boundary, replacing `capability.json` with an external
  symlink immediately before use.
- Root replacement similarly swaps the configured root for an external
  directory symlink immediately before use.
- Descriptor reads are guarded by external device/inode, so accepting or
  reading the external body fails the test independently of sentinel redaction.
- A separate test disables the safe primitive flag and proves discovery fails
  closed.

### 2. Provider-controlled values in public errors

Commit: `71dff6a6f97b7152d6329ec01c33324d7674f82b`

Changed:

- `src/asterion/runtime/protocol.py`
- `src/asterion/adapters/pi.py`
- `src/asterion/adapters/claude_code.py`
- `tests/test_runtime_protocol.py`
- `tests/test_runtime_adapter_redaction.py`

Fix:

- Closed-object rejection retains its structural label and `unknown fields`
  classification without listing unexpected keys.
- Runtime duplicate call, unmatched result, and duplicate result failures name
  only the lifecycle location.
- Pi duplicate/unmatched tool failures and Claude Code duplicate tool-use/result
  failures no longer interpolate native call IDs.
- Validation remains closed and lifecycle state remains exact; no checks were
  removed or relaxed.

Direct sentinel coverage:

- Runtime manifest, run request, nested input, event, and event-payload
  unexpected keys use `SECRET-UNEXPECTED-KEY`.
- Runtime duplicate/unmatched tool lifecycle cases use
  `SECRET-PROVIDER-CALL-ID`.
- Direct Pi and Claude adapter matrices cover duplicate call, unmatched result,
  and duplicate result paths with the same sentinel.
- Every case asserts both precise structural rejection and sentinel absence.

Adjacent audit:

- The remaining messages on these paths interpolate only validator-owned labels
  or fixed schema field names.
- No targeted `ProtocolError` still interpolates a provider call ID or lists an
  unexpected key.

### 3. Architecture/import drift

Commit: `61680569de39ef3fc5bec64a99f45768fe9ad95f`

Changed:

- `docs/architecture/controlled-code-validation-packages.md`
- `docs/architecture/composable-packages.md`
- `docs/architecture/local-package-catalog.md`
- `tools/check_docs.py`
- `tests/test_standalone_repository.py`
- `docs/superpowers/plans/2026-07-24-protocol-final-review-fixes.md`

Fix:

- The controlled-code graph now shows direct runner `input_text`,
  runtime-owned `filesystem.read`, host-owned `executor.controlled`, the policy
  dependency, and the real workflow-produced completion/report edges consumed
  by evaluation and observability.
- The documented workflow JSON has empty `consumes_events` and
  `consumes_artifacts`; the assembly boundary is documented with empty host
  events/artifacts.
- Examples import `compose_packages` from
  `asterion.packages.composition`, and catalog examples import
  `PackageRef`/`discover_packages` from `asterion.packages.catalog`.
- The docs checker rejects stale `dci.framework` references and resolves every
  explicit `asterion.*` import in Python fenced snippets. A copied-tree
  regression proves a missing documented symbol fails and a real symbol passes.
- The local catalog document describes pinned descriptor discovery and the
  explicit fail-closed portability boundary.

### 4. Recovery checkpoint drift

Commit: `61680569de39ef3fc5bec64a99f45768fe9ad95f`

Changed:

- `docs/status/RESUME-NEXT-SESSION.md`

Fix:

- Replaced contradictory historical/current bullets with one cumulative,
  time-qualified live checkpoint.
- Removed closed counterexamples and red-gate claims.
- Records Protocol Tasks 1–8 and pulled-forward Application Authority Task 1 as
  implemented.
- Records Application Authority Tasks 2–8 as approved future work and states
  explicitly that no `asterion.host_services` registry exists yet.
- Sets the immediate next action to final whole-branch re-review, followed by
  Application Authority Task 2 after a clean verdict.
- Prior journal lines were not edited. Repository commit automation required
  append-only, one-line entries for the three durable commits; no progress
  ledger was changed.

## RED evidence

Catalog before production fix:

```text
uv run python -m unittest -v tests.test_package_catalog
FAILED: 12 run, 3 failures
- document replacement: PackageCatalogError not raised
- root replacement: PackageCatalogError not raised
- safe primitives unavailable: PackageCatalogError not raised
```

This reproduced the old traversal: both swapped external manifests were
accepted, and no safe-primitive gate existed.

Redaction before production fix:

```text
uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_runtime_adapter_redaction
FAILED: 8 run, 4 failures
```

The failures showed `SECRET-UNEXPECTED-KEY` in the validator exception and
`SECRET-PROVIDER-CALL-ID` in runtime, Pi, and Claude duplicate lifecycle
exceptions.

Documentation contract before checker fix:

```text
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets
FAILED: 1 run, 1 failure
```

The old checker returned success for `from asterion.fixture import MISSING_API`.

## Verification evidence

All commands below were run after the fixes and without provider-backed
operations.

```text
uv run python -m unittest -v tests.test_package_catalog
PASS: 12 tests

uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_runtime_adapter_redaction \
  tests.test_asterion_pi_runtime \
  tests.test_asterion_claude_runtime
PASS: 27 tests

uv run python -m unittest -v \
  tests.test_protocol_canonical_ordering \
  tests.test_runtime_protocol \
  tests.test_package_composition \
  tests.test_package_catalog \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_dci_research_capability \
  tests.test_controlled_code_application
PASS: 72 tests

uv run python -m unittest -v tests.test_runtime_adapter_redaction
PASS: 2 tests

npm --prefix packages/typescript/asterion-runtime test
PASS: 13 tests

make test
PASS: 252 tests

make check
PASS: 252 Python tests; compile/Ruff; 25 Markdown files and 39 links;
      TypeScript 13 + 11 tests; Rust 19 tests plus fmt/clippy;
      sdist and wheel build

make lint
PASS: compileall and Ruff

make docs-check
PASS: 25 Markdown files and 39 local links

make promotion-check
PASS: 18 commands, provider_operations=0, full_dataset=no

git diff --check
PASS
```

The former 67-test review gate consisted of the seven-suite 63-test command plus
four canonical-ordering tests. The same combined set now has 72 tests because
this wave adds five catalog/runtime regressions. The two direct adapter tests
are reported separately.

No provider-backed Agent/Judge work, full benchmark, published-score
reproduction, or paper experiment was run.

## Portability decisions and concerns

- Safe discovery is intentionally supported only where Python exposes the
  required POSIX descriptor primitives and pinned-descriptor provenance:
  Darwin and Linux. Other platforms reject discovery rather than using
  `Path.is_symlink()` plus `Path.read_text()`.
- The final root component and every document are opened with no-follow
  semantics. Intermediate components retain the existing path-resolution
  behavior; canonical provenance comes from the pinned root descriptor.
- This verification session ran on Darwin 25.3 and directly exercised
  `F_GETPATH`. The Linux `/proc/self/fd` branch is implemented fail-closed but
  was not executed on this Darwin host.
- There are no known functional blockers. The next authority boundary remains
  Application Authority Task 2; this wave does not implement any future
  application registry, service discovery, provider operation, or benchmark.

## Final re-review follow-up

The final re-review identified three remaining failures. The following two
commits close them:

- `0a0639ceb939bd8557df05f8d5d08c907dd520cc` —
  `fix: reject intermediate catalog symlinks`
- `24872772e8159c7f81dc9e6e314540da2da48a04` —
  `fix: make documentation import checks total`

### Component-pinned catalog roots

The earlier portability statement that intermediate components retained normal
path resolution is superseded. Catalog roots now have one explicit physical
path contract:

- Absolute roots start from a pinned `/` descriptor and relative roots start
  from a pinned current-directory descriptor.
- Every remaining component is opened relative to its parent descriptor with
  `O_DIRECTORY | O_NOFOLLOW`; an intermediate or final symbolic link is
  rejected.
- `..` is rejected. Empty paths and `.` select the pinned starting directory;
  normalized empty and `.` components are ignored.
- Callers provide a physical path. Discovery does not resolve aliases into an
  accepted root; canonical provenance still comes only from the final pinned
  descriptor.

The deterministic intermediate-alias regression points an alias at an external
parent containing a sentinel manifest and proves discovery rejects the root
without exposing or accepting that identity. The existing root-replacement
regression now triggers at the descriptor-relative component open.

One `ExitStack` owns the anchor, intermediate, and final descriptors for every
root. Each successful `os.open` is registered for cleanup immediately, before
provenance or any later operation. Normal completion, structural catalog
errors, duplicate-root unwinding, and `BaseException` unwinding therefore use
the same lifecycle. The `KeyboardInterrupt` regression records every opened
root descriptor, interrupts descriptor provenance, and proves all recorded
descriptors are closed.

Catalog RED:

```text
uv run python -m unittest -v tests.test_package_catalog
FAILED: 15 tests, 3 failures
- intermediate symbolic-link root was accepted
- a root containing `..` was accepted
- descriptor provenance interrupted by KeyboardInterrupt leaked a descriptor
```

Catalog GREEN:

```text
uv run python -m unittest -v tests.test_package_catalog
PASS: 16 tests

uv run ruff check src/asterion/packages/catalog.py tests/test_package_catalog.py
PASS
```

### Static and total documentation import checking

The documentation checker now handles both `ast.Import` and `ast.ImportFrom`.
It resolves every `asterion` module component with
`PathFinder.find_spec()` and the preceding package's
`submodule_search_locations`; it never calls `import_module`. Explicit symbols
are checked against statically parsed top-level source bindings, with an
existing child module accepted as an importable symbol.

When a fenced block is not valid Python, the checker extracts candidate
Asterion import statements, including continued multiline statements. Every
candidate `SyntaxError` becomes `documented import is invalid`; no syntax
exception or traceback escapes the checker.

The copied-tree regression uses a module that writes a marker if imported. It
proves direct and from-import success without the marker, proves
`import asterion.definitely_missing` fails, proves a missing explicit symbol
fails, and proves an unfinished multiline import returns a structural error
without a traceback.

Documentation checker RED:

```text
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets
FAILED: 1 test, 4 failing subtests
- direct missing module returned success
- missing/valid from-import cases executed module code
- malformed multiline import escaped with a SyntaxError traceback
```

Documentation checker GREEN:

```text
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_handles_links_and_rejects_unsafe_targets
PASS: 2 tests

make docs-check
PASS: 25 Markdown files, 39 local links

uv run ruff check tools/check_docs.py tests/test_standalone_repository.py
PASS
```

### Final provider-free verification

All final gates were rerun after both follow-up fixes:

```text
expanded protocol/application gate
PASS: 76 tests

uv run python -m unittest -v tests.test_runtime_adapter_redaction
PASS: 2 tests

npm --prefix packages/typescript/asterion-runtime test
PASS: 13 tests

make test
PASS: 256 tests

make check
PASS: 256 Python tests; compile/Ruff; 25 Markdown files and 39 links;
      TypeScript 13 + 11 tests; Rust 19 tests plus fmt/clippy;
      sdist and wheel build

make lint
PASS: compileall and Ruff

make docs-check
PASS: 25 Markdown files, 39 local links

make promotion-check
PASS: 18 commands, provider_operations=0, full_dataset=no

git diff --check
PASS
```

No provider-backed operation, benchmark, or full-dataset run was performed.

## Second final re-review follow-up

The second final re-review found one remaining implementation failure and one
recovery-state drift:

- Static import resolution depended on importlib `_NamespacePath` parent state
  and raised `KeyError` for valid PEP 420 namespace children.
- The live checkpoint still stopped at the first corrective wave and retained
  stale 72/252 test totals.

Commit `f9d7861ef1fd0679acad7346747f0bba1eb8c490`
(`fix: resolve namespace imports without execution`) closes the implementation
finding.

### Concrete namespace resolution

The checker no longer uses `PathFinder`, `ModuleSpec`,
`spec.submodule_search_locations`, `sys.modules`, import loaders, or module
execution. It begins with concrete filesystem entries from `sys.path` and
resolves each dotted component using source-only import precedence:

- A regular source package has a valid `__init__.py`, statically parsed
  bindings, and its package directory as the only child root.
- A regular source module has statically parsed bindings and no child roots.
- A namespace component carries every matching directory from the current
  search roots in path order, allowing a namespace to span multiple roots.
- A module cannot have a later child component.
- Missing paths, filesystem errors, invalid source syntax, and unresolved
  components return an unavailable documentation result. They do not escape as
  exceptions or tracebacks.

Both copied-tree layouts are isolated from installed packages with `python -S`.
The regular-parent fixture contains `asterion/__init__.py`,
`asterion/ns/child.py`, an invalid-source child, and a symlink-loop child. The
top-level namespace fixture splits `asterion/top/` children across two
`PYTHONPATH` roots. Module and package source files write a marker if executed.

The matrix proves, for both namespace shapes:

- direct child imports pass;
- `from`-imported child modules pass;
- explicit source bindings pass;
- a second namespace root participates in child resolution;
- missing children and missing symbols fail structurally;
- syntax and filesystem resolver failures fail structurally;
- no traceback escapes and no side-effect marker is created.

Namespace RED:

```text
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_resolves_namespace_packages_without_importing
FAILED: 1 test, 13 failing subtests
- valid nested and top-level namespace imports raised KeyError: 'asterion'
- missing, syntax, and resolver failures escaped as tracebacks or false results
```

Namespace GREEN:

```text
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_validates_asterion_import_snippets \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_resolves_namespace_packages_without_importing \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_checker_handles_links_and_rejects_unsafe_targets
PASS: 3 tests

make docs-check
PASS: 25 Markdown files, 39 local links

uv run ruff check tools/check_docs.py tests/test_standalone_repository.py
PASS
```

### Refreshed final provider-free verification

```text
expanded protocol/application gate
PASS: 76 tests

uv run python -m unittest -v tests.test_runtime_adapter_redaction
PASS: 2 tests

npm --prefix packages/typescript/asterion-runtime test
PASS: 13 tests

make test
PASS: 257 tests

make check
PASS: 257 Python tests; compile/Ruff; 25 Markdown files and 39 links;
      TypeScript 13 + 11 tests; Rust 19 tests plus fmt/clippy;
      sdist and wheel build

make lint
PASS: compileall and Ruff

make docs-check
PASS: 25 Markdown files, 39 local links

make promotion-check
PASS: 18 commands, provider_operations=0, full_dataset=no

git diff --check
PASS
```

`docs/status/RESUME-NEXT-SESSION.md` is now cumulative through `f9d7861`,
records 76/257 as the current test boundary, retains final re-review as the
immediate next action, makes Application Authority Task 2 conditional on a
clean verdict, and reads this complete report with `cat`.

No provider-backed operation, benchmark, or full-dataset run was performed.
