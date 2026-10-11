# P7 passive resource observation repair

User authorized interrupt, analysis and correction of the supervised BP35 trial on2026-10-11. The trial remains stopped; this repair does not authorize a new trial.

The resource heartbeat calls broker.status(), which checks executable readiness. While an engine action is in flight, that check sees a nonterminal durable transaction and changes terminal_reason/processing_diagnostic. The action may then commit successfully, leaving a stale unknown-result diagnostic. A provider-free deterministic engine callback reproduces this mutation. The final trial summary contains this symptom ataction225; exact heartbeat attribution is supported, not stack-recorded.

Add an explicit passive broker accounting observation with only immutable scalar counters. ResearchMonitor reads it without calling execution admission or terminal-state validation. Counts may lag an in-flight action; sampling cannot grant authority, change transaction phase, change terminal reason or add/remove processing diagnostics. Existing status(), action admission, cancellation and genuinely unknown-result guards remain unchanged.

Rejected alternatives: calling private _status from telemetry hides the contract; relaxing _require_open weakens effect safety. Repeated prompt reminders and BP35-specific routes do not repair this observer fault.

Verify with a failing real in-flight transaction regression, committed and genuinely unresolved outcomes, finite/supervised counters, content-safe monitor checks, changed-code review and packaging. This fixes observer interference; it is not a demonstrated correction of model spatial reasoning or nine-level solving ability.
