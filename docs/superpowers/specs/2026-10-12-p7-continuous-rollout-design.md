# P7 continuous-consequence rollout experiment

User-approved direction: learn game rules, unfold action consequences to a boundary, replay death counterexamples, and inspect candidate routes. This is a P7 experiment, not a common Prime strategy or a new safety certificate.

## Contract

A pure Python P7 helper supplies rollout(initial_state, actions, *, transition, settled, terminal, collision=None, max_ticks_per_action=128). State is finite JSON. The actor supplies its model callbacks; one input is sent only at the first tick of each action, then transition receives None until a stable, collision, terminal or unknown boundary. Actual environment actions are never dispatched. Model callbacks own domain semantics; helpers do not read hidden engine state. Input copies are immutable to callers. Full state participates in cycle detection. Exceptions, unknown classification, cycles and tick exhaustion report unknown with the reason and actual limit. Callback wall time remains bounded by the existing IPython execution host, not this tick count.

replay_cases evaluates the same model against declared cases and emits history-compatible predictions; replay_deaths assembles all current-run actual GAME_OVER transitions from read-only history and initializes each from its actual prior frame. It does not load previous runs. Missing or corrupt evidence cannot silently pass. References identify exactly which observations and actions were checked. The existing host publication comparison remains authoritative for historical predictions. A replay match is model evidence, never proof of future route safety.

evaluate_candidates unfolds each candidate input sequence. Model-predicted deaths are excluded from its returned model-relative candidate set; unknown candidates remain available. A failed/unknown supplied backtest downgrades candidate judgment. Returned results carry execution_authority=none. Collision is not death and terminates evaluation at a partial boundary; unexamined suffix stays explicit. No new compulsory publish/checkpoint/NOTES gate or mandatory plan field is introduced. Real action admission remains unchanged in this phase; future model-driven veto needs a reviewed, host-recomputed binding and remains separately unimplemented.

## Application integration

Embed the installed standalone helper source into the existing p7_research kernel module. Reuse its read-only evidence server; no new registered tool, RPC action route, runtime, framework-domain dependency or model session. Only the supervised research experiment entry appends the new usage guidance. Public prompts do not acquire new experimental policy. Existing output capacity and optional display remain unchanged; helpers do not print automatically or remove pixel fields.

## Verification

Small unittest coverage checks one-input/multiple-microstep death, stable/collision/goal boundaries, cycles/limits/unknown, input immutability, missing-suffix status, failed death replay and candidate filtering. Existing bridge and actual persistent kernel verify helper availability and current-run death collection. An offline Task46 L3 witness tests a partial observed-pixel model, derived from recorded observations and motion; no game internals, new engine episode, hidden state, model request or externally supplied route. Its result is deliberately local, not a learned-general-rule or live-efficacy claim. Verify installed wheel helper resources; run promotion-check once if changed package assumptions require it. Do not start another paid game trial.

## User refinement after the first live trial

The optional helper was not invoked during the stopped2/9 trial. Final user policy is uncertainty-sensitive use during actual gameplay, not a compulsory computation on every step: assess situation, mechanism and consequence certainty continuously; when certainty is insufficient, prioritize program rollout, express hypotheses/unknowns and update from real feedback. Stable verified fragments may be reused. This usage guidance stays at the research entry. No automatic admission gate or unvalidated common-prompt promotion is implemented. Offline L2 testing provides conditional-risk evidence, not autonomous learned-model efficacy; a new clean trial is user-authorized.
