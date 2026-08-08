# Development execution mode

## Purpose

Remove outer authorization-file friction during local DCI and Pathlight development while retaining bounded execution, private evidence, and operator-owned provider configuration.

## Modes

- Development is the default. Coordinator commands do not require or create an outer authorization file.
- Production is enabled only by `ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION=1`. In this mode the existing exact authorization-file checks remain mandatory.

## Scope

The mode applies to Pathlight coverage experiment commands, including recovery preparation, execution, status, and reconciliation. It does not alter the generic benchmark subsystem, capability manifests, source locks, runtime protocol, controlled executor, or provider configuration.

## Execution invariants

- Every invocation remains bound to its exact plan, source lock, registry, case limit, and evidence root.
- Per-task limits, sequential execution, terminal receipts, native evidence sealing, redaction, and infrastructure-failure stopping remain active.
- In production mode an authorization file is required and must bind the plan and operator root exactly.
- Development mode does not interpret a configuration cache or previous result as production authorization.

## Interface

In development mode, `--authorization-file` is optional and omitted commands use a synthetic, in-memory authorization identity derived from the exact plan and operator root. No synthetic authorization is written to disk.

In production mode, omission is rejected before provider loading. Existing authorization-file CLI invocations remain compatible.

## Verification

- Development execution succeeds without an authorization file and never writes one.
- Production execution rejects missing authorization before host/provider construction.
- Existing explicit authorization tests continue to pass in production mode.
- Provider-free full gates pass; no real model is called while changing this behavior.
