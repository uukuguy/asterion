# Project Collaboration Memory

> Collaboration meta-information only. Technical invariants belong in
> `AGENTS.md`/`CLAUDE.md`; architecture rationale belongs in
> `docs/status/DECISIONS.md`.

## Index

| Type | Status | Entry |
|---|---|---|
| feedback | ✅ verified-active | `handoff` means a fast, complete cross-session closeout |
| feedback | ✅ verified-active | P7 learning must be visible during play and evaluated through improving game understanding |
| feedback | ✅ verified-active | Reconcile diagnostics with observed successful execution before concluding setup is missing |
| feedback | ✅ verified-active | Preserve approved architecture across sessions; P7 is the native base for rebuilding P1-P6 |
| feedback | ✅ verified-active | Research intensity — review changed code, not the whole gate |
| feedback | ✅ verified-active | Judge a subagent by whether the work is done, not by whether it has reported |
| feedback | ✅ verified-active | Search `PATH` and the real environment before declaring a resource absent |
| feedback | ✅ verified-active | Report a narrow defect as narrow; do not inflate it into an architecture decision |
| feedback | ✅ verified-active | Delete a seam whose only purpose was the forbidden dependency; do not retarget it |
| feedback | ✅ verified-active | A classification is not a cause; recover the value before changing anything |
| feedback | ✅ verified-active | Take a contract's key set from its producer, not from a fixture |
| feedback | ✅ verified-active | A state-machine bug fix in one layer is not done — find every place that checks the same key set |
| feedback | ✅ verified-active | Verify the producer side independently before assigning blame (direct RPC probe over the same wire format) |
| project | ✅ verified-active | P7 temporarily initializes its own Pi; defer a shared Asterion Pi base until a later architecture discussion |
| feedback | ✅ verified-active | The "倒数第 2-3 个 hook 位置挂几十秒" pattern points at the last synchronous hook, not the first slow one |
| feedback | ✅ verified-active | Global hook audit: keep only hooks whose project-condition (lwm JOURNAL.md / gsd .planning/config.json / adr .adr-config.yaml / rtk) actually matches the project under CLAUDE_PROJECT_DIR; verify both settings reference AND script file are gone |
| feedback | 🔴 superseded | The 2026-07-26 claim that Pi, `.env`, and basic resources were absent |

## ✅ Verified Active

### feedback — P7 cognition and visible play

