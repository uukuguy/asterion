# Prime native-RLM experiment defaults

## Decision

The explicit `native-rlm-bounded` command together with
`--native-rlm-experiment` is the operator's consent for one bounded native-RLM
probe.  It must not require the operator to construct an internal authority
document or choose an evidence directory merely to run the supported default
experiment.

The command creates an in-memory, non-reusable `AuthorityEnvelope` with one
exact Prime Gateway portfolio and the closed operation set needed for the
probe.  Its limits are the already approved 500,000 micros and 600,000 ms,
one recursion level, and one child.  This envelope is never written to disk,
is not usable by `bounded`, and cannot confer authority to any other command.

`ASTERION_PRIME_EXPERIMENT_MODEL` remains the required private configuration;
the supported default is `deepseek-v4-flash`.  The selected credential is
forwarded only to the owned daemon and is redacted everywhere else.

## Defaults and overrides

The native command requires only `--source-root` and
`--native-rlm-experiment`.  It obtains the budget ceiling from the approved
default.  `--max-cost-micros` may lower, but never raise, that ceiling.

It creates a mode-0700 private run directory beneath an ignored local
`.asterion-private/prime-rlm/` root.  `--private-evidence-root` optionally
selects a pre-existing operator-owned root instead.  Public reports include a
receipt digest and status only, never the private directory path.

`--authority` remains an advanced override.  When supplied it is validated by
the existing bounded-authority loader and must be no broader than the default
experiment.  The generic `bounded` level remains unchanged and still requires
an operator-owned authority document.

## Rejected alternatives

1. Requiring an authorization JSON and an evidence path for every run: this
   exposes framework implementation details and is the current usability
   failure.
2. Persisting generated authorization for later reuse: this turns a one-shot
   command into hidden, durable execution authority.

## Safety and verification

Provider-free, preflight, `make test`, and `make check` retain zero
model-provider operations.  Missing model configuration or credentials,
invalid explicit overrides, or an unsafe private root fail closed without a
model request.  Tests prove default construction, lower-only budget override,
private-root creation and permissions, external authority override, redaction,
and the unchanged generic bounded gate.
