# Asterion DCI Functional Verification Guide

This guide validates DCI as a product built on Asterion's generic capability
package and benchmark contracts. Product semantics are documented in the
[complete reference](../guides/asterion-dci-complete-reference.md); the shorter
operator path is in the [capability usage guide](../guides/asterion-capability-usage.md).

## Evidence language

- **Implemented** means production code and an entry point exist.
- **Verified** means the named command passed inside its stated boundary.
- **External-limited** means execution still needs external data, services,
  credentials, or operator authority.
- **Not rerun** means a full dataset or published score was not reproduced.

Command reachability is not functional closure, and bounded execution is not
paper reproduction.

## Provider-free repository setup

```bash
uv sync --frozen
make setup-pi
make setup-resources-basic
cp .env.template .env
make doctor
```

Setup may use network and disk but performs zero Agent/Judge operations and
runs no dataset. Pi, corpora, datasets, credentials, generated output, and
private evidence stay outside the wheel and Git.

`DCI_PI_DIR` selects the locked Pi checkout, `DCI_PI_AGENT_DIR` selects
separately managed authentication, and `ASTERION_DCI_RESOURCE_ROOT` anchors
operator-owned resources. A global `pi` executable does not replace the locked
checkout.

## Installed discovery and acceptance

```bash
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
```

`list` is metadata-only. `describe` loads only the selected application
provider. `acceptance` validates packaged providers, assemblies, capability
manifests, suites, resources, implementation bindings, and conformance assets.
All three paths are provider-free and must expose no prompt, answer,
credential, private path, or provider payload.

Expected cost boundary:

```text
Agent operations: 0
Judge operations: 0
Full dataset ran: no
```

## DCI adapter surface

```bash
uv run asterion-dci list
uv run asterion-dci describe
uv run asterion-dci preflight
uv run asterion-dci basic
uv run asterion-dci complete
uv run asterion-dci run --help
uv run asterion-dci benchmark --help
```

`preflight` checks readiness only. `basic` and `complete` can perform bounded
provider work after operator configuration is supplied. The adapter fixes the
exact DCI application and delegates benchmark behavior to the generic host.

## Benchmark plan verification

The package publishes `dci.github@1.0.0` (12 tasks),
`dci.paper-main@1.0.0` (13 tasks), and `dci.all@1.0.0` (15 tasks). Verify a
bounded provider-free plan:

```bash
uv run asterion-dci benchmark plan --case-limit 1
```

Verify the generic command shape independently:

```bash
uv run asterion benchmark plan \
  --application dci.complete-application@1.0.0 \
  --suite dci.all@1.0.0 \
  --case-limit 1
```

Pass criteria:

1. The plan is deterministic, immutable, body-free, and ordered by the suite.
2. Plan creation writes no evidence and loads no implementation provider.
3. GitHub and paper-main Bamboogle remain distinct task identities.
4. Dataset/corpus paths and environment values never enter the public plan.

## Authorized execution and resume verification

The generic benchmark run shape is:

```bash
uv run asterion-dci benchmark run \
  --case-limit 1 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK" \
  --evidence-root "$OPERATOR_SELECTED_PRIVATE_EVIDENCE_ROOT" \
  --execute
```

This command is executable only when an embedding operator host injects
authority, implementations, executor, cancellation, output directories, and a
private evidence service. The plain installed CLI intentionally lacks that
authority.

Resume additionally requires the compatible run ID:

```bash
uv run asterion-dci benchmark resume \
  --run-id "$COMPATIBLE_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK" \
  --evidence-root "$OPERATOR_SELECTED_PRIVATE_EVIDENCE_ROOT" \
  --execute
```

Pass criteria:

1. Missing `--execute`, source lock, evidence root, or host authority fails
   before implementation loading.
2. Tasks run once, sequentially, and stop on first failure or cancellation.
3. Compatible resume skips only the exact completed prefix.
4. Private evidence is immutable and mode-restricted.
5. Public results and errors redact prompts, answers, credentials, corpus
   bodies, raw output, provider payloads, and private paths.

## Repository and distribution gates

```bash
make test
make lint
make docs-check
make check
make promotion-check
```

`make check` covers Python, TypeScript, Rust, docs, and build. The promotion
gate repeats provider-free validation from a temporary standalone copy.

Full-dataset and paper-score execution remains **Not rerun** and requires
separate authorization plus a finite budget. The passing one-case Bamboogle
run is **Verified-bounded** and must never be promoted to published-score
evidence.

## Troubleshooting without weakening evidence

- Missing Pi or resources: repair the operator-owned external roots; do not
  vendor them into the package.
- Missing execution authority: use an approved embedding host; flags,
  credentials, cache, and prior evidence do not create authority.
- Source ambiguity: provide an exact source lock; do not introduce hidden
  precedence.
- Resume incompatibility: start a new run; do not mutate closed evidence.
- Isolated-wheel mismatch: inspect packaged resources and entry points before
  changing expected identities.
