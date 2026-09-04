# Prime P1 Real End-to-End Coding Design

## Outcome

`uv run asterion verify --provider prime-agent --level basic` performs one
fixed, bounded, model-driven coding task.  The model operates through exactly
one Prime SDK tool, `ipython`; a launcher-owned oracle observes initial failure
and final success.  This replaces fixture PASS as the P1 completion claim.

## Execution path

```text
CLI basic preset → prime.ipython-coding assembly → prime-agent package
→ prime.agent runtime → restricted worker → pinned Prime SDK/IPython
→ operator-owned bounded model session → real model responses
```

The generic framework remains domain-neutral.  Prime application integration
owns the provider adapter and is the only layer permitted to resolve the
operator `.env`; its credentials, prompts, provider payloads, source cells,
outputs, paths, and raw model responses never cross public boundaries.

## Required closure

1. Add `prime-agent@1.0.0` as an exact capability package with
   `prime.ipython-coding@1.0.0` and one implementation binding.
2. Register `prime.agent`, advertising only `prime.tool.ipython`, as a normal
   runtime adapter.
3. Add a narrow `model.bounded-session` host service with fixed P1 request,
   token, byte, cost, deadline, cancellation, and terminal-usage limits.
4. Replace deterministic P1 task solving with a pinned Prime SDK worker that
   multiplexes closed worker/model/terminal frames through host mediation.
5. Add the executable assembly and Prime verifier/product integration, with
   `preflight`, provider-free `acceptance`, one real `basic` run, and future
   monotonic `complete` expansion.

## P1 evidence

A bounded PASS requires the exact source, assembly, package, implementation,
image, workload, and oracle identities; nonzero bounded host-model operations;
only `ipython` tool calls; contiguous causal model/tool digests; initial oracle
failure followed by final success; mutation after a model-produced IPython
call; and worker/broker cleanup.  A fixture, fake broker, deterministic patch,
or manually issued cell cannot mint this receipt.

## Product sequencing

P2–P7 extend this exact spine: long context, recursive workflow, continuity,
bounded repair, continual improvement, and ARC-AGI-3.  Their existing receipt
and fixture tests remain regression scaffolding only; each becomes complete
only after its named real CLI scenario succeeds.
