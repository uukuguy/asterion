# Live Session Checkpoint

> Updated: 2026-09-05 05:05. **Session remains active — not a final handoff.**

## TL;DR

- The seven Prime product contracts and provider-free scaffolding exist, but
  none is a real LLM-driven end-to-end PASS yet.
- P1 Task 1 closed the exact `prime-agent@1.0.0` / IPython-only package and
  inert runtime path. Task 2 closed the private, fixed-limit bounded model
  session host factory and receipt lifecycle. Task 3's host-supervisor slice
  has an independently reviewed AST oracle and terminal evidence reducer.
- P1 Task 3 was redesigned at `4f32aea`: the model container is untrusted;
  only an application-host supervisor can emit completion/evidence.
- Final supervisor hardening at `1864d97` also latches cancellation at the
  broker observation point, before a discardable receipt exists.

## Current decision

- Do not trust container stdout, stderr, exit code, claimed frames, or a
  container-executed oracle. They can only cause rejection.
- The host binds a genuine bounded-model receipt and sent-cell digest to
  Docker-attested pre/post snapshots, confirmed cleanup, and a host-owned
  data-only AST oracle for the fixed `answer() == 42` fixture.
- The existing launcher/attach completion design is ruled out: same-container
  children can forge parent stdout via `/proc`, and importing model-owned
  Python cannot establish correctness.

## In-flight work

1. Extend Docker transport for daemon-ID/name,
   inspect projection, bounded workspace archive, pause, and cleanup proof.
2. Bind those daemon facts into the host supervisor, then integrate the actual
   Prime SDK broker and `verify --level basic`.
   A native-Docker qualification and real bounded broker call remain separate
   operator-authorized execution steps.

## Recovery commands

```bash
git status --short
git log --oneline -16
uv run python -m unittest -v tests.test_prime_ipython_host_supervisor
uv run ruff check src/asterion/applications/prime_agent/operator/ipython_host_supervisor.py tests/test_prime_ipython_host_supervisor.py
pyright src/asterion/applications/prime_agent/operator/ipython_host_supervisor.py tests/test_prime_ipython_host_supervisor.py
```
