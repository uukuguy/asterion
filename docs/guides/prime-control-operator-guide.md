# Prime Gateway operator guide

Prime Gateway is Asterion's first managed long-running control provider. It is
peer-selectable with other control providers; it is not a replacement for the
capability-package composer, application runner, or a future Asterion-native
long-running kernel. Prime owns its daemon session and controller loop, while
Asterion remains authoritative for portfolio selection, admission, execution,
budget settlement, cancellation, canonical journaling, and public evidence.

## What is implemented

The packaged Python host and TypeScript gateway implement create, attach,
detach, checkpoint, recovery, dynamic remaining-budget updates, exact-once
action settlement, application actions, one-level child sessions, and terminal
goal actions. The Asterion control skill talks to a private authenticated Unix
socket and can propose only the closed operation set admitted by the current
authority envelope.

The provider-free verified loop launches real gateway, fake Prime daemon, and
worker processes. Its ten stable scenarios cover applications, a child,
detach/attach, checkpoint recovery, gateway/supervisor/worker failure,
cancellation, budget rejection, and redaction. This proves the integration and
fault semantics without making a model-provider request.

## Verification levels

| Level | External work | Meaning |
|---|---:|---|
| `provider-free` | none | Real Asterion/gateway processes against deterministic fake Prime; ten scenarios and zero model-provider operations. |
| `preflight` | local Prime daemon only | Exact source lock, Node/dependency readiness, and daemon protocol handshake; zero model-provider operations. |
| `bounded` | separately authorized | Validates finite trusted-local authority and the cost ceiling, then requires an injected provider/run configuration. Without that operator-owned configuration it reports `External-limited` and starts no model work. |
| `restricted` | unavailable | Deferred until a restricted execution domain is injected and independently verified. The Rust controlled executor is not an OS sandbox. |

`Verified-loop` is reserved for both a passing provider-free gate and a
separately authorized bounded real-Prime run with complete causal evidence.
The current provider-free result alone is `Prime Gateway implemented`, not
native-kernel parity.

## Source setup

Prime source remains external. Asterion packages only its exact artifact lock,
control-plane manifest, and control skill. Check the selected source without
installing dependencies:

```bash
make prime-check ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent
```

Install the selected checkout's locked npm dependencies explicitly:

```bash
make prime-setup ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent
```

Both commands use a closed setup environment, expose no source path or command
stderr in their result, and perform zero model-provider operations. The source
must be a Git checkout at the exact clean commit and match every locked digest;
source exports without Git metadata are rejected before any command runs. The
pinned compatibility boundary is Node.js 22.8.0 through 22.x; a non-LTS odd
major is rejected before dependency installation. Setup revalidates the exact
Git root, commit, clean tracked/untracked state, and locked bytes after install
and again after build before reporting success.

Setup does not call Prime's root `npm run build`, because that upstream command
regenerates the model catalog from live external APIs. It runs a fixed offline
sequence for the TUI, AI, agent-core, and coding-agent workspaces; the AI step
compiles the pinned generated catalog without refreshing it. Do not inject a
persistent npm cache into setup: native `prebuild-install` cache entries are
URL-keyed and are not an Asterion execution authorization or integrity proof.

## Provider-free and preflight gates

Run the promotion-safe integration gate:

```bash
make prime-verify-provider-free
```

After setup, run the external daemon handshake without model work:

```bash
uv run python tools/verify_prime_loop.py \
  --level preflight \
  --source-root 3th-party/prime-agent
```

Missing source, dependencies, or daemon readiness is `External-limited`; it is
never promoted to PASS.

Preflight starts the built Prime bundle directly in foreground daemon mode,
waits for its private Unix socket, checks the normalized Gateway hello, and
terminates that exact child process. It does not use Prime's removed
`daemon start` command or the global `shutdown` command, so it cannot stop an
operator's unrelated Prime services.

## Bounded authority boundary

The bounded command requires an operator-owned authorization file and a
separate command-line cost ceiling:

```bash
make prime-verify-bounded \
  ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent \
  ASTERION_PRIME_AUTHORITY=/private/prime-authority.json \
  ASTERION_PRIME_MAX_COST_MICROS=10000
```

The authorization must be an
`asterion.prime-bounded-authorization/v1` document containing one exact
portfolio, sorted allowed operations, positive controller/application/child/
aggregate/cost limits, an unexpired trusted-local envelope, recursion depth at
most one, and exactly one concurrent child. Its cost limit cannot exceed the
separate command-line ceiling. Credentials, prompts, provider settings,
workspace paths, and mutable state do not belong in this file or any manifest.

The repository currently has no generic operator configuration capable of
selecting a real model/provider for this bounded experiment without leaking
product policy into framework code. Consequently the command validates source,
handshake, authority, and cost, then honestly reports `External-limited` until
that private run configuration is injected through an approved host boundary.
Promotion never invokes `bounded`.

The separately authorized native-RLM experiment is also default-off. It uses
one explicit $0.50 ceiling and private evidence root; it is never part of
`make test`, `make check`, or promotion:

```bash
make prime-verify-native-rlm-bounded \
  ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent \
  ASTERION_PRIME_AUTHORITY=/private/prime-rlm-authority.json \
  ASTERION_PRIME_EVIDENCE_ROOT=/private/prime-rlm-evidence
```

Until the native probe runner is installed, this command reports
`External-limited` after the exact preflight and authorization checks; it does
not invoke a model.

## Cost and risk comparison

The hosted gateway is the lower-cost path to long-horizon control because it
reuses Prime's mature session loop, but it adds a Node/Python process boundary,
an external source pin, daemon protocol drift risk, and two recovery ledgers.
The future native kernel would remove that integration dependency and permit
tighter Asterion scheduling/evidence semantics, but it would assume the larger
cost of controller policy, continuation quality, compaction, steering, and
long-run recovery. Keeping both providers peer-selectable lets Asterion gather
real bounded evidence before committing to that native investment.

Public events, journal records, Pathlight, stdout/stderr, and exception strings
must never contain prompts, credentials, private paths, raw provider payloads,
or application output. Any missing Pathlight observation is an evidence gap and
prevents a scenario from passing.
