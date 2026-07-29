# Asterion

Asterion is a composable, multi-runtime agent application framework. This
repository contains the Python framework, built-in controlled-code and DCI
application providers, schemas, examples, TypeScript runtime
components, and a Rust controlled executor.

## Installation

Install the locked development environment from the repository root:

```bash
uv sync --frozen
```

Python 3.10 or newer and `uv` are required. Node.js 22.19.0 or newer plus npm
are required for `make setup-pi`; Rust is needed only for its corresponding
cross-language checks.

## Discovery and installed acceptance

These commands inspect the installed package and make no provider request:

```bash
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
```

`acceptance` reports installed inventory and executable reachability
separately. The wheel packages six assembly resources; providers bind five,
all five compose against exact runtime manifests, and all five have complete
implementation bindings. The unbound
`applications/dci_agent_lite/assemblies/dci-local-research.json` resource is
reported as package-relative inventory, not as a product entry point. The
check also covers providers, capability manifests, context profiles, benchmark
identities, and paper scopes. It does not construct runtime clients, contact an
Agent or Judge, or run a dataset.

## External Pi and resources

From a fresh clone, prepare the locked Pi source and the two corpora used by
preflight/basic verification:

```bash
uv sync --frozen
make setup-pi
make setup-resources-basic
cp .env.template .env
# authenticate Pi and the independent Judge using operator-owned credentials
make doctor
```

`make setup` composes the first three provisioning commands. Setup may use
Git, npm, Hugging Face, disk, and network, but it performs zero Agent operations
and zero Judge operations and never runs a dataset.

Pi is an external checkout, never vendored into this repository. A global `pi`
executable is not the runtime authority: Asterion launches the checkout pinned
by `pi-revision.txt` at `DCI_PI_DIR` (default `./pi`). `DCI_PI_AGENT_DIR`
(default `~/.pi/agent`) selects separately managed Pi authentication. Setup
never reads, copies, creates, or prints authentication files.

Pi dependency installation uses `npm ci`, and the AI package compiles the
locked commit's checked-in model catalogs without refreshing them from moving
model APIs. If an earlier failed setup left a dirty checkout without a built
CLI, setup refuses to overwrite it: preserve or discard those changes
explicitly, or select another clean `DCI_PI_DIR`, then run `make setup-pi`
again.

`ASTERION_DCI_RESOURCE_ROOT` is the parent of external `corpus/` and `data/`
trees. `make setup-resources-basic` prepares only `corpus/wiki_corpus` and
`corpus/bc_plus_docs`. Benchmark paths come from private DCI operator
configuration; capability manifests contain no dataset or corpus paths.

Local corpus access means Asterion points Pi or Claude Code at operator-owned
files instead of a hosted retrieval service. It does not mean every relevant
document fragment stays on-device: selected corpus content can still be sent to
the configured Agent model provider during a run.

Keep Agent and Judge credentials in `.env`, exported environment variables, or
the selected Pi agent directory; never commit them. External `pi/`, `data/`,
`corpus/`, generated outputs, and private evidence remain outside the
distribution.

## Cost boundaries

- `acceptance`, `list`, `describe`, `make test`, and `make check` are
  provider-free.
- setup, checks, `doctor`, and `preflight` are provider-free and report zero
  Agent and zero Judge operations.
- `basic` performs bounded Agent/Judge work when correctly configured.
- `complete` includes the bounded provider-backed path plus acceptance.
- Full datasets, paper-score reproduction, and publication require separate
  governance. The bounded execution interface is **External-limited** and does
  not make `paper_full_executable=false` true.

Authorization is explicit and host-owned; Asterion does not require a monetary
amount to authorize a benchmark. An optional amount may be supplied as private
DCI operator configuration, but it is never serialized into a manifest, plan,
or public result and never grants execution authority.

DCI exposes three exact suites through the generic benchmark subsystem:
`dci.github@1.0.0` (12 tasks), `dci.paper-main@1.0.0` (13 tasks), and
`dci.all@1.0.0` (15 tasks). The application adapter fixes the application to
`dci.complete-application@1.0.0`. Planning is provider-free:

```bash
uv run asterion-dci benchmark plan --case-limit 1
```

Planning creates no evidence, loads no capability implementation provider,
performs no Agent/Judge work, and runs no dataset. `--case-limit 1` applies to
each task in suite order; it is not paper-score reproduction.

Execution and resume require an embedding operator host to supply explicit
authorization, exact source selection, implementations, executor, cancellation,
and private evidence services. The generic command shape is:

```bash
uv run asterion-dci benchmark run \
  --case-limit 1 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK" \
  --evidence-root "$OPERATOR_SELECTED_PRIVATE_EVIDENCE_ROOT" \
  --execute
```

The plain installed CLI deliberately has no execution authority. No credential,
path, existing output, cached evidence, or prior plan grants authority. A host
that authorizes execution writes immutable private evidence and exposes only
body-free public task/run results. Resume additionally requires the compatible
run ID. Full datasets and paper reproduction remain separately governed.

Use `make help` to see the same boundary beside every command group.

## Capability package sources

Built-in, installed-distribution, and explicit local-directory packages are
source forms of the same capability-package contract. A built-in registration
is not a privileged implementation layer. DCI is one package implementation of
the generic Asterion benchmark subsystem, and its built-in form exists only
after the same payload was proven through a clean external wheel using the
public SDK and conformance kit.

Source resolution has no hidden precedence. Multiple candidates for the same
exact package remain ambiguous even when their payload digests match; the host
must supply an exact source lock. Metadata discovery does not import provider
code, and only the selected installed extension is loaded. Installed extension
code is therefore part of the operator's trusted computing base after exact
selection, not trusted metadata during discovery.

Operator-owned credentials, provider configuration, datasets, corpus roots,
private environment, and evidence stay outside package manifests. Archive and
registry source forms are intentionally deferred until their trust,
verification, and lifecycle design is approved.

## Development

```bash
make test
make lint
make docs-check
make check
```

The [documentation hub](docs/README.md) links the framework architecture,
capability usage, complete DCI reference, and functional verification guide.

## Promotion

Before making this directory the root of a Git repository, run:

```bash
make check
make promotion-check
```

`promotion-check` copies the standalone tree into a temporary directory and
re-runs the provider-free repository gates there. It does not create a remote,
publish a package, or run a provider.

## Mixed-repository integration parity

The historical `538/538` delegated-selector matrix is a **mixed-repository only**
integration gate maintained by DCI-Agent-Lite. It compares the original DCI
baseline with Asterion and is not a current standalone acceptance result. The
standalone package deliberately does not ship that baseline, its governance
ledger, retained private evidence, or its integration verifier.
