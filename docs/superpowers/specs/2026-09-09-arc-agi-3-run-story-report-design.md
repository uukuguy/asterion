# ARC-AGI-3 Run Story Report Design

**Date:** 2026-09-09  
**Status:** Approved
**Scope:** Asterion Prime application-owned ARC-AGI-3 solve artifacts and local report viewer

## Purpose

Produce a durable, evidence-backed analysis artifact for every Asterion Prime ARC-AGI-3 run. The artifact preserves reusable process data independently of any presentation. A web report is one reproducible rendering of that data, not the artifact's source of truth.

The rendered report must make the interactive task, observed frames, actions, discoveries, revisions, completion state, and post-run understanding legible without exposing private prompts or raw provider payloads.

The feature is not specific to `ls20-9607627b` or to successful runs. The same pipeline covers completed, incomplete, failed, cancelled, and operator-stopped runs. The first generated artifact uses the completed run `p7-live-20260909065351`.

## Architectural Placement

The feature belongs to the Asterion Prime P7 application layer. It may use domain-neutral Asterion services, but framework modules must not import ARC-AGI-3 code or report semantics.

```text
explicit run root
  → application-owned evidence reader
  → validated immutable fact model
  → immutable fact bundle
  → versioned interpretation
  → replaceable deterministic renderer
  → loopback-only read-only viewer
```

Pathlight remains a general observability product and is not extended with ARC-specific narrative concepts. Its loopback server and immutable-snapshot patterns may be followed, but its dashboard model is not a dependency of the report compiler.

## Fixed Artifact Area

All generated solve artifacts live below one visible, project-relative, ignored, operator-owned root:

```text
artifacts/arc-agi-3/
├── catalog.json
└── games/
    └── <game-id>/
        └── runs/
            └── <run-id>/
                ├── artifact.json
                ├── data/
                │   ├── run.json
                │   ├── actions.jsonl
                │   ├── frames.jsonl
                │   ├── diffs.jsonl
                │   ├── reasoning-index.jsonl
                │   └── metrics.json
                ├── analyses/
                │   └── <analysis-id>/
                │       ├── analysis.json
                │       └── story.json
                └── renders/
                    └── web/<render-id>/
                        ├── index.html
                        ├── render.json
                        └── assets/
                            ├── app.js
                            ├── styles.css
                            └── header-art.png
```

The root is derived by the operator integration and is not selected through a public manifest. The implementation adds `/artifacts/` to the repository ignore rules so generated runs are visible in the project without becoming source-controlled build inputs. Directories are created with mode `0750`; files use mode `0640`. Inputs and outputs reject symlinks. Each data bundle, analysis, and render is generated into a sibling staging directory, validated, fsynced, and atomically renamed into its final location. Immutable content identities are never overwritten; only the derived root catalog is atomically refreshed.

Raw run evidence remains separately under `.asterion-private/prime-p7-live/<run-id>/`. The visible artifact area receives validated derived facts, all required replay frames, transition data, a safe reasoning index, bounded analyses, packaged presentation assets, and safe identities. It never receives raw worker-cell code or output, prompts, provider payloads, credentials, exception text, or absolute source paths.

`artifact.json` permanently binds the digest, media type, schema identity, and relative path of every canonical data file. Each `analysis.json` independently binds its fact-bundle input and `story.json`; each `render.json` independently binds its data, analysis, renderer, assets, and outputs. `catalog.json` contains relative identities and safe summary fields only. It is rebuilt deterministically from those validated manifests, with entries sorted by game ID and run ID. The loopback viewer provides the stable browser entry point; selecting another run or render does not require a new server URL.

## Evidence Inputs

The compiler receives one explicit absolute run directory. It does not scan for runs, choose a baseline, or infer authority from existing files. For the current P7 runner, supported inputs are:

- `summary.json` for terminal state, receipt, replay verification, cleanup, and recorded diagnostics;
- `trace/prime-trace.jsonl` plus `prime-trace.seal.json` for ordered, hash-chained actions and identities;
- the single recording below `recordings/` for the initial observation and post-action frames;
- `worker-cells.jsonl` for private reasoning evidence used by the narrator;
- `usage.reported` events emitted by Pi and persisted into the application-owned
  private trace as authoritative input/output token counts;
- optional future timing fields recorded by the application runner.

The evidence reader validates the summary schema, sealed trace, stable identities, action sequence, frame count, frame shape, recording-to-trace correspondence, and terminal-state consistency before producing facts. Ambiguous or missing required inputs fail closed. Incomplete runs may omit a trace seal only when their summary truthfully identifies a non-completed terminal condition; such reports carry an explicit `UNVERIFIED` or `PARTIAL` evidence badge rather than a completion seal.

## Immutable Fact Model

The internal application-owned model is `asterion.prime.arc-agi-3-run-story/v1`. It is not a new framework protocol. Its fact portion contains:

