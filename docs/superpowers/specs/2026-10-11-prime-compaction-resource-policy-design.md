# Prime application resource ceilings and runtime alarms

Date: 2026-10-11. Status: user-approved and independently reviewed; first two increments implemented and verified within the named boundary. Actual request certification remains separately unverified.

## User requirement and scope

Framework resource ceilings must have sufficiently generous defaults, allow application-level configuration, and report explicit runtime alarms when exceeded. Supervised research may use monitoring thresholds without an aggregate stop; operator authorization and unknown-effect fences remain binding.

The first implementation covers the inherited manual-compaction ceiling and the adjacent witness transport/material capacities. It also establishes the shared diagnostic record for resource ceilings. IPython output, context-memory/archive, callback and deadline controls must use this record when their existing limits trip; their independent capacity changes are subsequent scoped changes. This proposal does not certify all framework limits as repaired.

The [migration audit](../../reviews/2026-10-11-prime-p7-lossless-migration-audit.md#manual-summary-budget-root-cause-investigation) proves a separate request/accounting mismatch. Configuration alone cannot repair it. Native request interception and actual usage settlement are required before claiming request-bound budget certification. This work does not require ARC or paid model experiments.

## Recommended approach

Use immutable application-injected policy and the existing operator diagnostic channel. Do not increase constants in isolation: that leaves hidden transport limits and ambiguous failures. Do not remove every limit: explicit authorization, finite transport capacity and uncertain execution remain necessary boundaries.

Add `PrimeCompactionPolicy` in `agents/prime/compaction_budget.py`, exposed through an optional trailing field on `PrimeBackendSpec`:

| Field | Framework default | Meaning |
|---|---:|---|
| `max_total_tokens` | 262144 | Admission capacity for combined compaction input/output reservation; not a grant or summary output setting. |
| `max_frame_bytes` | 16777216 | Witness frame capacity, including full JSON envelope and duplicated request/context representations. |
| `max_material_bytes` | 65536 | Summarization template/material capacity. |

All values are positive exact JSON-safe integers. Frame capacity additionally cannot exceed the unsigned 32-bit framing maximum (2**32 - 1), the selected Node Buffer maximum or the host allocation/index representation limit; incompatible configuration is rejected before execution. Material capacity must be below the effective frame capacity, and the serialized material plus complete envelope must fit at admission. Measured whole-frame size is checked before allocation/write and during bounded reads. These defaults are finite initial engineering choices, not measured optima. The former 1 MiB frame and 8 KiB material constants are resource choices, not identity or schema invariants; replace them consistently on both sides rather than retaining hidden maxima. Keep digest equality, exact identities, closed shapes, sequence matching and safe integer validation unchanged. Existing configurable witness timeouts remain bounded by the operation's effective deadline.

Application/operator resolves configuration and injects it through the standard Prime entry. Core code reads no environment, credentials or provider profile. Add policy to both backend identity ceiling hashes so recovery cannot silently change capacity. Policy is not placed in compatibility manifests and does not change the four public closed protocols.

The standard entry infers `framework-default` when the policy is omitted and `application` when a policy is explicitly supplied, including an explicit policy with default values. An explicit validated source override remains available to operator integration; applications need not supply a separate origin flag merely to configure a capacity.

Delete generic fixed per-branch input/output and monetary policy constants. Quote inputs use supplied branch bounds; total is checked against policy. Cost uses injected `ModelPrice`, command reservation and remaining authority. Effective admission requires quote <= policy, quote <= command reservation, and reservation <= remaining session/parent authority. A larger default never increases authority.

## P1 compatibility and authority

Keep the existing small verification's total 64000-token /500000-micro-unit authority, callback/tool counts and 600-second deadline. Use one application-owned preset for its compaction reservation, proposed at 48000 tokens /125000 micro-units, rather than scattered 16000 constants. This leaves 16000 tokens for other stages when the full reservation is retained; exhaustion must report budget-limited, never grant more automatically. Release/runtime checks reference the same preset or settled receipt, not duplicated literals.

The framework default does not rewrite native Pi `reserveTokens`, model output limits or P7 supervised research controls. Native output limits must be observed from the actual request. P7's current non-durable supervised path is not the P1 manual 16000-token path.

## Explicit runtime alarms

Add immutable validated `LimitDiagnostic` through `services/diagnostics.py`, attached as an optional trailing field on existing `FailureDiagnostic`. Use fixed codes/enums and numeric values only:

- `limit_code`, `phase` (admission/execution/settlement), `action` (observed/rejected/stopped/recovery-required).
- `observed` (integer or unavailable), `limit` (nonnegative effective limit; remaining authority can be zero), `unit` (tokens/bytes/callbacks/milliseconds/cost-micros).
- `measurement` (exact/conservative-bound/estimate/unavailable), `config_source` (framework-default/application/operator/authority).

No prompts, output, raw provider errors, credentials or private paths enter this record. Preserve existing subject digests and correlation IDs. Report the binding limit: a 16000-token command must not be misreported as a 262144-token framework failure. Operator maps stable codes to visible configuration names and emits a concise alarm containing resource, measured/requested amount, effective limit and outcome. Persist the safe alarm alongside existing run evidence. No new notification service is needed.

Hard-cap violation emits an alarm and rejects/stops; explicitly configured soft monitoring thresholds only alarm. Estimated usage is labelled estimate. A provider result that exceeds the approved bound alarms and blocks subsequent work; it cannot undo expenditure already incurred. If outcome/cost remains uncertain, preserve reservation and require recovery. Sink failure cannot permit a rejected operation or replace its original reason. With no sink, retain a specific safe reason in the existing receipt. Deduplicate per operation and limit, not across separate operations.

Use existing receipt reason codes such as `compaction-token-limit`, `compaction-cost-limit`, `compaction-callback-limit`, `compaction-deadline`, `compaction-input-bound-unavailable` and `witness-frame-limit`. Preserve approve/reject channel semantics. Replace the current catch-all admission collapse with typed safe refusal metadata; malformed proposals remain fail-closed and distinct from resource exhaustion.

## Actual request and accounting dependency

Zero-provider feasibility verified the supported native seam: capture the configured provider's `streamSimple`, register a same-provider/API wrapper through Pi's public extension API, and forward original auth/model/options. Scope the wrapper to compaction and authorize at the actual adapter `onPayload` boundary before transmission. Preserve native compaction and summarization templates. Do not construct Pi in applications, copy the native summarizer or silently replace another wrapper.

Bind approval to actual system/messages/options and effective output limit, including sampling overrides. Capture per-branch terminal usage and distinguish reservation-charged from measured usage. Failed later branches or transport with uncertain usage retain reservation; retries require accounted authorization. Unsupported effective output caps or unavailable reliable input bounds must produce explicit capability/refusal diagnostics in strict mode. `UTF-8 bytes/4` remains an estimate and cannot certify a hard input ceiling. Supervised monitoring must display this uncertainty instead of claiming enforcement.

The feasibility probe is evidence for the interception seam, not final proof of arbitrary-provider token accounting. Provider-specific input-bound support requires its own named evidence before strict certification is enabled. Existing non-certified paths retain that status rather than being promoted by larger defaults.

## Implementation and verification boundary

Implement in three reviewable increments: policy/capacity plumbing; safe runtime alarms and operator presentation; actual native request authorization and settlement. Each increment reports its own verified boundary. The third must not be declared complete merely because the first two pass.

Focused checks cover default/override, old positional construction, policy identity mismatch on resume, unequal branch allocations, exact cost rounding, insufficient authority, frame/material boundary rejection on Python and TS, safe reason preservation, sink failure, soft/hard behavior and sentinel redaction. Zero-provider native probes cover rejection before transport, matching actual payload caps, successful branch usage, failure after approval and wrapper cleanup/conflicts. No synthetic usage is presented as paid model usage.

Rebuild all shipped Prime extension resources, run TypeScript extension tests, relevant Python tests and `make promotion-check`. Use a fresh-wheel zero-provider native witness run to prove configuration and alarms cross the packaged boundary. Do not start another BP35/full-model run under this change. Publish remaining uncovered provider/input-accounting limitations with the evidence.

## Design review receipt

Astra independent review identified the existing unsigned 32-bit frame header as a structural boundary; the proposal now explicitly preserves it and runtime buffer limits. The old1MiB resource choice is not that structural boundary. Remaining design approved within the stated first-two-increment scope; actual request certification remains conditional on separately verified provider bounds. Root native wrapper feasibility rerun passed with zero real network attempts and synthetic usage only.

Implementation receipt:739f2caf/cc4e834a/cf91607d/9964fb7f, fixture-only58856eba; independent review APPROVE, final promotion25/provider0 and installed-wheel native capacity/refusal proof PASS. Actual-request bound and usage settlement certification remains separate.
