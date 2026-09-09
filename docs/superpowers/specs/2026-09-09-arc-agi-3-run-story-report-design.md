# ARC-AGI-3 Run Story Report Design

**Date:** 2026-09-09  
**Status:** Approved for implementation planning  
**Scope:** Asterion Prime application-owned ARC-AGI-3 solve artifacts and local report viewer

## Purpose

Produce a durable, evidence-backed explanation of every Asterion Prime ARC-AGI-3 run. The report must make the interactive task, observed frames, actions, discoveries, revisions, completion state, and post-run understanding legible without exposing private prompts or raw provider payloads.

The feature is not specific to `ls20-9607627b` or to successful runs. The same pipeline covers completed, incomplete, failed, cancelled, and operator-stopped runs. The first generated artifact uses the completed run `p7-live-20260909065351`.

## Architectural Placement

The feature belongs to the Asterion Prime P7 application layer. It may use domain-neutral Asterion services, but framework modules must not import ARC-AGI-3 code or report semantics.

```text
explicit run root
  → application-owned evidence reader
  → validated immutable fact model
  → bounded run-story narration
  → immutable report artifact
  → loopback-only read-only viewer
```

Pathlight remains a general observability product and is not extended with ARC-specific narrative concepts. Its loopback server and immutable-snapshot patterns may be followed, but its dashboard model is not a dependency of the report compiler.

## Fixed Artifact Area

All generated solve artifacts live below one visible, project-relative, ignored, operator-owned root:

```text
artifacts/arc-agi-3/
├── catalog.json
├── index.html
└── games/
    └── <game-id>/
        └── runs/
            └── <run-id>/
                ├── manifest.json
                ├── story.json
                ├── index.html
                ├── assets/
                │   ├── app.js
                │   ├── styles.css
                │   └── header-art.png
                └── frames/
                    ├── 000.json
                    ├── 001.json
                    └── ...
```

The root is derived by the operator integration and is not selected through a public manifest. The implementation adds `/artifacts/` to the repository ignore rules so generated runs are visible in the project without becoming source-controlled build inputs. Directories are created with mode `0750`; files use mode `0640`. Inputs and outputs reject symlinks. A run is generated into a sibling staging directory, validated, fsynced, and atomically renamed into its final location. Existing run artifacts are never overwritten.

Raw run evidence remains separately under `.asterion-private/prime-p7-live/<run-id>/`. The visible artifact area receives only validated derived facts, selected frames, bounded narration, packaged presentation assets, and safe identities. It never receives raw worker cells, prompts, provider payloads, credentials, exception text, or absolute source paths.

`catalog.json` contains relative identities and safe summary fields only. It is rebuilt deterministically from validated run artifacts, with entries sorted by game ID and run ID. The root `index.html` provides the stable browser entry point; selecting another run does not require a new server URL.

## Evidence Inputs

The compiler receives one explicit absolute run directory. It does not scan for runs, choose a baseline, or infer authority from existing files. For the current P7 runner, supported inputs are:

- `summary.json` for terminal state, receipt, replay verification, cleanup, and recorded diagnostics;
- `trace/prime-trace.jsonl` plus `prime-trace.seal.json` for ordered, hash-chained actions and identities;
- the single recording below `recordings/` for the initial observation and post-action frames;
- `worker-cells.jsonl` for private reasoning evidence used by the narrator;
- optional future timing and usage fields recorded by the application runner.

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

The fact model is frozen before narration. Narration cannot change actions, frames, counts, identities, score, status, timestamps, or verification badges.

## Narrative Model

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

## Local Viewer

The operator command has two separate actions:

```text
build one explicit run → create immutable artifact and refresh catalog
serve artifact root   → start one loopback-only read-only viewer
```

Serving never invokes a model, modifies artifacts, discovers external evidence, or starts a solve. The server binds only to `127.0.0.1`, uses an ephemeral port by default, allows only `GET` and `HEAD`, rejects traversal and encoded path ambiguity, emits `no-store` and restrictive CSP/security headers, and serves only files rooted below the fixed artifact area.

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
- An existing final artifact causes a deterministic conflict error rather than overwrite.
- Catalog refresh ignores no malformed artifact silently; it fails and leaves the previous catalog intact.
- The server returns closed 404/405 responses without private detail.

## Minimal Verification

Testing is intentionally bounded to the feature's trust and correctness edges:

1. A completed sealed fixture compiles deterministically with ordered frames, exact facts, and a `VERIFIED` completion state.
2. An operator-stopped or incomplete fixture compiles without inventing success, score, elapsed time, or post-solve certainty.
3. Tampered trace, mismatched frame/action count, ambiguous recording, traversal, and symlink inputs fail before publication.
4. Sentinel prompt, credential, path, provider-payload, and raw-worker-output strings do not appear in any artifact or HTTP response.
5. Narration cannot alter facts or cite nonexistent steps; rejected narration falls back to the factual report.
6. The loopback server serves UTF-8 assets and rejects mutation methods and path escape.

The primary verification command is:

```bash
uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story
```

Broader repository checks are run only if implementation touches packaged resources, entry points, or distribution metadata.

## Initial Delivery

The first delivery will:

1. add the application-owned evidence reader, fact compiler, narrative validator, renderer, and loopback viewer;
2. add a CLI entry that builds one explicit run and serves the fixed artifact catalog;
3. generate the first real artifact for `ls20-9607627b` from `p7-live-20260909065351`;
4. verify that the report uses the recorded 23 actions, score `3.267621`, completion and replay seals, real frames, model identity, and 43 worker cells;
5. mark timing or usage values unavailable unless authoritative evidence exists;
6. preserve all existing P7 solve and evidence behaviour.

No hosted deployment, public sharing flow, PDF export, comparison view, or framework-level ARC abstraction is included in this delivery.
