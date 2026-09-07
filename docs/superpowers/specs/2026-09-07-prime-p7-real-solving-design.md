# Prime P7 Real ARC-AGI-3 Solving Design

## Decision and status correction

P7 is complete only when Prime autonomously solves ARC-AGI-3 content.  The
existing `prime-p7-run` four-action episode remains useful evidence for the
runtime, broker, restricted worker, replay, and cleanup chain, but it is a
transport smoke test.  It does not complete P7 because its prompt and validator
fix four `ACTION1` calls and it never completes a level.  Until the solving
gate below passes, the Prime program status is six of seven complete.

The next and only implementation target is P7a: use the operator-injected
`deepseek-v4-flash` host service to complete at least the first level of the
public offline `ls20-9607627b` environment through Prime's persistent,
programmatic interaction loop.  Matching Prime Intellect's Opus 5 score is not
part of P7a.

Passing P7a changes the seven-scenario Prime program from 6/7 to 7/7
functionally complete.  P7 then has two independently reported maturity gates:

1. **P7b public reproduction:** complete all seven LS20 levels, then measure
   the public 25-game corpus with the official RHAE calculator.
2. **P7c Kaggle submission:** package the same solver capability for the
   network-disabled Kaggle environment with an injected local-model host and
   notebook/submission adapter.

P7b multi-game runs and P7c are outside the P7a implementation scope.  They do
not block delivery of the first command-line solver or the 7/7 functional
completion claim.  Status must always name the achieved gate: `P7a solved`,
`P7b public reproduction`, or `P7c Kaggle submission`.

This design supersedes the completion semantics in
`2026-09-04-prime-p7-arc-agi-3-design.md` and the resulting canonical status
claims.  It preserves their implemented transport evidence.  The implementation
work updates `CURRENT-STATE.md`, `PRIME-TYPICAL-APPLICATIONS.md`, the framework
worklist, resume state, and Make help so none describes the four-action smoke as
ARC solving.

## Upstream reference and fidelity boundary

The implementation follows Prime Intellect's MIT-licensed companion repository
`PrimeIntellect-ai/arc-agi-3-prime-agent` at commit
`398d4dd63cf01d00adbea41c13437ba0b8ad40fc`.  Its relevant behavior is:

- one fresh Prime agent session and restricted worker per game;
- a persistent IPython workspace for programmatic frame analysis;
- game access only through `observe`, `status`, and `act` over a Unix socket;
- no model access to the ARC SDK, engine source, provider credentials, other
  games, or prior runs;
- game-agnostic behavioral guidance that builds and revises a world model;
- validated action batches containing at most 20 primitive actions; and
- a finite per-game action ceiling.

Asterion will source-lock the adapted prompt, behavior guide, client, action
validation, and broker semantics.  Any substantially copied source retains the
upstream MIT notice.  The upstream implementation is a behavioral reference,
not a new framework dependency and not an alternate runner.

The published companion repository says the reported protocol has a 500-action
per-game ceiling, while its published result rows include some larger action
counts.  P7a therefore treats the checked-in broker protocol as authoritative
for execution and does not claim bit-for-bit reproduction of the published
scorecards.  This discrepancy must be resolved before a P7b reproduction claim.

## Installed identities

P7a is additive.  It does not reinterpret the existing installed route or its
receipt:

| Role | Existing transport smoke | New P7a solver |
| --- | --- | --- |
| application | `prime.arc-agi-3@1.0.0` | `prime.arc-agi-3-solving@1.0.0` |
| executable capability | `prime.arc-agi-3@1.0.0` | `prime.arc-agi-3-solving@1.0.0` |
| host capability | `prime.arc-agi-3-development` | `prime.arc-agi-3-solving` |
| input preset | `fixed-small-verification` | `solve-first-public-level` |
| result scope | `p7-development` | `p7-solving` |
| promotion | `unpromoted` | `unpromoted` |
| artifact ID | `prime.p7-development.trace` | `prime.p7-solving.receipt` |
| artifact kind | `p7-development` | `p7-solving` |
| media type | `application/vnd.asterion.prime.p7-development-trace+json` | `application/vnd.asterion.prime.p7-solving-receipt+json` |

