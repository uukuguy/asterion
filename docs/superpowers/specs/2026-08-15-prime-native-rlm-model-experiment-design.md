# Prime Native RLM Bounded Model Experiment Design

> Parent: `docs/superpowers/specs/2026-08-11-asterion-prime-rlm-messaging-design.md`.
>
> Scope: one operator-authorized native Prime RLM probe, not general RLM
> execution or a claim of full Prime parity.

## Goal

Collect one auditable real-model observation of Prime's native `rlm.run`
path: native child creation, one family message delivery, child teardown, and
one terminal outcome. The experiment must enter the existing daemon-host shim
and `RlmChildService` boundary before Prime's native child effect.

The operator has approved a total cost ceiling of 500,000 micros ($0.50) and a
600,000 ms wall-clock deadline. The provider/model configuration stays in the
operator-owned `.env`; it is neither read into a manifest nor copied into an
authorization or public record.

## Approaches considered

1. **Chosen — closed, single-run experiment host.** A private host validates
   the existing bounded RLM authorization, consumes a single run reservation,
   and starts one pinned derived Prime daemon. It invokes the native kernel
   path through the installed daemon shim and collects only safe evidence.
2. **Rejected — call Prime's private kernel directly.** This bypasses the
   Asterion admission and receipt boundary, so it cannot substantiate an
   Asterion capability package.
3. **Rejected — synthesize model responses.** This retains provider-free test
   coverage but cannot demonstrate the native `rlm.run` child/message path.

## Authority and private configuration

The experiment consumes one `asterion.prime-bounded-authorization/v1`
document only after `load_bounded_rlm_authority` accepts it. In addition to
the generic requirements, the envelope must provide:

- `rlm.child.spawn`, `rlm.child.message`, and `rlm.child.delete`;
- recursion depth exactly one and concurrent children exactly one;
- a positive, unexpired 500,000-micros-or-lower cost limit; and
- finite positive controller, application, child, and aggregate token limits
  plus a 600,000-ms-or-lower action deadline.

The command line independently supplies `--max-cost-micros 500000`; a lower
operator ceiling is valid. The authority contains no model name, credential,
prompt, provider endpoint, filesystem path, or mutable run state.

A private operator-owned run configuration, injected after authorization
preflight, identifies the model and reads the necessary environment values.
The host validates that the selected model is nonempty and derives a private
selector digest. It never prints the model name or environment value. The
effective private configuration digest, source lock, authority ID/revision,
and one-time run reservation are bound together in a mode-0600 evidence root.
Neither a `.env` file nor a previous receipt grants authority.

## Runtime flow

```text
operator authority + private run configuration
  -> source/shim lock and bounded-RLM authorization preflight
  -> reserve one 500,000-micros / 600,000-ms experiment
  -> start one verified derived Prime daemon and authenticated host bridge
  -> root session invokes the native rlm.run probe
  -> shim admits child spawn, message, terminal, and delete transitions
  -> bounded host accounts safe usage and enforces cancellation
  -> private receipt and public-safe observation, then daemon reaped
```

The probe is deliberately minimal: one root session, one direct native child,
one in-family message, and one cleanup attempt. It must not ask the model to
perform arbitrary tool use, start more children, recurse, or continue after a
terminal result. The runner receives its resolved plan, injected services, and
cancellation signal; it does not discover credentials, select a model, retry,
persist general state, or authorize itself.

## Failure and cancellation

Every preflight mismatch fails before a daemon, kernel, or model operation:
invalid or expired authority, source/shim drift, budget/deadline excess,
missing private configuration, invalid model selector, or unavailable
operator-owned execution root.

During the run, budget exhaustion, deadline expiry, cancellation, a second
child request, recursion, protocol drift, unmatched message receipt, or
cleanup uncertainty fences the experiment. The host sends cancellation, waits
only within the remaining deadline, then terminates and reaps the exact daemon
and any descendants it owns. It records `uncertain` rather than asserting a
clean result if teardown cannot be proved.

The total ceiling is reserved before the first model effect and settled
monotonically from safe usage receipts. Unknown, missing, or over-ceiling
usage is a failed/uncertain run; it never permits another attempt under the
same reservation. No automatic retry is allowed.

## Evidence and promotion

Private evidence contains only the authority binding, source/shim lock,
configuration digest, event ordering, opaque identities, safe counters,
terminal classification, and teardown result. It must not contain prompts,
generated programs, message bodies, model/provider payloads, credentials,
transcript paths, or raw process output.

The public observation can state only that the named single-run boundary
passed or failed, its redacted reason class, safe usage totals, and opaque
event digests. It may promote exactly the bounded evidence assertions for
`rlm.generated-program`, `rlm.child-model`, and `rlm.recursion-depth` when
all causal receipts are complete. It must not promote `Verified-loop`, full
system parity, or a general native kernel capability.

## Verification

Provider-free tests prove the experiment planner/authority/configuration
binding, one-time reservation, redaction, deadline and budget rejection,
cancellation propagation, exact child/message ordering, and no retry. They
must read no credentials and make no model call.

The separately named real-model command runs only when the operator supplies
the authority, private run configuration, and explicit 500,000-micros ceiling.
It is excluded from `make test`, `make check`, `make promotion-check`, and all
metadata-only commands. A successful command must additionally prove the
owned daemon and descendants were reaped. Any incomplete receipt remains
`external-limited` or `uncertain`, never PASS.

## Scope boundary

This work creates a bounded experiment host and its evidence contract. It does
not expose a public daemon IPython command, move `.env` data into framework
configuration, change closed public protocols, enable unbounded Prime RLM,
or implement the Asterion-native long-running kernel.
