# Reproducing Asterion Prime P7

This guide separates inspecting the public system, running new local research, and submitting your own certified routes. The [result record](../results/arc-agi-3/README.md) describes an accumulated public-game experiment; a new checkout does not contain its private attempt history or saved route certificates.

## 1. Inspect without calling a model

From a checkout with Python 3.10+ and `uv`:

```bash
uv sync --frozen
uv run asterion list
uv run asterion describe --provider dci-agent-lite
```

The producing P7 application is under [`src/asterion/applications/prime/p7/`](../../src/asterion/applications/prime/p7). The exact registered tools are `ipython`, `p7_workspace`, and `p7_execute_plan`. Read the [prompt](../../src/asterion/applications/prime/p7/prompt.py), [research workspace](../../src/asterion/applications/prime/p7/research.py), [broker](../../src/asterion/applications/prime/p7/broker.py), and [experience loader](../../src/asterion/applications/prime/p7/experience.py) to inspect the general method rather than a per-game answer table.

For provider-free checks of the model-facing contracts, registered tools, and recorded experience:

```bash
uv sync --frozen --extra prime
uv run python -m unittest -v \
  tests.test_prime_p7_tool_registry \
  tests.test_prime_p7_actor_projection \
  tests.test_prime_p7_research \
  tests.test_prime_p7_experience
```

These are software-contract tests using controlled fixtures. `make promotion-check` adds distribution checks without model requests; live research uses the entry points below.

## 2. Prepare the external runtime and game assets

The current public [Makefile](../../Makefile) P7 launchers build an Asterion wheel and install it into an isolated guest environment. Their defaults target macOS with OrbStack's `ubuntu` Linux guest and systemd/cgroups. They need:

- Host `uv`, Python, `make`, Node.js 22.x/npm, and OrbStack's `orb`; guest `/root/.local/bin/uv`, Python 3.11+ for the pinned IPython 9 stack, Node/npm, and systemd. Make resolves Node with `npm exec --offline --package=node@22`, so the npm `node@22` package must already be cached where that resolver runs, including the guest. A system Node installation alone does not establish this cache.
- An operator-owned Pi installation with a readable, executable `dist/bundle/rpc-entry.js`, an agent profile containing `models-store.json` and `auth.json`, and authenticated access to the chosen backend. P7 does not require external Prime Agent source or SDK code.
- An ARC resource root containing public `environment_files`, metadata/baselines, and `wheels/arc_agi-0.9.9-py3-none-any.whl` plus `wheels/arcengine-0.9.3-py3-none-any.whl`. These SDK wheels and game assets are external; Asterion's framework wheel does not bundle them.
- A private operator `.env` with the ARC credential named `ARC_API_KEY` and model selection. The supplied [`.env.template`](../../.env.template) primarily configures DCI; copying it alone does not finish P7 preparation.

The default ARC root is the sibling `../external-prime/arc-agi-3/`. This is a resource-location convention, not an import of external agent source. Obtain the matching ARC toolkit wheels separately. With your ARC API key configured in the private operator `.env`, synchronize the public catalog:

```bash
make asterion-prime-p7-sync-games
make asterion-prime-p7-games
```

The sync tool uses GET requests and creates no scorecard or game instance. It fetches public game assets and rejects conflicting existing versions; it does not install Pi or download the SDK wheels. Keep credentials in your private environment/profile, never in command arguments or committed files.

For the recorded model identity, put these non-secret selections in your operator `.env`, alongside your privately configured authentication:

```dotenv
ASTERION_PRIME_PROVIDER=openai-codex
ASTERION_PRIME_MODEL=gpt-6.1-sol
```

The model is selected explicitly: the code default is currently `gpt-6-sol`, and DCI's model settings are separate. See [model selection](../../src/asterion/applications/prime/p7/model_selection.py). Provider availability and authentication must be usable in your own Pi profile; configuration text alone cannot establish that.

Review the Make defaults before running. Pass your actual paths through `ASTERION_PRIME_OPERATOR_ROOT`, `ASTERION_PRIME_ARC_ROOT`, `ASTERION_PRIME_PI_ENTRY`, and `ASTERION_PRIME_PI_AGENT_DIR`, and select `PRIME_ORB_MACHINE` as appropriate. Guest commands must be able to read the checkout, newly built wheel, ARC assets, and Pi/profile paths. The default Pi entry uses an OrbStack `/mnt/mac` mount and a Homebrew installation; it is not a portable Linux path. The local console also has an `ASTERION_PRIME_LOCAL_PI_ENTRY` setting.

Use **Make command-line overrides** for custom resource roots; exporting `ASTERION_PRIME_ARC_ROOT` alone loses to its Makefile assignment. Set `P7_ARC_ROOT` to your resource path available to the host and guest, then, for example:

```bash
make asterion-prime-p7-level-witness GAME=ls20 LEVEL=1 \
  ASTERION_PRIME_ARC_ROOT="$P7_ARC_ROOT"
```

Pass the same override to catalog, solve, console, and official commands when using that root. Adjust the other guest/profile options similarly; this command does not set up mounts or authentication.

**Current bootstrap gap:** Pi/ARC asset preparation, guest setup, and authentication are separate operator steps. `make setup` prepares Pi/DCI resources and does not complete P7 setup. On other host layouts, adapt the application launcher paths and containment wiring before using the Make entry points.

## 3. Run one bounded local research attempt

Start with an explicit game and level:

```bash
make asterion-prime-p7-level-witness GAME=ls20 LEVEL=1
make asterion-prime-p7-games
make p7-controller
```

