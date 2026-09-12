# Task 3 report: exact host-resolved Pi extension bindings

Commit: `dde2bac1 feat: bind exact pi application extensions`

## Scope

Implemented the framework-only Pi extension binding/preflight seam and wired it
through the default `pi.reference` factory and process launch. No P7 extension,
application, provider configuration, `.env` access, Prime Agent source, or SDK
dependency was added.

## Files

- `src/asterion/runtimes/pi_extensions.py` — immutable, redacted exact binding
  with identity/path/capability/FD/environment validation and resource preflight.
- `src/asterion/runtime/defaults.py` — optional exact host-service resolution,
  fail-closed ambiguity/collision checks, command/environment/capability wiring.
- `src/asterion/runtimes/pi.py` — explicit immutable inherited-FD configuration
  and allowlisted descriptor union at process launch.
- `tests/test_pi_runtime_extensions.py` — structural, factory, preflight,
  redaction, no-extension regression, and real-child-process coverage.

## RED evidence

- `uv run python -m unittest -v tests.test_pi_runtime_extensions` initially
  exited 1 with `ModuleNotFoundError: No module named
  'asterion.runtimes.pi_extensions'`, proving the required type was missing.
- After the minimal immutable type was GREEN, the expanded validation suite
  exited 1 with 24 expected assertion failures for the unimplemented exactness
  checks.
- Self-review added an unselected-host-binding preservation test; it exited 1
  because the factory raised `runtime host Pi extension is ambiguous` without
  an `extension_host_capability` option.

## GREEN evidence

- Focused extension suite: 12 tests, all passed.
- Exact requested regression command:
  `uv run python -m unittest -v tests.test_pi_runtime_extensions tests.test_default_runtime_factory tests.test_asterion_pi_runtime`
  ran 58 tests in 4.658s, all passed.
- `uv run ruff check` on all four owned files: `All checks passed!`.
- `uv run python -m py_compile` on all four owned files: exit 0.
- `git diff --check` on all four owned files: exit 0.

## Self-review

- Corrected the no-selection branch to ignore unselected extension-shaped host
  services, preserving existing `pi.reference` behavior exactly.
- Confirmed selected service identity equals `binding.extension_id`, more than
  one exact binding is rejected, base/extension capability overlap is rejected,
  and environment collisions fail before client construction.
- Confirmed a closed inherited FD fails factory preflight before client/process
  construction, while the runtime rechecks inherited FDs immediately before
  spawning to narrow the close-after-factory race.
- Confirmed the child receives the literal `--extension PATH`, only configured
  environment plus the extension snapshot, and the allowlisted descriptor;
  extension secrets and paths do not appear in public runtime events or reprs.

## Concerns

- This seam deliberately does not implement or register the P7 extension.
- Environment names are confined to the canonical namespace derived from the
  extension ID (`prime.ipython` -> `ASTERION_PRIME_IPYTHON_*`); values remain
  opaque and redacted.

## Approved pinned-loader fix

Fix commits:

- `74c246b1 fix: pin pi extension resources through launch`
- `872709bb fix: preserve pi protocol integers during redaction`

Review identified that the first implementation validated only path and FD
numbers at factory time. The approved protocol amendment replaces direct
extension-path loading with an installed Asterion-owned Node loader and an
explicit single-run resource lease. Preflight now opens the regular `.mjs`
source without following symlinks, validates its conservative self-contained
ESM form, snapshots its accepted bytes into an owned inherited FD, duplicates
every declared inherited descriptor, rewrites only declared `*_FD` values, and
holds the loader identity through launch. The runtime revalidates the loader
and every owned FD immediately before spawn and closes the lease on success,
failure, cancellation, explicit close, or finalization without a run.

Additional owned files:

- `src/asterion/runtimes/resources/asterion_pi_extension_loader.mjs` — reads
  and closes the pinned source FD, verifies size and SHA-256, imports exactly
  those bytes through a data URL, and exposes only a generic failure.
- `tests/test_pi_extension_loader.mjs` — direct loader byte-identity, generic
  digest-failure, environment removal, and rejection-path FD-cleanup tests.
- `.superpowers/sdd/task-3-brief.md` — append-only approved protocol amendment.

### Fix RED evidence

- The new Node loader test initially failed because the loader resource did not
  exist (`ERR_MODULE_NOT_FOUND`).
- The deterministic Python race tests initially showed the original extension
  path in argv, unchanged caller FD numbers, no unsupported-source rejection,
  and no installed-loader locator.