- The user wants P7 itself to play, explain game hypotheses, and print every cognition change in runtime logs. Assistant summaries do not replace runtime output.
- When asked to continue after verified levels, resume from the saved next-level pose rather than make the model solve earlier levels again. Record warm restoration separately from new solving; preserve solved evidence before continuing.
- User explicitly authorized sequential local solving across the 25-game catalog: DC22 → VC33 → remaining games, skipping completed SP80; User subsequently authorized two simultaneous games, each with a separate workspace; maximum two. The 900-second preset applies to EACH LEVEL ATTEMPT: save each passed prefix, then give the next level a new timer. After two failed attempts at one blocked level switch games; success resets that level’s failure counter. A passed level using at least its baseline but scoring below115 gets one efficiency redo promptly after the current same-game attempt settles; do not wait for full-game completion. Keep the better result and preserve later saved levels. Announce every newly started game with its ID, starting level and concurrent partner. After finite DC22 and VC33 attempts, the user authorized exactly one complete 25-task official submission: pause remaining local games, record official score/channel, then resume. On2026-10-06 the user subsequently authorized one additional complete25-game saved-route submission while keeping two local games running; this second finite card closed-confirmed29.834632 (7full games/54levels/1883actions, card749fd876-37e4-42aa-9dc8-fdb9511b0f4a). User now authorizes exactly one third complete25-game saved-route submission after current CD82/RE86 rounds reach full completion or a genuine finite unfinished boundary; retain two local games and report the new receipt plus change from the second card. After RE86 L8 finished, user explicitly prioritizes completing existing partial games NOW alongside the independent official submission: no fresh games and no efficiency redos in this phase; keep two slots. Preserve historical failures and count two new genuine unfinished attempts per blocked level in this new phase. This does not authorize open-ended livebench. The console covers all 25 local games with local scoring and per-game continuation/replays. User prefers timely integration of completed branch work into `main`.
- Action judgment must occur during P7 solving and be saved immediately; playback only displays those native conclusions. Never call another LLM to backfill judgments in replay. Missing legacy structured fields mean未记录, not an actor judgment of未识别. Action labels must show P7's learned operation meanings. Visual changes are valid action-effect evidence for P7 to reason about and verify; frontend pixel-shift shortcuts must not substitute for that reasoning. 特殊用途 means a known operation that needs a full tooltip; unknown remains未识别. Use plain labels: fixed input meaning, observed understanding, with usage counts kept separate.
- Keep the original level-sidebar layout; reduce repeated text and bold only the passed action count. User rejected the oversized step redesign.
- Prepare the full25-game/183-level roster before game switching; the user rejects first-use parsing and fragile cache-only warming. Loading feedback must not flash, move the board or reserve a large empty row. Keep redundant evidence text in compact accessible details.
- Preserve and actually reuse failed research, including zero-level attempts, negative hypotheses and useful programs; retries should continue accumulated understanding rather than restart empty. User prefers timely integration of completed work into `main`; coordinate the branch merge promptly after closure and do not leave completed work stranded.
- Judge learning by accumulated game understanding and how it informs play. Do not equate experience with an old solution route or require complete cognition before attempting a level.
- Review P7 solving at the whole-design level against Tycho/Retrodict actual code. The user prioritizes WorldMap-driven reasoning and Prime's IPython, requires the web console to support the solving process, and authorizes a bold redesign without preserving current implementation shape. Do not assume PNG is necessary or respond with disconnected patches. Proposal: `docs/superpowers/specs/2026-10-05-p7-worldmap-solver-redesign.md`; source review: `docs/reviews/2026-10-05-p7-worldmap-solving-design-review.md`.
- Use the existing Pi Codex subscription with `gpt-6.1-sol`; do not switch to OpenRouter. Delegate ordinary programming to Sol high and repetitive checks to Luna; independently review changes.
- Console HTML and acceptance evidence must live in persistent project run directories, never only in temporary directories. Console acceptance uses DOM, HTTP and exported-HTML checks, plus the existing browser when diagnosing user-visible failures. Existing Zen session was reused for the replay-freeze verification; do not create a new profile or claim Chrome acceptance from Node/JSDOM. The canonical controller URL is fixed at http://127.0.0.1:57515/ across restarts. The UI shows the active run when solving, otherwise the selected saved route; the latest failed/partial attempt is a separate diagnostic view, without a multi-run chooser.
- User requires slow replay parsing to happen during passed-level saving, preparing durable per-level files; a first-use cache rebuild alone does not meet the request. Switching games must show progress promptly and keep saved counts/cognition bound to the same source.
- User rejects repeated console regressions and per-game display patches: keep saved progress, action totals, cognition and fixed replay selection consistent across recovery and retries. Unplayed games should allow each level initial preview without creating completion evidence.
- The console centers P7 autonomous solving and a readable Chinese gameplay description. Hypotheses fill knowledge gaps; they do not replace the solving task. Show actual public decisions and action feedback.
- Current idle default selection opens the saved verified P7 route. Explicit HUMAN mode should show its saved pose or real initial frame and permit direct play. Human play is independent manual validation. It must not enter P7 context, cognition, history, learning or control workflow. Replay remains separate. Approved design: `docs/superpowers/specs/2026-10-05-prime-p7-console-modes-design.md`.
- The console should remember the last game and level, including after service restart. Human validation permits direct level choice. Show the current action through its button highlight; keep the action panel compact. Human controls need clear execution feedback and a frame timeline/action queue. Played human levels must save their pose/history and permit switching back to continue, including after console restart. Provide an explicit current-level clear and fresh start, separate from history-preserving RESET; preserve other levels.
- Current solver contract: `docs/superpowers/specs/2026-10-05-p7-worldmap-solver-redesign.md`; the earlier cognition-and-experience contract describes the retained legacy path. Current evidence and immediate action: `docs/status/RESUME-NEXT-SESSION.md`.

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

