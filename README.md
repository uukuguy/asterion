# Asterion

Asterion is a composable, multi-runtime agent application framework. This
repository contains the Python framework, built-in controlled-code and DCI
application providers, schemas, examples, launchers, TypeScript runtime
components, and a Rust controlled executor.

## Installation

Install the locked development environment from the repository root:

```bash
uv sync --frozen
```

Python 3.10 or newer and `uv` are required. Node.js and Rust are needed only for
their corresponding cross-language checks.

## Discovery and installed acceptance

These commands inspect the installed package and make no provider request:

```bash
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
```

`acceptance` verifies package-owned closure: providers, applications,
assemblies, capability manifests, context profiles, benchmark identities, and
paper scopes. It does not contact an Agent or Judge and does not run a dataset.

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

`ASTERION_DCI_RESOURCE_ROOT` is the parent of external `corpus/` and `data/`
trees. `make setup-resources-basic` prepares only `corpus/wiki_corpus` and
`corpus/bc_plus_docs`. `make setup-resources-benchmark` handles available
declared sources and reports every unavailable/gated launcher path with its
expected upstream; it never substitutes another corpus. Use the corresponding
`check-resources-*` targets for read-only checks.

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
  governance, an explicit invocation, and a finite budget.

Use `make help` to see the same boundary beside every command group.

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
