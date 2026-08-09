---
name: asterion-control
description: Use the host-authorized Asterion portfolio, child sessions, checkpoints, goals, and budget from Prime's persistent Python kernel.
---

# Asterion Control

Import `asterion_control` in the persistent IPython kernel and call its async
functions directly. Inspect `await asterion_control.portfolio()` and
`await asterion_control.remaining_budget()` before proposing work.

Every application, child, checkpoint, or goal effect requires a stable
caller-chosen `idempotency_key` and an explicit finite `budget`. Reuse a key
only for a byte-for-byte equivalent logical request. Never generate a new key
to retry an uncertain call; query `await asterion_control.action_status(...)`
or report the uncertainty instead.

Application outputs contain only safe receipt and artifact metadata. They do
not contain provider payloads or raw host output. Do not read or render the
private socket, token, session environment, or opaque content references.

Example:

```python
targets = await asterion_control.portfolio()
budget = await asterion_control.remaining_budget()
result = await asterion_control.invoke_application(
    target=targets[0],
    input_text="the private application input",
    idempotency_key="research-step-1",
    budget={
        "controller_tokens": 0,
        "application_tokens": 1000,
        "child_tokens": 0,
        "aggregate_tokens": 1000,
        "cost_micros": 10000,
        "deadline_ms": 60000,
    },
)
```
