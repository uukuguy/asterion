# Prime Restricted-Worker Acceptance Design

## Decision

All seven Prime capability products require an injected restricted-worker
lifecycle before they may issue `bounded-sandboxed` evidence. Trusted-local
compatibility and model runs remain useful operational evidence, but cannot be
promoted to formal acceptance.

## Closed scenario roles

The sole accepted scenario-to-role mapping is:

| Scenario | Worker role |
| --- | --- |
| `prime.ipython-coding/v1` | `prime.ipython-coding` |
| `prime.programmatic-long-context/v1` | `prime.programmatic-long-context` |
| `prime.recursive-workflow/v1` | `prime.recursive-workflow` |
| `prime.long-session-continuity/v1` | `prime.long-session-continuity` |
| `prime.bounded-autonomy/v1` | `prime.bounded-autonomy` |
| `prime.continual-improvement/v1` | `prime.continual-improvement` |
| `prime.arc-agi-3/v1` | `prime.arc-agi-3` |

There are no aliases, defaults, role ranges, or runtime-selected launch
commands. Operator code owns each role's launcher, seccomp policy, image, and
platform descriptor.

## Restricted-worker lifecycle

The domain-neutral worker service binds one immutable identity across request,
lease, attestation, execution, and cleanup:

```text
role_id + run_id + challenge_digest + workload_digest
        + image_digest + finite resource limits
                          ↓
                      worker lease
                          ↓
         isolation attestation + terminal execution receipt
                          ↓
                   verified destruction receipt
```

`RestrictedWorkerRequest`, `RestrictedWorkerLease`,
`RestrictedWorkerAttestation`, and `RestrictedWorkerCleanupReceipt` carry the
role and workload digest. A new `RestrictedWorkerExecutionReceipt` adds an
exact `result_digest` and terminal `completed` state. The injected service,
not application code, derives `result_digest` from canonical bytes returned by
the worker channel. All identities, image, limits, isolation facts, terminal
state, and cleanup must match exactly.

## Prime admission and evidence issuance

`verify_prime_worker_boundary()` receives a capability scenario ID and rejects
any non-matching role or lifecycle substitution. Its guarded public receipt
retains scenario, role, worker/run/challenge/workload/result digests, image,
and PASS status only.

Every bounded product observation retains a canonical source receipt digest.
Its verifier requires a matching `PrimeWorkerBoundaryReceipt` with the exact
scenario and result digest before issuing `PrimeEvidenceLevel.BOUNDED_SANDBOXED`.
The central evidence issuer rejects bounded-sandboxed evidence without this
gate. Provider-free receipts remain provider-free and cannot cross this
boundary.

## Delivery scope

1. Extend domain-neutral lifecycle values and receipt verification; add
   substitution, premature execution, immutability, and redaction tests.
2. Add closed Prime scenario-role mapping and guarded worker-bound evidence
   issuance; migrate Product 1 gate tests.
3. Change Products 5 and 6 receipt reducers so trusted-local reports can be
   inspected but cannot issue bounded-sandboxed PASS.
4. Keep the current Docker implementation Product-1-only. Products 2–7 report
   unavailable/External-limited until a role-specific launcher returns an
   exact execution receipt. No Docker image, platform, or model invocation is
   performed as part of this contract migration.

## Verification

- `unittest` matrices cover all seven mappings and every identity/digest
  substitution.
- Public representations contain no workload body, model output, credential,
  command, path, or raw worker response.
- Existing Product 1 Docker lifecycle tests continue to prove its fixed
  launcher; Products 5/6 trusted-local tests explicitly fail bounded issuance.
- `make test`, `make check`, and promotion checks remain provider-free.
