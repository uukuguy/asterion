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

## Trusted completion boundary

The model container is untrusted: its stdout, stderr, exit status, claimed
terminal frames, and Python imports cannot prove task success. A Prime
application host supervisor is the sole completion/evidence author. It binds
an actual bounded-model receipt and sent-cell digest to Docker-daemon-attested
pre/post snapshots of the fixed workspace file, force-removes the container
before verification, and runs a host-owned data-only AST oracle for the fixed
`answer() == 42` fixture. It never imports or executes model-owned Python.
Untrusted output can cause only rejection.

This replaces the rejected same-container launcher design: redirected child
stdout does not prevent `/proc/<parent>/fd/1` writes, and an oracle importing
model-owned code cannot trust its exit status. Docker transport must retain
daemon container ID separately from requested name and use a fixed inspect
projection. A default-off native Docker probe qualifies this isolation; only a
separately authorized real broker run may mint P1 PASS.

## Product sequencing

P2–P7 extend this exact spine: long context, recursive workflow, continuity,
bounded repair, continual improvement, and ARC-AGI-3.  Their existing receipt
and fixture tests remain regression scaffolding only; each becomes complete
only after its named real CLI scenario succeeds.
