# Asterion DCI Benchmark Operator Guide

List the exact immutable product instances before selecting one:

```bash
asterion-dci benchmark instances --json
```

Planning and source locking are metadata-only and provider-free:

```bash
asterion-dci benchmark lock \
  --instance dci.local-fixture@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

asterion-dci benchmark plan \
  --instance dci.local-fixture@1.0.0 \
  --capability-source-lock "$DCI_SOURCE_LOCK"
```

Execution requires the exact source lock, a private absolute evidence root,
`--execute`, and fresh host authorization:

```bash
asterion-dci benchmark run \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

Resume the returned run ID with the same instance, range, lock, and evidence
root:

```bash
asterion-dci benchmark resume \
  --instance dci.local-fixture@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

The default range is one case per selected task. `--all-cases` resolves only an
instance's finite catalog count and is mutually exclusive with
`--case-limit`; planning that range does not authorize its execution.

`dci.local-fixture@1.0.0` is provider-free. Real instances, beginning with
`dci.qa.bamboogle.github-sample50@1.0.0`, use external datasets and corpora,
the selected Agent model, an independent Judge request, and network access.
Keep provider/Judge credentials and all resource paths in operator-owned
environment or `.env` configuration. They are never package-manifest or public
plan values.

Evidence under the selected root is private and immutable. Public command
results contain only task IDs, statuses, case counts, and symbolic artifact
IDs. Full benchmark and paper reproduction runs require a separate explicit
finite-budget authorization; cached configuration, a source lock, readiness,
or prior evidence never grants that authority.

See [the instance inventory and executable
runbooks](status/DCI-BENCHMARK-INSTANCES.md) for the exact implementation,
operating procedure, and verification state.
