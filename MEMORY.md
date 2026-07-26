# Project Collaboration Memory

> Collaboration meta-information only. Technical invariants belong in
> `AGENTS.md`/`CLAUDE.md`; architecture rationale belongs in
> `docs/status/DECISIONS.md`.

## Index

| Type | Status | Entry |
|---|---|---|
| feedback | ✅ verified-active | `handoff` means a fast, complete cross-session closeout |
| feedback | ✅ verified-active | Reconcile diagnostics with observed successful execution before concluding setup is missing |
| feedback | 🔴 superseded | The 2026-07-26 claim that Pi, `.env`, and basic resources were absent |

## ✅ Verified Active

### feedback — complete `handoff` contract

- When the user says `handoff`, close boundaries, persist conclusions and
  state, keep Git clean, correct and index memory, and ensure
  `project-state resume` can continue without conversational context.
- Keep the closeout concise and operational; do not turn routine handoff into
  a long audit.

### feedback — evidence reconciliation

- When a diagnostic conflicts with a confirmed successful execution, trace the
  configuration and path boundary before concluding that setup is missing.
- State verification boundaries explicitly: provider-free checks, readiness,
  bounded provider-backed execution, and full-paper reproduction are distinct.

## 🟠 Current Judgments

- None. Current technical status and next actions live in
  `docs/status/CURRENT-STATE.md` and `docs/status/RESUME-NEXT-SESSION.md`.

## 🔴 Superseded but Worth Remembering

### feedback — false missing-setup conclusion (2026-07-26)

- Superseded: Pi, `.env`, and basic resources were configured and usable.
- Cause of the wrong conclusion: `make doctor` resolved operator-relative
  paths against the installed package root.
- Durable lesson: successful examples are evidence that must be reconciled,
  not dismissed by a contradictory preflight result.
