# Prime P5 Bounded Autonomy Design

## Decision

`prime.bounded-autonomy/v1` reproduces one fixed offline IPython diagnostic
repair loop. A root works a fixed fixture under fixed turn, usage, time, and
cost projections. One deterministic quality gate may fail once; its redacted
failure digest becomes the sole feedback. The root may make one bounded repair,
then the same gate runs only if the workspace digest changed. A valid terminal
and a passing second gate are both required.

## Closed Contract

The workload owns fixture, root task, model/oracle/schema identities, IPython
only action surface, action/usage/deadline/cost ceilings, one feedback event,
and at most two quality-gate invocations. Callers supply no prompt, code,
workspace path, gate command, model, budget, environment, credential, or retry
policy. The gate is host-owned; it is not a model tool.

## Required Trace

1. root IPython work produces a first workspace digest and nonterminal gate;
2. the deterministic gate reports one redacted failure digest;
3. root performs bounded repair, producing a distinct workspace digest;
4. the gate executes once on that new digest and passes;
5. root reaches the fixed terminal/oracle, then worker/session are disposed.

Repeated gate execution on an unchanged digest, a second feedback loop,
unchanged repair workspace, terminal before passing gate, non-IPython action,
or exceeded ceiling fails closed.

## Evidence

Provider-free fakes validate ordering, digest de-duplication, budget truth,
redaction, and cleanup only. Bounded evidence requires an authorized real
Prime/IPython observation, exact worker boundary, gate attestation, quiescent
broker, and destroyed worker. No Docker, model, network, or benchmark run is
implied by local tests.
