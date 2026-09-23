# Prime P3/P5/P6 composed execution plan

## Goal

An installed Prime application selected through its provider must contain exactly one executable capability binding and produce its sealed receipt only after the injected host performed the named work. The public runner must not report success from a policy-only or placeholder runtime path.

## Invariants

- Policy remains declarative; the executable manifest is selected explicitly in each assembly.
- Each native package binds one implementation to that exact executable ref.
- Runtime `run` invokes the operator-owned host service and returns a normalized started/artifact/terminal stream; input, run ID, terminal classification, receipt identity and cancellation are checked before a capability artifact is returned.
- Fake-worker presets and public composition share the same workflow owner. No framework module imports Prime or DCI implementations, and no new composer/runner is created.
- P6 retains its single `HarnessCoordinator` and removes placeholder proposal/revision/receipt creation from the runtime binding; its real oracle verdict controls the sealed result.

## Sequence

1. Add RED provider→assembly→runner tests for P3, P5, P6. Inject recording hosts. Assert a real host call, one sealed artifact, and no successful artifact on refusal/cancellation/malformed result.
2. Complete P3 assembly/package/runtime and route the operator success preset through the composed runner. Keep limits as explicit bound refusal records; each should still verify the same host-service behavior.
3. Complete P5 with the same path and ensure propose/verify/repair actually execute before receipt.
4. Complete P6 with the same path using `CandidateStoreLoop`; delete fixed placeholder values and ensure oracle result and rollback are respected.
5. Reconcile package and assembly tests, run the focused application/operator tests, `make promotion-check`, and code review.

## Evidence limits

Deterministic fake-worker receipts prove this selected execution path and control boundary. They do not prove live model capability or broad benchmark success.