### feedback — delete a seam whose only purpose was the forbidden dependency

- When a mechanism exists only to reach into something the project forbids,
  remove it. Do not look for a different source to feed it. The tell is that the
  seam presents itself as generic scaffolding: the framework half really is
  generic, and only its *consumer* was illegitimate, so retargeting feels
  conservative when it is actually rebuilding the forbidden edge.
- Given 2026-09-16, after treating the pinned Pi dependency channel as a seam to
  repair. Its whole purpose was to inject Prime Agent's modified-Pi compaction
  internals by another name; the user's reply was "谁让你偷偷导入prime-agent的，
  我不如直接用 prime-agent 好了". Deleting it outright (−686 lines) was correct and
  unblocked the work.
- **Why:** retargeting preserves the dependency the project spent a whole phase
  removing, and it leaves the next session unable to tell a legitimate seam from
  a disguised import.

### feedback — a classification is not a cause; recover the value

- When a failure surfaces as a classification with no detail, instrument the
  check that produced it and read the actual values before changing anything.
  `raise ... from None` suppresses the display but leaves the original in
  `__context__`, so the cause is recoverable without touching production code.
- Given 2026-09-16, diagnosing the P1 live run: "Prime backend recovery required"
  and "native event type is invalid" each named nothing. Walking `__context__`
  and logging every event type turned both into exact findings — a SIGTERM'd
  worker, and `agent_settled` missing from the accepted vocabulary.
- **Why:** two of this session's three real defects were invisible at the
  classification level. Guessing at them would have produced speculative edits
  in a runtime that other applications share.

### feedback — instrument ack state, not just the surrounding exception

- When a multi-prompt state machine (here `drive_prompt` in
  `runtimes/pi_rpc.py`) raises "X before Y", instrument both the event sequence
  AND the state transitions at each step — not just the surrounding exception
  block. The exception tells you "what", the event trace tells you "why this
  prompt took a different path than the previous one".
- Given 2026-09-19, after P1's `recovery-required` was finally traced to
  `pi_rpc.py:769 RuntimeError("Received agent_settled before prompt
  acknowledgement")`. Earlier diagnostic passes that only printed the
  exception caught at `backend.py:797` and `execution.py:479` showed the
  symptom (`run.failed`) but not the producer-side event order; only adding a
  trace in `drive_prompt`'s loop exposed that **the second `_prompt`'s first
  event was `agent_settled`, with no prior `response` ack** — while the first
  `_prompt` had `response` first, then `agent_start/.../agent_end`. The
  exception-only trace (`raise ... from None` at three layers) hid exactly the
  ordering signal that the producer's vocabulary reveals directly.
- **Why:** a state machine that classifies by event *type* (`response` vs
  not) cannot be debugged from a typed exception — the same exception fires
  for "ack lost" and "ack never came", and the only discriminator is the
  event sequence leading into the throw. If the underlying protocol can
  reorder, **always log the sequence that produced the failure**, not just
  the failure.
- **Practical rule:** for state-machine `raise` in `drive_prompt` /
  `_invoke` / `_await_driver` / `handle_event`, the diagnostic should print
  every event type the loop sees AND the state variable (`acknowledged` /
  `round_terminal_seen` / etc.) after each step — not just at the throw.
  Single-point exception print is necessary but not sufficient for these
  state machines.

### feedback — a state-machine bug fix in one layer is not done; find every place that checks the same key set