- The adversarial event test initially exposed the sentinel secret/private path
  when they appeared as mapping keys; after value/key redaction, the tightened
  FD-metadata assertion still failed on the embedded source descriptor.
- The loader rejection-cleanup test initially failed because a valid source FD
  remained open when another metadata field was invalid.
- Final independent review reproduced an owned descriptor emitted as a JSON
  integer in public tool arguments/results; the focused regression failed with
  `7 != '<redacted>'` before typed descriptor redaction was added.
- Follow-up review then showed global integer redaction could corrupt a valid
  usage counter equal to an FD. The strengthened test failed during protocol
  validation until integer redaction was confined to free-form tool
  argument/result subtrees.

### Fix GREEN evidence

- `node --check src/asterion/runtimes/resources/asterion_pi_extension_loader.mjs`
  exited 0.
- `node --test tests/test_pi_extension_loader.mjs` ran 3 tests, all passed.
- `uv run python -W error::ResourceWarning -m unittest -v
  tests.test_pi_runtime_extensions` ran 19 tests, all passed.
- Exact regression command `uv run python -W error::ResourceWarning -m
  unittest -v tests.test_pi_runtime_extensions tests.test_default_runtime_factory
  tests.test_asterion_pi_runtime` ran 65 tests in 4.855s, all passed.
- `uv run ruff check` and `uv run python -m py_compile` on the four Python
  owned files passed; `git diff --check` on the expanded owned set passed.
- Independent scoped re-review returned CLEAN after field-aware integer
  redaction preserved protocol-owned usage counters.
- A wheel built with `uv build --wheel` contained
  `asterion/runtimes/resources/asterion_pi_extension_loader.mjs`, so no package
  metadata change was required.

### Fix self-review

- Replacing the original path after factory construction executes the pinned
  original bytes, including through the real Node loader.
- Closing and reusing an original declared FD number cannot substitute the
  duplicated resource observed by the child.
- Relative, symlink, TypeScript, relative/bare/dynamic import, loader
  replacement, and closed-resource cases fail before child process start.
- Adversarial stdout, stderr, provider/model, message, tool argument/result,
  mapping-key, string/integer FD, and error channels do not expose extension
  paths, environment names/values, loader metadata, or FD metadata in public
  events/errors; protocol-owned numeric usage fields remain intact.
- Parent and child descriptors are explicitly closed across normal completion,
  protocol errors, invalid metadata, launch failure, and pre-start cancellation.

### Remaining concerns

- The loader intentionally accepts only a self-contained `.mjs` artifact with
  static `node:` imports; source graphs and TypeScript require a host-side build
  step before binding.
- This task still does not implement or register the P7 extension itself.

## Final review hardening

Commit: `20b7d90c fix: harden pi extension validation boundaries`

The final Task 3 re-review identified four additional boundary cases. This
follow-up reserves the loader's internal environment namespace at binding
construction, scopes redaction to known free-form Pi payload fields, rejects
multiline re-exports, and removes the obsolete original-path argv API from
`PiExtensionBinding`.

### Final-review RED evidence

- `test_extension_binding_rejects_reserved_loader_environment_before_io`
  failed for both `pi` and `pi.extension`: bindings could declare
  `ASTERION_PI_EXTENSION_SOURCE_FD` without rejection.
- `test_redaction_preserves_protocol_controls_matching_environment` failed
  before acknowledgement because global substring replacement corrupted raw
  event keys/types and the `asterion-1` response ID for environment values
  exactly `type`, `response`, `1`, and `call-`.
- `test_factory_rejects_multiline_and_compact_reexports_before_client` failed because a
  multiline relative re-export reached `PiRuntimeClient` construction.
- Independent review of the first matcher then reproduced valid compact
  `export {value}from` and `export*from` forms reaching client construction;
  both failed the expanded regression before optional whitespace was accepted.
- The immutable-binding test failed because the obsolete unsafe
  `PiExtensionBinding.command_args()` method still existed.

### Final-review GREEN evidence

- Reserved internal names now fail during binding construction, with mocked
  `os.open` and `os.dup` both proven uncalled for both colliding extension IDs.
- Field-aware redaction preserves Pi event discriminators, response and tool
  IDs, tool names, booleans, and usage integers; it redacts strings/integers
  only in tool arguments/results and text only in assistant delta/content
  fields. The short-value adversarial stream completes validly.
- Multiline and compact relative/bare `export ... from` forms fail before
  runtime client/process construction.
- The focused extension suite ran 22 tests under
  `-W error::ResourceWarning`, all passed.