- application, runtime, reasoning, provider, and model identities;
- game ID, level, seed when recorded, run ID, and evidence digests;
- terminal state, levels completed, score, action count, action limit, replay and seal status;
- start time, end time, elapsed duration, model usage, and reasoning-cell count when authoritatively recorded;
- ordered actions with before/after frame identities and changed-cell counts;
- the initial frame and every resulting frame;
- evidence-backed notable transitions such as collision/no-op, large visual change, state change, and completion.

Missing measurements render as “未记录”; they are never reconstructed from filenames, filesystem modification times, or mockup values. In particular, the current successful run reports the actual `43` worker cells from `summary.json`; the earlier visual mockup's `41` is not carried into the artifact.

Pi already reports token usage on assistant `message_end` events. The common Pi
runtime adapter normalizes those native fields into the existing public
`asterion.agent-runtime/v1` `usage.reported` event. Asterion Prime consumes that
public event without redefining its shape, while the P7 projector retains the
counts in private application evidence before producing its receipt-only public
projection. The report compiler sums only validated persisted usage records.
Runs created before that persistence exists remain explicitly “未记录”; token
counts are never reconstructed from text length or a provider invoice.

The fact model is frozen before narration. Narration cannot change actions, frames, counts, identities, score, status, timestamps, or verification badges.

## Preserved Process Data

The normalized bundle is the durable analysis surface. It is intentionally independent of HTML and contains:

- `run.json`: run identity, task identity, terminal state, verification state, score, limits, model/runtime identities, timing and usage availability, and source-evidence digests;
- `actions.jsonl`: one ordered record per applied primitive action, including action name, before/after frame index and digest, environment state, levels completed, remaining budget, and no-op/collision classification when derivable;
- `frames.jsonl`: the initial observation and every post-action frame as exact palette-indexed arrays with shape, digest, state, and sequence metadata;
- `diffs.jsonl`: deterministic changed-cell coordinates, bounding boxes, counts, and palette transitions for every adjacent frame pair;
- `reasoning-index.jsonl`: safe per-cell metadata such as cell sequence, success/error category, code/output digests, cited action/frame indices, and bounded purpose labels, without raw worker code or output;
- `metrics.json`: action totals, changed-cell distributions, productive/no-op counts, reasoning-cell totals, completion transition, timing, and usage values when recorded.

JSON and JSONL are canonical UTF-8 with sorted object keys and finite values. Every record has a closed schema version. Arrays whose order is semantic retain that order; set-like arrays are sorted and unique. `artifact.json` binds all file digests so later analysis can detect mutation.

The bundle is sufficient for offline statistics, alternative visualizations, step clustering, and report regeneration. Analysts who are explicitly authorized to inspect raw worker content use the separate private evidence root; the visible artifact never becomes a duplicate raw-log store.

## Versioned Analysis Model

The narrative portion explains the run as a small number of causal episodes rather than one equal card per action. Each episode contains:

- step range;
- observation;
- hypothesis;
- experiment or planned action;
- result;
- model update;
- consequence for the next decision;
- citations to exact action and frame indices;
- confidence: `fact`, `strong-inference`, or `tentative`.

A bounded, application-owned narrator may use the injected Asterion model service to summarize validated facts and selected private worker cells. It receives no credentials, filesystem paths, provider payloads, or unrestricted host access. Its result is parsed through a closed application-owned validator. Unknown citations, altered facts, unsupported completion claims, excessive text, or forbidden fields reject the narration.

Each accepted narration is stored below `analyses/<analysis-id>/story.json`, with its provenance and output digest in the adjacent `analysis.json`. The analysis ID binds the fact-bundle digest, narrator contract version, model identity, and normalized result. A revised analysis creates a new ID; it does not overwrite an earlier explanation or the fact bundle.

If narration is unavailable or rejected, the deterministic fact compiler still produces a usable report with action playback, transition statistics, terminal status, and automatically detected notable transitions. Report generation therefore does not depend on a second model call for factual integrity.

The post-solve interpretation answers four concise questions when evidence supports them:

1. What object was controlled?
2. How did valid and invalid movement behave?
3. Which visual relationship mattered?
4. What condition completed the level?

Unsupported answers remain visibly unresolved. Failed or partial runs instead summarize the current model, tested hypotheses, remaining uncertainty, and the last productive step.

## Report Experience

The approved professional poster layout is the visual contract:

- masthead led by `ARC-AGI-3`, with game/level/run subtitle and compact model, action, score, time, and reasoning statistics;
- a subdued ARC-AGI-3 interactive header illustration integrated between title and verification status;
- a central real-frame player with play/pause, step controls, speed, frame index, action, changed-cell count, and optional difference overlay;
- a synchronized explanation panel for the selected step;
- a vertically structured causal solve story in which decisive experiments receive greater visual emphasis;
- a distinct post-run understanding block;
- concise ARC-AGI-3 protocol and Asterion execution-chain background at the bottom.