The solving assembly references `prime-arc-agi-3-solver@1.0.0` and selects
`prime.agent`.  Its solver capability requires the runtime-provided
`prime.tool.ipython`.  It does not depend on the existing `prime-agent@1.0.0`
capability package unless it explicitly composes one of that package's declared
scenario capabilities.  This avoids changing the contents of the already exact
package.  Each executable has one exact implementation binding.  Selection
occurs only through the installed application and exact assembly references,
with no hidden option, environment precedence, source scanning, or
reinterpretation of a development receipt.

The generic Prime runtime bridge gains immutable `PrimePresetExecutionRequest`
and `PrimePresetExecutionResult` values plus a `PrimePresetExecutionService`
protocol.  Its application-selected runtime profile fixes the admitted input
preset, result scope, promotion state, and artifact descriptor.  It converts a
successful host result into the existing runtime artifact descriptor without
importing ARC-specific types.  The existing fixed-small-verification routes
retain their present service and behavior.

P7a's `prime.arc-agi-3-solving` host implements that generic execution service
and an application-owned `PrimeArcAgi3SolveReceiptAccessor`.  The accessor
returns an immutable, public-safe receipt only for an exact run ID and digest
after successful completion; retrieval performs no execution and cannot start
another session.  The receipt admits only the `p7-solving` scope, locked digest,
completed-level count, action count, partial-game score projection, and
`unpromoted` promotion state.  `partial_game_score` is a decimal string in the
closed `0.000000` through `100.000000` form, rounded to six fractional digits
with decimal `ROUND_HALF_EVEN`.  This avoids cross-language float ambiguity
while remaining directly renderable as a numeric score.  P7a can establish
functional solving while remaining development-only.  Detailed private replay
is not part of this receipt.

Runtime events carry only the declared artifact ID, kind, media type, and
receipt digest.  After runtime completion, the exact capability implementation
uses the accessor to project allowlisted receipt fields into
`CapabilityExecutionResult.artifacts[].value`.  Run identity and receipt digest
must match the runtime descriptor.  Counts and scores are never added to runtime
event payloads.  Existing Asterion v1 schemas remain unchanged; new manifest
instances and Python/TypeScript validation must still agree.

## Architecture

No closed Asterion v1 protocol changes are required.  The dependency flow stays:

```text
CLI/operator host
  -> selected installed provider
  -> application assembly
  -> catalog/composer
  -> exact capability implementation
  -> runner
  -> prime.agent runtime adapter + injected host services
```

The Prime runtime adapter remains game-neutral.  It translates native Prime
operations and results into the public runtime protocol.  It owns no ARC rules,
prompt, game selection, scoring, rendering, broker lifecycle, or provider
configuration.  Solver guidance and solve orchestration belong to the exact
capability/application implementation.  The operator host owns model
connections, worker and broker acquisition, finite authority, cancellation,
cleanup, and private evidence.  The assembly declares every required host
capability, and injection occurs only after preflight.

The operator integration alone resolves `.env`, chooses the exact DeepSeek
backend, prepares the already-downloaded corpus, and injects host services.
Framework modules do not read provider configuration or credentials.

The runner receives a resolved plan and injected services.  It does not select
a model, discover games, authorize a benchmark, start unrelated services,
retry a failed solve, or persist evidence outside the operator-owned lifecycle.

## P7a components

### Solver guidance

Replace the fixed four-action instruction with source-locked, game-agnostic
guidance adapted from the official companion repository.  The agent must:

- inspect each frame programmatically in persistent IPython;
- track objects, colors, locations, changes, completed levels, and hypotheses;
- choose short exploratory batches when rules are uncertain;
- compare before/after frames and revise its world model;
- exploit a supported rule once evidence is sufficient; and
- continue until a level completes or the preset limit is reached.

