# Asterion DCI Functional Verification Guide

This guide verifies the promoted standalone repository. It separates installed
closure from external readiness, bounded provider-backed behavior, and parent
workspace integration history. For product semantics, see the
[complete reference](../guides/asterion-dci-complete-reference.md); for a short
operator path, see the [capability usage guide](../guides/asterion-capability-usage.md).

## Scope and evidence language

- **Implemented** means production code and a public entry point exist.
- **Verified** means the named command passed inside the stated boundary.
- **External-limited** means the interface is complete but needs external Pi,
  data, a provider, or credentials.
- **Not rerun** means a full dataset or published score was not reproduced.

Command reachability is not functional closure. Standalone acceptance must load
the installed provider and validate its complete packaged identities. Provider
backed verification must additionally prove bounded execution and safe durable
artifacts. No command in this guide implicitly authorizes a full dataset.

## Prerequisites and repository setup

Provider-free work requires Python 3.10 or newer and `uv`:

```bash
uv sync --frozen
```

Node.js 22.19.0 or newer plus npm are required to provision and run the locked
Pi checkout; Rust is required only for its cross-language checks. Pi, corpora,
datasets, and credentials are external:

```dotenv
DCI_PI_DIR=./pi
DCI_PI_AGENT_DIR=~/.pi/agent
ASTERION_DCI_RESOURCE_ROOT=.
DCI_PROVIDER=openai-codex
DCI_MODEL=gpt-5.6-luna
DCI_EVAL_JUDGE_MODEL=
DCI_EVAL_JUDGE_API_KEY_ENV=
```

Copy `.env.template` to `.env` for operator-owned settings. Prepare a fresh
clone with:

```bash
make setup-pi
make setup-resources-basic
cp .env.template .env
make doctor
```

The setup commands may use network and disk, but make zero Agent/Judge
operations and run no dataset. A global `pi` executable does not replace the
checkout locked by `pi-revision.txt`; `DCI_PI_AGENT_DIR` points to separately
managed authentication. Never commit `.env`, credentials, external resources,
or private outputs.

## Standalone provider-free verification

### 1. Discover the installed product

```bash
uv run asterion list
uv run asterion describe --provider dci-agent-lite
```

`list` is metadata-only. `describe` loads only the selected provider and reports
its applications, assemblies, packages, verification levels, cost boundary,
and body-free configuration.

### 2. Verify installed closure

```bash
uv run asterion verify --provider dci-agent-lite --level acceptance
# equivalent Make entry point
make asterion-verify-acceptance
```

Acceptance is package-owned. It checks the exact installed providers,
applications and assemblies, eleven capability manifests, five context
profiles, thirteen benchmark identities, and sixteen paper scopes. It works
from a source checkout or isolated wheel and ignores adjacent source trees.

Expected cost summary:

```text
Agent operations: 0
Judge operations: 0
Full dataset ran: no
```

### 3. Verify repository and distribution gates

```bash
make test
make lint
make docs-check
make build
make check
```

`make check` runs Python, documentation, TypeScript, Rust, and distribution
gates. None of these targets constructs a provider request.

### 4. Inspect the complete CLI surface

```bash
uv run asterion --help
uv run asterion-dci --help
uv run asterion-dci system-prompt --help
uv run asterion-dci run --help
uv run asterion-dci terminal --help
uv run asterion-dci resume --help
uv run asterion-dci evaluate --help
uv run asterion-dci benchmark --help
uv run asterion-dci export --help
uv run asterion-dci ablation --help
uv run asterion-dci paper --help
```

Help and `system-prompt` are provider-free. Other commands become cost-bearing
only when an execution path reaches an Agent or Judge.

## Cost-bearing verification

### Preflight: external readiness, zero provider operations

```bash
make asterion-verify-preflight
```

Preflight checks `.env`, `DCI_PI_DIR`, Node, required corpora, and Judge
configuration. Missing inputs produce an actionable, redacted failure. A
successful preflight is readiness evidence, not execution authority.

### Basic: bounded Agent and Judge behavior

```bash
make asterion-verify-basic
```

Basic runs the bounded cases advertised by `asterion describe`. Confirm the
displayed operation count before proceeding. Output must stay under the chosen
private output root and public results must contain references and aggregate
status rather than prompts, answers, credentials, or private paths.

