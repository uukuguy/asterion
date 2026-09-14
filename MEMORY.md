# Project Collaboration Memory

> Collaboration meta-information only. Technical invariants belong in
> `AGENTS.md`/`CLAUDE.md`; architecture rationale belongs in
> `docs/status/DECISIONS.md`.

## Index

| Type | Status | Entry |
|---|---|---|
| feedback | ✅ verified-active | `handoff` means a fast, complete cross-session closeout |
| feedback | ✅ verified-active | Reconcile diagnostics with observed successful execution before concluding setup is missing |
| feedback | ✅ verified-active | Preserve approved architecture across sessions; P7 is the native base for rebuilding P1-P6 |
| feedback | ✅ verified-active | Research intensity — review changed code, not the whole gate |
| feedback | ✅ verified-active | Judge a subagent by whether the work is done, not by whether it has reported |
| feedback | ✅ verified-active | Search `PATH` and the real environment before declaring a resource absent |
| feedback | ✅ verified-active | Report a narrow defect as narrow; do not inflate it into an architecture decision |
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

### feedback — do not rediscover or reverse approved native direction

- P7 completed the Prime Agent to Asterion Prime native transition. P1-P6 must
  be rebuilt on that implementation, not repaired on Prime Agent wrappers.
- Treat Prime Agent source/SDK as external historical evidence only. Do not
  relabel a source-coupled execution path as native because Asterion owns its
  outer orchestration.
- For research development, emphasize review of changed implementation and
  focused boundary assertions; avoid release-scale test suites unless asked.

### feedback — research intensity, not production engineering

- Review changed code plus the key boundary assertions, and run **small
  targeted** regressions. Do not re-run full combination gates or full suites,
  and do not harden tooling past the point where it catches the real violations.
- Given 2026-09-14 after a static detachment gate absorbed five defect rounds
  and two review passes — several hours — while no application had been rebuilt.
  The deliverable is the rebuilt application; the guard around it is support
  work. AGENTS.md already said this; the failure was inverting it.

### feedback — search the environment before declaring something absent

- Before reporting that a resource does not exist, search where it would
  actually live: `PATH`, package-manager global roots, the user's own install
  locations. One `ls` of the obvious directory is not a search.
- Given 2026-09-14, after concluding "the only Pi on this machine is `./pi/`"
  from a single directory listing — and pausing the work on that conclusion.
  The user's reply was "没有 Pi 吗？你看看 PATH 中有没有？不知道找找吗？".
  `/opt/homebrew/bin/pi` was on `PATH` all along, symlinked into the npm global
  root, and it was the genuinely detached artifact the phase needed.
- **Why:** a wrong absence claim is not a neutral gap. It stops work, or pushes
  the session toward a workaround for a constraint that never existed.

### feedback — report a narrow defect as narrow

- When the defect is one line in one file, say so, fix it, and stop. Do not
  present it as an architectural choice with trade-offs, and do not open a
  decision point that the evidence has already closed.
- Given 2026-09-15, after framing "`create_provider()` publishes an unfinished
  P1" as a "closure coupling" needing a resolver-semantics decision. The user's
  reply was "什么乱七八糟的。这个绑在一起的 provider 是你设计的吧". The real fix
  was removing one published entry.
- **Why:** inflating a small defect wastes the user's attention, delays the
  fix, and obscures who caused what. Name the actual scope, then act.

### feedback — judge a subagent by the work, not the report

- Check repository state periodically instead of waiting for a final report. If
  the goal is met and the tree is green, stop the agent and commit rather than
  waiting for it to narrate.
- Given 2026-09-14 after an agent finished its work with the gate already at
  zero and then spent hours before committing. A second agent was stopped at the
  same point (goal met, 70 tests green) and its work committed directly.

## 🟠 Current Judgments

- Phase 1 (legacy Prime Agent detachment) is complete and the application layer
  is free of Pi references; the remaining work is construction, not removal.
  P1-P7 native implementations stand at 0 of 7 and are all unavailable by
  design. Current technical status and next actions live in
  `docs/status/CURRENT-STATE.md` and `docs/status/RESUME-NEXT-SESSION.md`.

## 🔴 Superseded but Worth Remembering

### feedback — false missing-setup conclusion (2026-07-26)

- Superseded: Pi, `.env`, and basic resources were configured and usable.
- Cause of the wrong conclusion: `make doctor` resolved operator-relative
  paths against the installed package root.
- Durable lesson: successful examples are evidence that must be reconciled,
  not dismissed by a contradictory preflight result.