The header illustration is decorative; the central player always uses actual run frames. The report must remain understandable with narration absent and with animation disabled. Responsive layouts collapse to a single reading column without changing content order.

The first version uses plain packaged HTML, CSS, and JavaScript with no CDN, build-time web framework, telemetry, fonts, or network dependency. The viewer serves UTF-8 explicitly.

## Regenerable Rendering

Rendering is provider-free and consumes only one validated fact bundle, one selected analysis, and packaged presentation assets. It never rereads raw solve evidence or invokes the narrator.

Each render is written below `renders/web/<render-id>/`. The render ID binds the bundle digest, selected analysis digest, renderer version, and theme version. Changing layout, CSS, artwork, copy formatting, or interaction code creates a new render without changing process data or rerunning the solve. Older renders remain available for comparison or rollback.

`render.json` records those exact inputs and output digests. Generated HTML contains no uncited factual copy outside the checked-in ARC-AGI-3 and Asterion background material. The JavaScript reads normalized data rather than embedding hand-written values, so a style revision cannot silently change actions, score, frame count, or completion state.

## Local Viewer

The operator command has three separate actions:

```text
compile one explicit run → create immutable process-data bundle
analyze/render bundle    → add versioned interpretation and web render
serve artifact root      → start one loopback-only read-only viewer
```

`compile` is deterministic and provider-free. `analyze` is the only action that may use an injected model. `render` is deterministic and provider-free and may be rerun whenever presentation code changes. Serving never invokes a model, modifies artifacts, discovers external evidence, or starts a solve. The server binds only to `127.0.0.1`, uses an ephemeral port by default, allows only `GET` and `HEAD`, rejects traversal and encoded path ambiguity, emits `no-store` and restrictive CSP/security headers, and serves only files rooted below the fixed artifact area.

The URL identifies the stable catalog, not an individual generated HTML fragment. One running server and one browser tab can browse all generated runs.

## Privacy and Publication Boundary

The fixed artifact area is visible inside the project but remains an operator artifact rather than a public Asterion API or automatically published site. It may contain concise derived narration, real frames, action history, and evidence digests, but never:

- system or solve prompts;
- credentials or environment values;
- absolute paths;
- raw provider requests or responses;
- unrestricted worker code/output;
- hidden expected answers;
- arbitrary exception text.

Worker cells are read only as narrator input. They are not copied into `story.json` or HTML. Error presentation uses closed public-safe categories. A future shareable exporter is outside this implementation; the repo-visible artifact must not be treated as publication-ready merely because it renders in a browser.

## Failure Behaviour

- Invalid, ambiguous, inconsistent, or symlinked evidence produces no final artifact.
- A narration failure degrades to the deterministic factual report and records a safe narration status.
- A missing frame prevents animation but may produce a metadata-only partial report only when the terminal summary is otherwise valid and explicitly identifies the evidence gap.
- An existing bundle, analysis ID, or render ID causes a deterministic conflict error rather than overwrite; a new version receives a new content-bound identity.
- Catalog refresh ignores no malformed artifact silently; it fails and leaves the previous catalog intact.
- The server returns closed 404/405 responses without private detail.

## Minimal Verification

Testing is intentionally bounded to the feature's trust and correctness edges:

1. A completed sealed fixture compiles deterministically with ordered actions, exact frames and diffs, safe reasoning metadata, and a `VERIFIED` completion state.
2. An operator-stopped or incomplete fixture compiles without inventing success, score, elapsed time, or post-solve certainty.
3. Tampered trace, mismatched frame/action count, ambiguous recording, traversal, and symlink inputs fail before publication.
4. Sentinel prompt, credential, path, provider-payload, and raw-worker-output strings do not appear in any artifact or HTTP response.
5. Narration cannot alter facts or cite nonexistent steps; rejected narration falls back to the factual report.
6. Re-rendering the same bundle and theme is byte-deterministic, while a theme-version change produces a new render without changing data digests.
7. The loopback server serves UTF-8 assets and rejects mutation methods and path escape.

The primary verification command is:

```bash
uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story
```

Broader repository checks are run only if implementation touches packaged resources, entry points, or distribution metadata.

## Initial Delivery

The first delivery will:

1. persist Pi's authoritative token-usage events in private P7 evidence without
   widening the public receipt, then add the application-owned evidence reader,
   normalized process-data compiler, narrative validator, renderer, and loopback
   viewer;
2. add CLI actions that compile one explicit run, add a versioned analysis, regenerate a web render, and serve the fixed artifact catalog;
3. generate the first real data bundle, versioned analysis, and web render for `ls20-9607627b` from `p7-live-20260909065351`;
4. verify that the report uses the recorded 23 actions, score `3.267621`, completion and replay seals, real frames, model identity, and 43 worker cells;
5. mark timing or usage values unavailable unless authoritative evidence exists;
6. preserve all existing P7 solve and evidence behaviour.

No hosted deployment, public sharing flow, PDF export, comparison view, or framework-level ARC abstraction is included in this delivery.