### Complete: bounded behavior plus installed closure

```bash
make asterion-verify-complete
```

Complete composes preflight, bounded basic cases, and provider-free acceptance.
It is not a full benchmark and must still report `Full dataset ran: no`.

### Direct functional probes

Use a small local corpus and finite turn limit:

```bash
uv run asterion-dci system-prompt --help
uv run asterion-dci run \
  --cwd "$ASTERION_DCI_RESOURCE_ROOT/corpus/wiki_corpus" \
  --max-turns 6 \
  "Answer using only the local corpus."
uv run asterion-dci resume --help
uv run asterion-dci evaluate --help
```

For generic application assembly:

```bash
uv run asterion run \
  --provider dci-agent-lite \
  --application dci.research-capability@1.0.0 \
  --runtime pi.reference \
  --run-id validation-example \
  --input "Research the local corpus."
```

## Benchmark and launcher verification

All fourteen launchers compute their own project root. Data and corpus defaults
come from `ASTERION_DCI_RESOURCE_ROOT`, falling back to the project root. Use an
explicit small limit for a bounded probe:

```bash
make check-resources-benchmark
# explicitly fetch/convert supported upstreams; unavailable resources remain failures
make setup-resources-benchmark
```

```bash
ASTERION_DCI_RESOURCE_ROOT=/absolute/path/to/resources \
  bash scripts/qa/run_hotpotqa_dev_sample50.sh --limit 1
ASTERION_DCI_RESOURCE_ROOT=/absolute/path/to/resources \
  bash scripts/bright/run_bio.sh --limit 1
ASTERION_DCI_RESOURCE_ROOT=/absolute/path/to/resources \
  bash scripts/beir/benchmark_arguana.sh --limit 1
ASTERION_DCI_RESOURCE_ROOT=/absolute/path/to/resources \
  bash scripts/bcplus_eval/run_bcplus_eval_openai.sh level3 high --limit 1
```

Before any real probe, validate syntax and path resolution without a provider:

```bash
find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
uv run python -m unittest -v tests.test_standalone_launchers
```

The profile registry covers BC+, six QA datasets, four BRIGHT datasets, and two
BEIR datasets. `benchmark` supports finite limits, concurrency, exact reuse,
Judge cache identity, QA/IR modes, analysis, figures, and body-free exports.
Full-dataset execution is **Not rerun** and requires separate authorization.

## Artifacts and pass criteria

A successful durable run retains private question, event, conversation, state,
provenance, and evaluation artifacts under an operator-selected output root.
Public CLI/application results expose only safe identities, counts, digests,
status, and artifact references.

Pass criteria:

1. Every command exits zero inside its declared boundary.
2. Acceptance reports zero provider operations and no full dataset.
3. Source and isolated-wheel acceptance report the same installed closure.
4. Bounded cases use finite turns/rows and the announced operation count.
5. Resume and Judge reuse validate exact identities before reusing artifacts.
6. Logs and public reports contain no credential, prompt, answer, or private
   path body.
7. Missing Pi, data, or credentials fails before provider construction.

## Mixed-repository integration history

The parent DCI-Agent-Lite workspace retains the original DCI baseline and its
cross-product verifier. `tools/verify_asterion_dci_product.py` is **mixed-repository only**
and is intentionally absent here. Its historical
mixed-repository result covered `538/538` delegated selectors, `12/12` launcher
pairs, product rows, extra batch selectors, and retained bounded evidence.

That history supports migration confidence but is not a current standalone
acceptance criterion. A promoted repository should run package-owned acceptance
and its own temporary-copy promotion gate instead of reconstructing the parent
workspace.

## Troubleshooting without weakening evidence

- If acceptance searches outside this root, treat it as a packaging defect; do
  not point it at a parent verifier.
- If a launcher cannot find data, set `ASTERION_DCI_RESOURCE_ROOT`; do not copy
  corpora or datasets into the wheel.
- If Pi is missing or at the wrong revision, repair `DCI_PI_DIR`; do not edit or
  vendor the external checkout as part of Asterion verification.
- If Judge configuration changes, expect evaluation cache invalidation.
- If an isolated wheel differs from source acceptance, inspect packaged
  resources and ignore rules before changing expected counts.
- Never convert a skipped provider case into PASS or use an old public report as
  proof of a new execution.