This calls the model and OFFLINE ARC engine. The standard witness has a fixed 900-second guest allowance and cleanup checks. Its action ceiling is the human baseline through the target when no prefix is restored; with a restored prefix, it counts that prefix's actual actions plus the target-level baseline. When an existing verified target route supplies a bound, its saved target action count replaces that target baseline. `LEVEL=2` means completing levels 1 and 2 in order, not jumping to level 2. The verified variant is the default; the model uses the current three-tool research interface. No legacy variant is needed.

The application supplies observations and budgets, the LLM revises a WorldMap and optionally computes in persistent IPython, and the broker checks short plans against real feedback. An unknown mechanism can be probed with a short discriminating action. Planning and hypothesis validation need not finish a complete formal model before acting.

For a full-game attempt, or a solve through an explicitly selected level:

```bash
make asterion-prime-p7-solve GAME=ls20
make asterion-prime-p7-solve GAME=ls20 LEVEL=2
```

These use ordinary application solve bounds, not the witness's identical preset. Choose one operation at a time. Full sweeps/retries are separate research work; the example is not a prescription to start an unbounded campaign.

Each attempt has its own record under `.asterion-private/prime-p7-live/`. Inspect that attempt's `summary.json` for actual completed levels, sealed trace, replay checks, cleanup, and failure reason. A timeout, stalled execution, failed prediction, or reached action cap is not a pass. A failed later level can still preserve a separately checked completed prefix.

The console is at `http://127.0.0.1:57515/`. Viewing and replay are separate from its explicit manual/solver actions. Set `P7_RUN_DIRECTORY` to one of your existing attempt directories, then export a self-contained public projection with:

```bash
make asterion-prime-p7-console RUN="$P7_RUN_DIRECTORY"
```

Export does not call a model or execute new game actions. Missing historic reasoning is labeled missing; final knowledge is not presented as knowledge held earlier.

## 4. Understand what carries across attempts

The public [experience code](../../src/asterion/applications/prime/p7/experience.py) loads eligible same-game historical research. Empty history is valid; our private priors and records are not an installation prerequisite. Later local attempts may use their own accumulated records. The historical source, claim scope, and current evidence remain distinct.

Prefix restoration starts a new local game, replays the authenticated completed prefix, and checks every result before the model continues. It does not teleport a game to a later level. After RESET, raw observations, completed prefixes, and durable experience remain, while pending probes/planner permissions are cleared. Current-episode evidence is required for new authority.

The public `fresh-target` quarantine policy is witness-only, requires explicit source and resume bindings, and is selected by the operator. It filters identified old target-level material while preserving the permitted earlier-level prefix. This optional intervention is separate from P7's autonomous action choices. `STRATEGY=explore` selects route exploration while continuing to use eligible retained evidence.

### Does RESET erase the cost of a failed attempt?

No. P7 can choose a legal RESET within an attempt and continue while its budget remains. In Competition mode, RESET restarts the current level; it does not create a fresh game or clear charged actions. For example, 20 actions, RESET, then 10 actions cost **31 actions**. The official SDK increments both the reset counter and action count. [Competition rules](https://docs.arcprize.org/toolkit/competition_mode), [SDK scorecard implementation](https://github.com/arcprize/ARC-AGI/blob/main/arc_agi/scorecard.py).

Earlier separate OFFLINE research attempts precede the new official card and therefore are outside that card's action count. Disclosing prior exploration is essential; this distinction is not a mechanism for clearing failures inside an official run.

## 5. Submit your own certified routes

Official submission is a distinct network operation requiring an ARC API key and an operator decision. Save-time [certificates](../../src/asterion/applications/prime/p7/solution_certificates.py) bind routes to their SDK checks, identities, game assets, and verifier source. Submission statically reads that authority instead of revalidating all historical candidates with the SDK.

```bash
make asterion-prime-p7-official-preflight
make asterion-prime-p7-official-submit GAME=ls20
# Use this instead for a separately chosen full-catalog submission:
make asterion-prime-p7-official-submit GAME=all
```

Preflight checks catalog readiness without opening a card or calling a model. Saved submission creates a fresh Competition card, creates each selected game once, and executes recorded actions online without a model. It checks real observations and stops on uncertainty. Missing or stale certification is rejected before card creation. `GAME=all` requires `gpt-6.1-sol` route identity and your current certified roster. The separate `official-live-eval` entry performs model inference and is not equivalent to saved submission.

Only a checked `closed-confirmed` receipt establishes the final server score. A scorecard URL can exist while a run is pending. Local score, replay checks, open-card progress, or a recovery file cannot substitute for the final receipt. See [official results and recovery](prime-p7-games-and-official-results.md). A community entry should link the public producing code and Competition scorecard, disclose prior exploration/replay, and avoid self-reported numerical ARC-AGI-3 score fields.

## Community submission and research provenance

The [community requirements](https://github.com/arcprize/ARC-AGI-Community-Leaderboard/blob/main/CONTRIBUTING.md) focus on a general-purpose method, an open producing system, a novel contribution, and a Competition Mode scorecard for ARC-AGI-3. They do not impose a fixed-version, empty-store, fully automatic 100-score evaluation as a submission prerequisite. ARC-AGI-3 numerical scores are read from the scorecard rather than entered in submission YAML.

This record comes from iterative public-game research with retained experience, retries, operator scheduling, and mid-campaign application repairs, followed by model-free online replay. The public system implements the method; the result record identifies selected outputs. Credentials, full research conversations, and earlier private attempt records remain external. Operators can run the public system with their own assets and accumulate their own experience and certified routes.