Production solving has no prescribed action sequence or golden action-answer
validator.  Scripted provider-free test doubles may use fixed actions to
exercise transitions, but they cannot establish real-solving acceptance.  The
model may choose any action accepted by the current environment.

### Host-owned broker

The solve route receives a separate private broker implementation rather than
changing the smoke broker's closed four-action semantics.  Its model-facing
client and schema implement the upstream `observe()`, `status()`, and
`act(actions)` surface.  It owns the game instance and authoritative journal.
It validates method names, sequence continuity, action shapes, coordinates,
batch length, action ceiling, level transitions, and calls after closure.  It
returns observations and statuses only to the isolated worker.

The broker evaluates every primitive action separately.  It stops a batch at
the first authoritative level-completion transition and executes no remaining
actions.  The private replay retains the exact completion observation and any
transition frames; the renderer must not label the next level's initial frame
as the solved frame for the previous level.

The broker records enough private evidence to replay the episode and calculate
the first-level/partial-game score.  The implementation pins the
official calculator supplied by the locked `arc_agi` wheel and its baseline
inputs.  A score digest is only an integrity value and is never presented as a
numeric score.  P7a makes no full-game, corpus, or scorecard-reproduction claim.
Public application evidence contains only canonical identities, counters,
terminal classification, fixed-decimal score projection, digests, and cleanup
facts.

### Model host and persistent session

The existing operator model host supplies `deepseek-v4-flash` to the installed
Prime runtime.  The first preset is finite: one game, one session, at most 500
primitive actions, at most 128 model callbacks, and a 60-minute wall deadline.
These are internal preset controls; the command does not ask the user to choose
provider, model, cost, action, or deadline values.

The persistent IPython worker imports only the locked broker client and ordinary
analysis libraries already admitted by the worker profile.  It cannot import
the ARC SDK, inspect environment source, access the provider key, use the
network, or read another run.

### Operator display and public result

`make prime-p7-solve` is the P7a operator command.  It retains one canonical
public JSON result on stdout and routes safe progress through
`HostProgressReporter`.

The interactive command also has an explicit local presentation sink authorized
to display the public ARC game's grids and action sequence.  This sink is
separate from `HostProgressReporter`, canonical stdout, public runtime events,
receipts, telemetry, and durable status logs.  Stderr may implement the local
sink, but generic status capture must not treat its raw contents as public-safe.
Only structured, allowlisted grid cells, action fields, counters, and score
fields reach the renderer.

The replay view shows:

- the purpose, game identity, model identity, and current finite limits;
- the initial rendered grid as the question;
- model/analysis round and cumulative action progress without raw prompts or
  provider payloads;
- level transitions and terminal reason;
- the action sequence plus the solved-level frame as the interactive answer;
  and
- completed levels, primitive action count, and fixed-decimal partial-game score.

The operator renderer consumes in-memory/private lifecycle evidence and does
not add frames, prompts, model reasoning, provider bodies, credentials, raw
engine output, or private filesystem paths to the public result or durable
status logs.  Showing the question and action answer never authorizes rendering
model prose or chain-of-thought.

The existing `make prime-p7-run` remains the cheap four-action transport smoke
test and must describe itself as such.  It cannot report P7 solving completion.

## Execution and evidence flow

1. The operator preset prepares and verifies the locked LS20 resource, Prime
   runtime, source set, worker image, broker client, and model host.
2. The host creates one private broker and one restricted Prime worker, then
   injects the socket and model services.
3. Prime observes the initial frame and iterates between programmatic IPython
   analysis, model reasoning, and broker actions.
4. Each broker response advances one authoritative journal.  The host emits
   safe phase/round/action/level progress independently of model text.
5. On the first level transition, the private broker stops the current batch.
   The host closes P7a successfully, replays the journal with the same resource
   identity, seed, calculator, and baseline inputs, renders the correctly
   labelled operator answer, and seals a redacted partial-game receipt.
