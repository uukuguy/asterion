# Task 9 report: prepare the DCI coverage diagnosis closure

## Result

Implemented the provider-free diagnosis boundary that can merge one immutable,
content-free aggregate from the finite Task 8 coverage experiment. The aggregate
binds the exact plan/proposal/scope/variant/registry/authorization/receipt
digests, exact ordered five-dataset cohort, safe counts and microunit metrics,
zero Judge operations, the cost ceiling, the infrastructure-failure limit, and
a derived canonical digest.

A complete aggregate requires all five datasets at 10/10, 50 Agent operations,
zero integrity failures, zero Judge operations, no more than 5,000,000 microusd,
and fewer than two infrastructure failures. Only then does diagnosis remove the
`retrieval-coverage` gap and mark query decomposition
`ready-for-authorization`. Every proposal remains
`execution_authorized=False`; no evidence automatically grants authority.
Partial or integrity-failed aggregates keep the gate blocked.

The Chinese renderer exposes only the safe aggregate fields and explicitly
states that the relation between coverage and historical scores is observational
and does not establish causality. The DCI Pathlight CLI accepts this aggregate
only through in-process dependency injection; it has no raw-artifact flag or
reader and does not invent an artifact contract before real immutable evidence
exists.

The provider-free `prepare` step produced plan digest
`e845f41bb1fa7e81857f12244cc5053393df861bc7b25e815dfb4a5126f00e90`.
This is prepared-plan evidence only.

## External execution status

**NOT RUN.** Task 9 stopped before Step 3. No provider, Agent, Judge, model,
network, or external experiment operation ran, and no observed coverage result
was produced, estimated, or published. Repository documentation therefore keeps
the query-decomposition gate `blocked-by-coverage`.

Before a finite run, the operator must verify that a private 0600 authorization
matches the prepared plan's exact:

- `plan_sha256` (currently
  `e845f41bb1fa7e81857f12244cc5053393df861bc7b25e815dfb4a5126f00e90`)
- `proposal_sha256`
- `scope_sha256`
- `variant_sha256`
- `registry_set_sha256`
- `source_lock_sha256`
- all five `registry_sha256` values
- 50 Agent operations and zero Judge operations
- 5,000,000-microusd ceiling
- stop before a third launch after two infrastructure failures
- independent `operator_approval_sha256`
- `execution_authorized=true`

Configuration, caches, old evidence, and the prepared plan itself do not grant
execution authority. After checking the exact private documents, the operator's
finite foreground command is:

```bash
env -i HOME="$HOME" PATH="$PATH" SHELL="$SHELL" zsh -lc '
  set -a
  source .env
  set +a
  uv run asterion-dci pathlight experiment execute \
    --plan-file "$ASTERION_PATHLIGHT_COVERAGE_PLAN" \
    --authorization-file "$ASTERION_PATHLIGHT_COVERAGE_AUTHORIZATION" \
    --output-root "$ASTERION_PATHLIGHT_COVERAGE_OUTPUT"
'
```

## TDD evidence

The first focused diagnosis run failed because the coverage aggregate types and
keyword boundary did not exist. Renderer and CLI tests then failed before
conditional rendering and injection were implemented. A later contradictory
partial-metric test failed against the first validator and passed after the
availability/metric invariant was tightened.

The resulting matrix covers complete, partial, integrity-failed, reordered,
subclassed, digest-tampered, and contradictory aggregates; legacy serialization;
correlation-only Chinese output; private sentinel redaction; and provider-free
CLI publication with an injected aggregate.

## Verification

```text
uv run python -m unittest -v \
  tests.test_pathlight_runtime_observation \
  tests.test_pi_pathlight_observation \
  tests.test_claude_pathlight_observation \
  tests.test_workflow_evidence_runtime \
  tests.test_pathlight_flow \
  tests.test_dci_pathlight_coverage \
  tests.test_dci_pathlight_experiment_cli \
  tests.test_dci_pathlight_diagnosis \
  tests.test_dci_pathlight_cli
  PASS: 103 tests

uv run pyright \
  src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py \
  src/asterion/applications/dci_agent_lite/pathlight_cli.py \
  tests/test_dci_pathlight_diagnosis.py \
  tests/test_dci_pathlight_cli.py
  PASS: 0 errors, 0 warnings

uv run ruff check \
  src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py \
  src/asterion/applications/dci_agent_lite/pathlight_cli.py \
  tests/test_dci_pathlight_diagnosis.py \
  tests/test_dci_pathlight_cli.py
  PASS

make docs-check
  PASS: checked 60 markdown files and 41 local links

git diff --check
  PASS
```

The pre-existing dirty `docs/status/JOURNAL.md` and
`docs/status/RESUME-NEXT-SESSION.md` are excluded from the Task 9 commit.