- The exact regression suite ran 68 tests in 5.062s under
  `-W error::ResourceWarning`, all passed.
- The Node loader suite remained 3/3 green; both Node syntax checks,
  `ruff`, `py_compile`, source `pyright`, and `git diff --check` passed.

### Final-review self-review

- No protocol schema change was required: the closed raw Pi event shapes in
  `PiProtocolAdapter` provide the bounded map of public free-form locations.
- Redaction no longer mutates arbitrary raw mappings, control keys, event
  types, IDs, or typed counters before protocol validation.
- Only `PiExtensionLease.command_args()` can produce extension argv, so callers
  cannot obtain the unpinned original extension path from the binding API.

## Comment-separated dependency hardening

Commit: `3bd3b0a2 fix: reject commented pi extension sources`

A remaining review reproduced JavaScript comments acting as lexical whitespace
inside a re-export, bypassing the conservative dependency matcher. Because the
approved artifact is a generated/self-contained `.mjs`, preflight now rejects
all source containing line/block comment markers before snapshot or inherited
descriptor duplication. The loader retains its generic failure defense.

### Comment-bypass RED/GREEN evidence

- RED: `test_factory_rejects_comment_bearing_sources_before_client` reached
  `PiRuntimeClient` for `export/*gap*/{value}from "./dependency.mjs"`.
- GREEN: a six-case matrix covering comments after `export`, before/inside
  braces, around `*`, around `from`, and before the specifier all raises
  `RuntimeFactoryError`; wrapped `os.dup` and the client are both uncalled.
- GREEN: `test_factory_accepts_minimal_self_contained_p7_extension` proves a
  comment-free default factory registering a `prime_ipython` tool remains
  accepted by the factory/lease seam.
- Focused extension suite: 24 tests under `-W error::ResourceWarning`, passed.
- Exact Python regression: 70 tests in 4.876s under
  `-W error::ResourceWarning`, passed.
- Node loader: 3/3 passed with both loader/test syntax checks; ruff,
  py_compile, source pyright, and `git diff --check` passed.

### Comment-bypass self-review

- Rejection is class-based rather than another token-specific re-export regex.
- Validation occurs after the exact source read (required to inspect bytes) but
  before the anonymous source snapshot, inherited-FD duplication, loader open,
  runtime construction, or process spawn.
- The accepted positive fixture matches the intended P7 integration shape but
  does not implement the P7 extension.

## Bounded JavaScript dependency scanner

Commit: `642e44a0 fix: lex pi extension dependencies before launch`

The final compact namespace form `export*as ns from "./dependency.mjs"`
demonstrated that dependency recognition could not remain regex-based. The
source gate now lexes identifiers, punctuators, quoted strings, and plain
template literals, rejects executable comments and interpolated templates,
and validates import/export dependency grammar independently of whitespace.

### Scanner RED evidence

- `test_factory_rejects_every_dependency_syntax_form` failed because compact
  namespace re-export reached `PiRuntimeClient`.
- `test_factory_accepts_node_imports_and_harmless_literal_words` failed for a
  compact namespace `node:` import, a multiline `node:` import, and harmless
  quoted/template text containing `import` and `from`.

### Scanner GREEN evidence

- The rejection matrix covers named, star, namespace alias, compact,
  multiline, relative/bare static and side-effect imports, dynamic relative
  and `node:` imports, and a `node:` re-export. Every case fails before source
  snapshot duplication or runtime client construction.
- The acceptance matrix covers named, compact namespace, side-effect, and
  multiline static `node:` imports plus quoted/plain-template contents holding
  dependency-like words and comment-like markers.
- The minimal P7-shaped self-contained extension remains accepted.
- Focused extension suite: 26 tests under `-W error::ResourceWarning`, passed.
- Exact Python regression: 72 tests in 6.162s under
  `-W error::ResourceWarning`, passed.
- Node loader: 3/3 passed with loader/test syntax checks; ruff, py_compile,
  source pyright, and `git diff --check` passed.

### Scanner self-review

- Only raw quoted specifiers matching the closed `node:` builtin form are
  accepted; escapes, relative/bare paths, all re-exports, and all dynamic
  imports fail closed.
- Plain string and template contents are opaque to dependency recognition.
  Template interpolation is rejected because it contains executable code that
  a bounded non-parser cannot safely ignore.
- Loader-side size/digest/source-name checks and its generic public error are
  unchanged.
- Independent scoped review reproduced the dependency matrix and returned
  CLEAN, with no correctness, security, regression, or maintainability
  findings.
