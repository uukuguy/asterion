# Task 8 fix report: canonical ordering and audit closure

## Red probes

The shared adversarial fixtures were added before validator changes.

- Python `tests.test_protocol_canonical_ordering` ran four tests and failed the
  package and assembly lone-surrogate subtests because both validators accepted
  `"\uD800"`.
- The TypeScript suite ran twelve tests with nine passing and three failing.
  Native UTF-16 comparison rejected the scalar-valid `U+E000, U+10000` order,
  accepted the reverse, and rejected the valid `a, a.b` package-reference
  order because it compared interpolated `package_id@version` strings.

After the implementation change, the same Python probes pass four of four and
the TypeScript suite passes twelve of twelve.

## Exact ordering contract

Canonical string ordering is lexicographic Unicode scalar-value ordering:

1. Reject any string containing a code point from `U+D800` through `U+DFFF`.
2. Compare the first differing Unicode scalar value numerically.
3. If one string is a prefix of the other, the shorter string sorts first.
4. Require each canonical array to be strictly increasing, which also rejects
   duplicates.
5. Compare assembly package references field-wise by `package_id`, then
   `version`, using the same comparator. Never compare an interpolated
   `package_id@version` value.

Python retains native string/tuple ordering after explicit surrogate rejection.
TypeScript iterates code points with an explicit comparator rather than using
native UTF-16 relational comparison.

## Files

Implementation and schemas:

- `src/asterion/protocol_ordering.py`
- `src/asterion/packages/protocol.py`
- `src/asterion/assembly/protocol.py`
- `packages/typescript/asterion-runtime/src/validation.ts`
- `schemas/packages/v1/package-manifest.schema.json`
- `schemas/assembly/v1/assembly.schema.json`

Shared fixtures and tests:

- `tests/test_protocol_canonical_ordering.py`
- `packages/typescript/asterion-runtime/test/runtime.test.mjs`
- `tests/fixtures/packages/v1/valid-unicode-scalar-order.json`
- `tests/fixtures/packages/v1/invalid-unicode-scalar-order.json`
- `tests/fixtures/packages/v1/invalid-surrogate-edge.json`
- `tests/fixtures/assembly/v1/valid-canonical-order.json`
- `tests/fixtures/assembly/v1/invalid-interpolated-package-ref-order.json`
- `tests/fixtures/assembly/v1/invalid-unicode-scalar-order.json`
- `tests/fixtures/assembly/v1/invalid-surrogate-edge.json`

Documentation:

- `docs/architecture/composable-packages.md`
- `docs/architecture/dci-capability-audit.md`
- `.superpowers/sdd/task-8-fix-report.md`

The other two Task 8 documents were reviewed and did not require correction.
No file under `docs/status/` and no progress ledger was changed.

## Commits

- `1fe9662cc7840f2974096f3227f44a9ea7a681af` —
  `fix: align cross-language canonical ordering`
- `docs: close hardened protocol audit gaps` — documentation and this report
  are committed together; the containing commit supplies the final hash.

## Verification

All commands were provider-free.

```text
uv run python -m unittest -v tests.test_protocol_canonical_ordering
  PASS: 4 tests

uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_package_composition \
  tests.test_package_catalog \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_dci_research_capability \
  tests.test_controlled_code_application
  PASS: 63 tests

npm --prefix packages/typescript/asterion-runtime test
  PASS: 12 tests

make lint
  PASS: compileall and Ruff

make docs-check
  PASS: 24 Markdown files, 39 local links

make promotion-check
  PASS: provider-free promotion gate

git diff --check
  PASS
```

## Concerns

None. Sorting remains semantic validation. The only string-domain change is
lone-surrogate rejection needed to give Python and TypeScript the same Unicode
scalar domain. No v1 cardinality or media-type/value grammar was added, and no
provider operation ran.
