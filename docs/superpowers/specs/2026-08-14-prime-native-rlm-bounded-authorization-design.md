# Prime Native RLM Bounded Authorization Design

> Parent: `docs/superpowers/specs/2026-08-11-asterion-prime-rlm-messaging-design.md`.

## Goal

Prepare one auditable, non-executing authorization boundary for the future
native Prime RLM experiment. The boundary must reject incomplete, expired, or
over-broad authority before starting a Prime daemon, sidecar, kernel, or model
operation.

The experiment remains a separate operator action. This work does not enable
or invoke a model, and `PRIME_NATIVE_RLM_MAX_DEPTH` remains `0`.

## Decision

Reuse `asterion.prime-bounded-authorization/v1` and add a dedicated loader:
`load_bounded_rlm_authority`. It first applies the existing generic bounded
authority validation, then requires the native RLM capabilities that the
Prime-hosted `RlmChildService` enforces:

- `rlm.child.spawn`
- `rlm.child.message`
- `rlm.child.delete`

It additionally requires exactly one recursive level and one concurrently
active child. The existing finite positive token, cost, deadline, trusted-local
domain, expiry, and source/shim preflight constraints remain unchanged.

The generic bounded loader remains available for non-RLM Prime verification;
adding RLM permissions there would incorrectly broaden unrelated bounded
experiments.

## Interface and flow

```text
operator authority file
  -> load_bounded_rlm_authority(path, max_cost_micros)
  -> load_bounded_authority(...)
  -> exact RLM operation/depth/concurrency checks
  -> verified AuthorityEnvelope, or one redacted PrimeVerificationError
  -> later explicitly authorized native RLM runner
```

The loader returns the immutable `AuthorityEnvelope` only. It does not read
credentials, resolve a model, create a socket, start Prime, or alter runtime
configuration. A later runner must separately call source/shim preflight and
must retain the fixed native depth gate until its own finite experiment
authorization is present.

## Failure behavior

All invalid inputs return the existing public-safe error
`Prime bounded authorization is invalid or inconsistent`. Errors must not
render the authority path, its raw JSON, model configuration, credentials, or
any private values. The loader rejects missing RLM permissions, a depth other
than one, and a concurrency limit other than one.

## Tests

Unit tests will prove that:

1. a fully bounded authority containing the three RLM operations is accepted;
2. each missing RLM operation is rejected independently;
3. depth zero, depth above one, zero concurrency, and concurrency above one
   are rejected;
4. malformed and secret-bearing authority files remain redacted; and
5. the loader performs no subprocess, daemon, sidecar, kernel, credential, or
   model operation.

The focused verification command is:

```bash
uv run python -m unittest -v tests.test_verify_prime_loop
```

After implementation, `make check` remains the repository-wide gate.

## Scope boundary

This design intentionally does not create a public daemon command for IPython
execution. Prime's native `rlm.run` path must remain internal to the session
kernel; exposing an external substitute would bypass the native host binding
and invalidate parity evidence.