- When a multi-layer state machine rejects a key set at one layer (e.g.
  `handle_event` rejects `agent_settled` with `EVENT_TYPE_INVALID`), fix
  that layer — but immediately grep for every other layer that has the same
  key set embedded. A fix at one layer often exposes a sibling layer that
  still has the narrow shape, and a "fixed" bug that still produces a
  different rejection is not fixed.
- Given 2026-09-19, after `a581a56c` accepted `agent_settled` in
  `execution.py:366`'s benign-trailing set (so `handle_event` no longer
  raises `EVENT_TYPE_INVALID`), but P1 still failed at the next layer with
  `RuntimeError("Received agent_settled before prompt acknowledgement")` from
  `runtimes/pi_rpc.py:725-772`'s `drive_prompt` ack state machine. The
  sibling layer (`agent_end`-only round-terminal check at `execution.py:539`)
  was the third layer; only after fixing all three did the protocol stage
  progress (`verify.start → verify.complete → oracle.start`). The pattern
  is: **`handle_event` filters out the event → `drive_prompt` checks the
  same key set → `consume_checked` and the round-terminal guard check it
  again.** Whenever the key set is filtered at one layer, grep the whole
  tree for that key and re-check each call site.
- **Why:** the `from None` exception suppression at three layers
  (`backend.py:797/818`, `execution.py:479`, `runtime_binding.py:204`)
  hid which layer was throwing. Without the event-sequence trace, the
  rejection looked identical ("runtime failure") at every layer, and the
  only way to find all three was to instrument the deepest layer first
  and walk outward. Once the deepest layer is fixed, the *next* deep layer
  becomes the bottleneck — and the failure mode at that next layer is
  usually the same key set with a sibling check the original fix missed.
- **Practical rule:** when a bug fix touches a state-machine key set
  (event types, terminal kinds, lifecycle names), do the same grep the
  consumer-side debugging did, then fix **every** site that matches. If
  the bug fix is at the consumer side and the producer side already
  accepted the key, the consumer-side fix is usually a sequence of fixes
  at multiple layers, not one.

### feedback — verify the producer side independently before assigning blame

- When a producer's behavior looks broken in your call path, run a
  one-shot RPC probe that uses the same JSON protocol your code uses
  *minus your own wrapping layer*. If the probe works correctly and your
  path doesn't, the bug is in your wrapper — not in the producer. Writing
  a 30-line shell + node script that spawns the producer binary and
  sends two prompts over the same wire format is cheaper than chasing a
  non-existent upstream bug through deeper layers of state-machine
  debugging.
- Given 2026-09-19, after concluding from P1's event stream that "Pi
  0.85.1 reuse path has a functional regression: second prompt produces
  only `agent_settled`, no model turn". The actual root cause was
  somewhere in the Asterion→Pi wrapper path (likely a session/compaction
  side effect between the two prompts). A direct RPC probe against
  `pi-coding-agent/dist/bundle/rpc-entry.js` using only
  `{id, type: "prompt", message: "..."}` twice — exactly the shape
  Asterion's `drive_prompt` sends — ran cleanly twice with full
  `message_start → message_update × N → message_end → agent_end`
  sequences both times. The conclusion that Pi has a reuse-path bug was
  wrong; the difference between the probe and Asterion's call path was
  the *whole* Asterion side (session backend, extension, IPython worker,
  the context between the two prompts), not Pi.
- **Why:** blaming an external library is **sticky** — once it lands in
  a journal entry, a decision doc, and a stub commit message, the next
  session spends hours looking for upstream fixes or version downgrades
  that don't exist. The direct probe costs two minutes and prevents
  the entire failure mode. Use it the moment you find yourself saying
  "the producer must be broken".
- **Practical rule:** when `producer` is a binary/library you have on
  disk and the call shape is a small JSON RPC (or HTTP, or any wire
  protocol), spawn it directly with a 30-line probe that omits your
  wrapper, send the same calls your wrapper sends, and compare the
  observed behavior. If the probe passes and your wrapper fails, the
  bug is in your wrapper — full stop. Write the probe before drafting
  any blame or commit.