6. On action, callback, cancellation, engine, worker, or wall-clock limits, the
   host closes with a stable failure classification and the best safe progress
   counters.  Limit exhaustion is evidence of an unsuccessful attempt, never a
   PASS.
7. Every path stops the broker, cancels/awaits outstanding work, removes the
   worker, and proves zero lifecycle residue before returning.

## P7a acceptance

P7a is **Implemented** when the installed application path and
`make prime-p7-solve` entry point exist.  The canonical acceptance command is:

```bash
PRIME_RUN_ID=prime-p7-solve-ls20-level1-a make prime-p7-solve
```

P7a is **Verified** only when that real command exits zero, stdout contains the
single canonical application result for artifact `prime.p7-solving.receipt`,
and its evidence proves all of the following:

- the selected runtime is `prime.agent` and the injected model identity is the
  locked `deepseek-v4-flash` preset;
- the official offline game identity is `ls20-9607627b`, seed 0;
- action selection was dynamic and no expected/fixed action sequence was used;
- the agent used the admitted persistent IPython/broker interaction surface;
- at least one real level transition completed;
- replayed actions reproduce the completed level and fixed-decimal partial-game
  score;
- the operator display contains the initial question, action answer, solved
  frame, progress, and score;
- the public JSON result and logs satisfy redaction rules; and
- the broker, worker, model session, and temporary state were cleaned up.

A model attempt that reaches a finite limit without completing a level remains
an executable but failed P7a attempt.  It must be diagnosable from safe progress
and private replay evidence, then improved through prompt/harness iteration.

## Failure handling

Preflight rejects identity, resource, runtime, model-host, or worker mismatches
before starting the game.  The application's private broker rejects malformed
calls, oversized batches, invalid actions or coordinates, sequence gaps,
action-limit overflow, contradictory level state, and post-terminal calls.
Provider and worker failures expose stable classifications only.

Cancellation, timeout, or model failure closes the private journal before
cleanup.  Cleanup errors never overwrite the original failure, but an otherwise
successful solve cannot pass without proved cleanup.  No automatic retry starts
a second paid model session.

## Focused verification

Development verification stays proportional to the boundary change.  It adds
focused `unittest` coverage for:

- dynamic action acceptance and removal of the fixed-action validator;
- action/batch/sequence/terminal rejection;
- first-level success versus finite-limit failure;
- official calculator/baseline score replay binding;
- structured operator rendering separated from canonical stdout, runtime
  events, progress, receipts, and durable logs;
- sentinel redaction; and
- cancellation and cleanup.

One provider-free scripted episode verifies orchestration boundaries and cannot
establish a solving PASS.  Provider-free focused tests cover the new solve route
and continued smoke-route behavior.  Run the repository-required checks
applicable to changed Python, TypeScript, documentation, and contracts.  Run
`make promotion-check` because P7a adds an installed entry point and packaged
resources.  Record every named command and result; unrun checks remain Not
rerun.

One real DeepSeek LS20 solve is the acceptance command.  Paid multi-game
benchmarks, adversarial campaigns, repeated real-model stability runs, and
Kaggle execution remain deferred to separately authorized P7b/P7c work.

## Kaggle target

ARC Prize 2026 ARC-AGI-3 is the final external target because it evaluates the
same exploration, world-modeling, goal-setting, and planning behavior on hidden
interactive environments.  Its Kaggle evaluation is network-disabled, so the
P7a DeepSeek API host cannot be the competition host.

P7c adds a separate operator/application adapter that injects a packaged local
model, runs under the Kaggle notebook limits, interacts through competition
mode, and generates the required submission.  The ARC solver capability and
Prime runtime contract stay unchanged.  This provider swap is itself a target
demonstration of Asterion's framework and capability integration protocol.

Primary references:

- <https://github.com/PrimeIntellect-ai/arc-agi-3-prime-agent>
- <https://www.primeintellect.ai/blog/prime-agent>
- <https://arcprize.org/competitions/2026/arc-agi-3>
- <https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3>
- <https://docs.arcprize.org/toolkit/competition_mode>
