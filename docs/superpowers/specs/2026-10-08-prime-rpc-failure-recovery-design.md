# Prime RPC failure diagnosis and bounded recovery

User requirement: recurring Pi RPC failures must be handled by infrastructure, without outside guesswork or blind full-game restarts. This is a generic runtime mechanism with P7-owned effects/budget adaptation. External requests can still fail; the contract is diagnosis, safe bounded recovery where evidence permits, and truthful stopping elsewhere.

## Failure evidence

Before compact projection, validate and capture only bounded failure fields through an explicitly injected private sink. Runtime does not read credentials, paths or environment configuration. Operator owns mode0600 storage, 8KiB per event and64KiB total, with truthful truncation. Normal prompts/messages/tool payloads/headers are not captured. Sink failure must not change request execution, native retries or cancellation.

Use immutable typed failure metadata and a fixed public exception string. Preserve exact request/session/lifecycle identity, acknowledgment and settlement, stop reason, actual structured status/closed-set code if available, native retry lifecycle and private diagnostic reference. Unknown status stays unknown; do not invent HTTP status from arbitrary body text. Public summaries remain body-free. Successful native retry must not contaminate the terminal outcome with stale failure.

## Recovery

Pi native retry remains the first owner. A host may enable a single extra same-process continuation across the entire run, never once per round. Require exact final failure receipt, completed matching settlement, healthy same child/session, no pending or uncertain generic tool effects, host effect guard confirming committed known outcomes, remaining original deadline and all existing limits. Explicit permanent rejection, protocol corruption, unacknowledged/unsettled transport failure, cancellation or unknown action effects must fence and stop.

A complete native retry-exhausted witness is evidence of Pi's recovery attempt, not proof the final provider condition is transient. Recovery eligibility is conservative and named accordingly. Fixed backoff consumes the original deadline. Preserve Pi history, Python kernel, game broker, journal, counters and NOTES. Send a new neutral current-state continuation; never replay an old tool plan, cell or original prompt. No automatic process rebuild or budget renewal. Existing backend entry points remain fenced unless explicitly wired to the same contract.

## Scope and validation

Implement in isolated worktree while live trial production remains frozen. Generic pi_rpc/services diagnostics own typed failures and exact settlement authorization; Prime session/execution own once-per-run recovery; P7 injects private storage and journal/effect/budget guards. No new game-specific reasoning instructions or schema/tool-registration architecture.

Focused provider-free tests cover: compaction modes, private-only error capture and sentinel redaction, sink failure and limits, native retry success, permanent refusal, exact one recovery with unchanged budget/counters, no action replay after committed effects, pending/unknown effects, stale receipt, missing settlement, cancellation and exhausted budget. Independent contract/code review precedes integration. Live recovery ability remains unverified until an authorized deployment exercises it.