### feedback — take a contract's key set from its producer, not from a fixture

- When a contract describes another component's output, read the code that
  produces it and copy the key set from there. Do not infer it from the
  validator, and never from a test fixture: a fixture written to match the
  contract cannot detect a contract that is wrong about its producer.
- Given 2026-09-17, after three P1 defects in one session were the same shape —
  a contract narrower than reality. The witness wire entry rejected `usage.cost`
  (floats the integer-only form cannot encode); the host required a
  `customInstructions` entry field Pi never writes; the RPC validator allowed
  four of the six keys Pi's compact result carries. Every fixture modelled the
  narrow shape, so every suite stayed green. The producer's construction site —
  Pi's installed bundle — settled all three in one grep each.
- **Why:** the fixture and the contract share an author's assumption. Only the
  producer is independent evidence, and here it was already on disk.

### feedback — last-sync-hook is the latency source, not the first slow one

- When the user reports latency at the "倒数第 2-3 个位置" (the 2nd-to-last /
  3rd-to-last hook in a chain), start the diagnosis at the **last** synchronous
  hook, not the first slow one. Front hooks usually exit fast; the tail is
  where `curl --max-time` and similar timeouts land.
- Given 2026-09-18, when the user reported Claude sitting idle for tens of
  seconds to minutes before processing already-typed input. Inspecting
  `~/.claude/settings.json` hooks: the 2nd-to-last hook on every event was
  `~/.orca/agent-hooks/claude-hook.sh`, a `curl --max-time 1.5` against an
  unreachable local endpoint. Removed 10 orca groups + 7 otty groups + 9 gsd
  hooks + adr-guard + 3 lwm pretooluse (29 hooks total); input latency dropped.
- **Why:** the chain front is usually not the bottleneck; the tail hook is
  running every event with a hard timeout that no UI surface reveals. Skim
  the last 1-2 hooks before chasing earlier ones.

### feedback — global hook audit before every new phase

- Before starting a new project / phase, audit `~/.claude/settings.json` hooks
  against the project's actual structure under `$CLAUDE_PROJECT_DIR`. Drop
  hooks whose project-condition (lwm JOURNAL.md / gsd `.planning/config.json`
  / adr `.adr-config.yaml` / rtk) does not match.
- Given 2026-09-18 on Asterion: removed `gsd-context-monitor` (no opt-in,
  fires on every PostToolUse), `gsd-read-guard` / `read-injection-scanner`
  / `workflow-guard` (all node, no opt-in, fire on every Edit/Read), the
  opt-in `gsd-*` group (Asterion has no `.planning/`), `adr-guard.sh`
  (no `.adr-config.yaml`), and 3 lwm PreToolUse hooks (commit-reminder /
  long-task-launch / milestone never matched pattern but always started
  bash). Kept `lwm-stop-health.sh` (Asterion uses project-state =
  lightweight-memory system; Stop fires once and the check is the project's
  own health probe).
- **Audit completeness check (2026-09-18 evening correction).** The first
  audit cleared 9 gsd hooks from `settings.json`'s `hooks` block but missed
  two survivors: (1) `SessionStart` `gsd-session-state.sh` had a
  `.planning/PROJECT.md + ROADMAP.md` opt-in gate that fired on every
  SessionStart as a fork-then-exit-zero shell call; (2) `statusLine`
  `gsd-statusline.js` ran **on every user message** (every turn's status
  bar) — likely the "Claude is unresponsive" tail-latency felt during the
  earlier session. A "removed" entry in a journal/commit is only true if
  both the settings reference AND the script file are gone; the first
  audit only checked the first. Re-audit with `grep -nE 'gsd' ~/.claude/
  settings.json ~/.claude/settings.local.json` AND
  `ls ~/.claude/hooks/gsd*` to confirm both sides are clear.
