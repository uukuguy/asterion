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

Python 3.10 or newer and `uv` are required. Node.js 22.19.0 (22.x LTS) plus npm
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

## Prime Gateway managed control

Prime Gateway is an optional peer control provider for long-running,
strongly-controlled sessions. Prime owns the controller session; Asterion owns
the exact application portfolio, admission, execution, budgets, cancellation,
journal, and public evidence. Prime source remains external; the wheel contains
only Asterion's control manifest, exact artifact lock, and authenticated control
skill.

```bash
make prime-check ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent
make prime-verify-provider-free
```

The first command checks the pinned source and performs zero provider work. The
second launches the real gateway against a deterministic fake daemon and proves
ten process/fault scenarios with zero model-provider operations. External daemon
preflight and explicitly authorized bounded readiness are separate; promotion
never starts bounded provider work. See the
[Prime Gateway operator guide](docs/guides/prime-control-operator-guide.md) and
[Prime parity ledger](docs/status/PRIME-PARITY-LEDGER.md) for exact evidence
labels and the deferred native-kernel scope.

## Cost boundaries

- `acceptance`, `list`, `describe`, `make test`, and `make check` are
  provider-free.
- setup, checks, `doctor`, and `preflight` are provider-free and report zero
  Agent and zero Judge operations.
- `basic` performs bounded Agent/Judge work when correctly configured.
- `complete` includes the bounded provider-backed path plus acceptance.
- Full datasets, paper-score reproduction, and publication require separate
  governance. A passing bounded run is **Verified-bounded** only and does not
  make `paper_full_executable=false` true.

Authorization is explicit and host-owned; Asterion does not require a monetary
amount to authorize a benchmark. An optional amount may be supplied as private
DCI operator configuration, but it is never serialized into a manifest, plan,
or public result and never grants execution authority.

DCI exposes an immutable instance catalog over the generic benchmark
subsystem. List it and select an exact version:

The underlying exact suites remain `dci.github@1.0.0`,
`dci.paper-main@1.0.0`, and `dci.all@1.0.0`; product instances bind those
suites to an exact application, task selection, executor, and finite range.

```bash
uv run asterion-dci benchmark instances --json
uv run asterion-dci benchmark lock \
  --instance dci.local-fixture@1.0.0 \
  --output "$OPERATOR_SELECTED_SOURCE_LOCK"
uv run asterion-dci benchmark plan \
  --instance dci.local-fixture@1.0.0 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK"
```

Listing, locking, and planning create no evidence, load no capability
implementation provider, perform no Agent/Judge work, and run no dataset. The
default range is one case per task. `--all-cases` only resolves the finite
catalog range; it is not authority to execute that range.

The product-owned installed host runs only after explicit authorization, exact
source selection, and a private absolute evidence root:

```bash
uv run asterion-dci benchmark run \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK" \
  --evidence-root "$OPERATOR_SELECTED_PRIVATE_EVIDENCE_ROOT" \
  --execute
```

Resume additionally requires the returned compatible run ID and the same
instance, range, lock, and evidence root. `dci.local-fixture@1.0.0` is
provider-free. Real instances use external data, model/network access, and an
independent Judge; the default bounded range controls their cost. No credential,
path, cached configuration, prior plan, or evidence grants execution authority.
Full datasets and paper reproduction remain separately governed.

See [the DCI operator guide](docs/OPERATOR-GUIDE.md) and
[instance backlog](docs/status/DCI-BENCHMARK-INSTANCES.md).

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
Long-running agent development starts with the
[Agent Control Protocol](docs/architecture/AGENT-CONTROL-PROTOCOL.md); the
[Prime parity ledger](docs/status/PRIME-PARITY-LEDGER.md) keeps foundation,
Prime-managed and native-kernel claims distinct.

## Promotion

Before making this directory the root of a Git repository, run:

```bash
make check
ASTERION_PROMOTION_NPM_CACHE="$(npm config get cache)" make promotion-check
```

`promotion-check` copies the standalone tree into a temporary directory and
re-runs the provider-free repository gates there. Its npm dependencies require
an absolute, pre-populated, operator-owned npm cache supplied through
`ASTERION_PROMOTION_NPM_CACHE`; the cache is an external tool resource, not
packaged evidence. A cache miss fails and does not access the network. It does
not create a remote, publish a package, or run a provider.

## Mixed-repository integration parity

The historical `538/538` delegated-selector matrix is a **mixed-repository only**
integration gate maintained by DCI-Agent-Lite. It compares the original DCI
baseline with Asterion and is not a current standalone acceptance result. The
standalone package deliberately does not ship that baseline, its governance
ledger, retained private evidence, or its integration verifier.
