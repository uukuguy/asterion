# Recovered Session Checkpoint

> Updated: 2026-07-30.

## TL;DR

- Plan 4 closed in `935b129`; DCI is a capability-package implementation of
  Asterion's generic benchmark subsystem.
- Local and bounded Bamboogle instances now have formal installed execution
  hosts with explicit authorization, private evidence, cancellation, and resume.
- The installed-wheel local closure and complete DCI instance backlog are
  finished. The first real Bamboogle instance is `Verified-bounded`.

## Durable baseline

- `dci@1.0.0` owns seven capabilities, three suites, fifteen task bindings,
  implementation code, resources, and its provider.
- Built-in, installed-distribution, and local-directory source forms passed
  external-first equivalence and promotion checks.
- `asterion-dci` wires its product-owned host only after explicit execution
  arguments and authority; metadata-only commands remain provider-free.
- The real Bamboogle path binds `asterion-safe/pi` to the existing Agent/Judge
  engine. Main-workspace run `run-48217ad3214649dea9ff7e06c23d1625`
  completed one correct case; exact resume took zero seconds and added no
  evidence.
- Integrated `main` passes `make check` and `make promotion-check`. The
  completed capability-protocol worktree and branch no longer exist.

## Immediate next action

Select the next exact instance from `DCI-BENCHMARK-INSTANCES.md` and implement
it through the same generic benchmark host. Keep each real verification
separately authorized and finitely bounded. Do not execute the 50-case
Bamboogle plan without new authority.

## Ruled-out paths

- Do not put credentials, paths, provider configuration, prompts, or mutable
  state into portable package manifests.
- Do not grant execution merely because configuration, data, a source lock, or
  prior evidence exists.
- Do not add a DCI task loop or runner outside the generic benchmark subsystem.
- Do not claim a fixture run reproduces a paper or full dataset.