- **Why:** hooks fire on every tool call, regardless of project. Stale hooks
  cost latency that compounds into the user's "Claude is unresponsive"
  feeling. Audit is cheap; the win is per-event, every session.

## 🟠 Current Judgments

- **2026-09-27 handoff boundary:** P7 currently initializes its own Pi from
  operator-injected entry/profile/provider/model configuration. Pi ownership is
  still distributed across the generic runtime, Prime session, P1/native,
  P7, and legacy Prime-agent paths; do not consolidate these paths during the
  current P7 work. The shared Asterion Pi base is a later architecture topic.

- The 2026-09-22 architecture remediation is committed on `codex/review-implementation-20260922` and awaits integration into `main`. Read `docs/status/CURRENT-STATE.md` and `RESUME-NEXT-SESSION.md` for current evidence. The 2026-09-19 “7 of 7 complete” statement is historical implementation evidence, not a current end-to-end claim. Technical decisions and verification limits live in `docs/status/DECISIONS.md` and the review report.

- **P4 design choices locked in**: deterministic fake-worker for the witness
  (no real Pi subprocess), two `make` Orb invocations against a persistent
  `ASTERION_PRIME_P4_PRIVATE_ROOT` as the supervisor (no child-process
  spawn), provider gate stays closed until witness passes (mirror of P2's
  Task 4 closure). `prime.continuity-store` is the new injected host service;
  the store's `open_continued` classmethod is the **only** path that binds
  a new identity against an existing private_root (every other identity
  field must equal prior, else `PrimeStoreError`; only `generation` may +1,
  `worker_identity_sha256` may swap with the new value recorded).
  **D-2026-09-18-01** locks in the runtime-binding SHA inheritance: the
  recover-mode next identity must inherit `pi_command_sha256`,
  `extension_binding_fingerprint`, and `ceilings_sha256` from the prior
  identity, never hardcoded literals. Same-build commit+recover worked by
  accident; cross-build detach+attach (the fixture scenario) was rejected
  by `_enforce_continuation_rules`. Current technical status and next
  actions live in `docs/status/CURRENT-STATE.md` and
  `docs/status/RESUME-NEXT-SESSION.md`.
- **Two 2026-09-16/17 judgments were withdrawn after measurement.** The
  "session too small" reading of the compaction failure was static-only and a
  decision was taken on it before any value was captured; Pi in fact compacts.
  The "Pi never read the Asterion settings" reading was disproved by importing
  Pi's own `config.js` in Orb. The 2026-09-17 "the ninth defect is the budget
  cap" reading was also superseded — the cap was real but the units mismatch
  underneath it was the blocker. All three are recorded so the reasons are not
  re-derived: capture the value first, then conclude.
- **A constant that echoes elsewhere on the path is a warning, not a
  coincidence — and one grep is not an enumeration.** `4096` appeared four times
  on the P1 compaction path — the extension's request bound, the host's request
  bound, `_INPUT_CAP_MAX`, and `reserveTokens` — and every one was either wrong
  or a copy of a wrong assumption. The tell that exposed the units mismatch was
  that the operator's `_COMPACTION_INPUT_CAPS` equals the old `_INPUT_CAP_MAX`:
  the same number in two places meant one of them was being read in the wrong
  unit. On 2026-09-17 the same clause — "the rebuilt context must be smaller in
  canonical-JSON bytes" — turned out to sit at **six** enforcement points, and
  three were found only after the search stopped being truncated by `head -20`.
  Each of the earlier ones cost a live run to discover. When a wrong constant is
  found, grep the whole path and list every site before fixing any of them.

## 🔴 Superseded but Worth Remembering

### feedback — false missing-setup conclusion (2026-07-26)

- Superseded: Pi, `.env`, and basic resources were configured and usable.
- Cause of the wrong conclusion: `make doctor` resolved operator-relative
  paths against the installed package root.
- Durable lesson: successful examples are evidence that must be reconciled,
  not dismissed by a contradictory preflight result.
