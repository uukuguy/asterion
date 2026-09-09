# Asterion README and ARC-AGI-3 Achievement Design

## Purpose

Update the repository introduction to reflect the current Asterion architecture and document one real, verified ARC-AGI-3 achievement without overstating its scope. The documentation must work for both international and Chinese readers and must use real visual evidence rather than generic promotional imagery.

## Deliverables

- `README.md`: canonical English README.
- `README.zh-CN.md`: complete Simplified Chinese counterpart.
- A mutual language switch at the top of both files: `English | 简体中文`.
- `docs/assets/arc-agi-3/solve-replay.gif`: compact animation derived from the 30 normalized frames of the sealed run.
- `docs/assets/arc-agi-3/solve-report.png`: the supplied full-report screenshot copied from `/Users/sujiangwen/Desktop/arc-agi-3-ls20.png` into the repository.

Both image assets are documentation evidence generated from normalized run data. They must not contain private worker text, credentials, local paths, prompts, or provider payloads.

## Narrative Order

1. Asterion name, one-sentence framework definition, language switch, and concise status note.
2. A prominent ARC-AGI-3 achievement section with the real replay animation.
3. Exact result facts and a restrained-width screenshot of the complete interactive report.
4. Why ARC-AGI-3 is technically different from static input/output tasks.
5. How Asterion Prime solved the task and how the evidence chain works.
6. Current Asterion architecture and component boundaries.
7. Installation, discovery, ARC artifact commands, DCI, development, and promotion guidance.
8. Compatibility and historical notes that distinguish native Asterion Prime from legacy Prime Gateway integration.

The result appears near the top, but the README remains a project README rather than a one-result announcement.

## ARC-AGI-3 Claim Boundary

The README may state only that Asterion Prime completed Level 1 of game `ls20-9607627b` in one sealed run. It must not claim that Asterion solved all of ARC-AGI-3, reached a benchmark-level score, or matched another agent.

The displayed run facts are:

- application/runtime: Asterion Prime using Pi;
- model: `deepseek-v4-flash`;
- actions: 23;
- visual frames: 30, including multi-frame action animation;
- reasoning cells: 43;
- partial game score: `3.267621`;
- completed levels: 1;
- terminal: level completed;
- sealed trace and replay verification: true;
- solve token usage and elapsed time: not recorded by this legacy run and therefore never estimated.

The README links to the distributable standalone HTML by repository-relative description but does not commit the generated `artifacts/` file. It documents the command that regenerates the export from local evidence.

## GitHub Repository Metadata

After both README files and their assets pass verification, update `uukuguy/asterion` through the authenticated GitHub CLI with these exact public values:

- Description: `Composable multi-runtime agent application framework with a native Prime runtime and verified ARC-AGI-3 interactive solving evidence.`
- Website: `https://github.com/uukuguy/asterion#arc-agi-3-interactive-reasoning`
- Topics: `agent-framework`, `agentic-ai`, `llm`, `multi-runtime`, `capability-system`, `interactive-reasoning`, `arc-agi-3`, `pi`, `python`, `typescript`, `rust`.

Read the metadata back after mutation and report the exact resulting values. Do not change repository visibility, features, branch settings, releases, or any other GitHub configuration.

## Technical Explanation

The ARC section explains four constraints in plain language:

- the objective and object semantics are hidden;
- the world is stateful across actions;
- the agent must perform online, falsifiable experiments;
- actions are bounded and success is determined by environment state, not by persuasive text.

The solve architecture is shown as a compact Mermaid flowchart or equivalent Markdown diagram:

```text
Asterion Prime → Pi → Model
       ↓
Persistent IPython → ARC Broker → Environment
       ↓
Sealed trace → Replay verification → Regenerable report
```

The explanation distinguishes the original action/evidence record from the evidence-grounded post-run narration. It does not expose or invent hidden chain-of-thought.

## Asterion Project Alignment

All project claims must be checked against the current codebase before writing. In particular, the README must reflect these current decisions:

- Asterion is a composable, multi-runtime agent application framework; Python owns orchestration and composition, TypeScript validates shared Node contracts, and Rust owns controlled execution.
- Asterion Prime and Asterion Native are peer application/runtime surfaces sharing the public Asterion framework.
- P1–P7 are applications built on Asterion capabilities, not the foundational Prime implementation.
- The native Asterion Prime path uses Asterion's Pi runtime integration and does not import or execute prime-agent source.
- Capability packages, exact assemblies, runtimes, runners, and injected host services follow the repository dependency direction and trust boundaries.
- Pi, credentials, datasets, generated private evidence, and legacy/reference source trees remain external.
- Manifests describe compatibility and contain no credentials, executable authority, prompts, mutable state, or provider secrets.
- Provider-free inspection and verification commands must remain clearly separated from provider-backed execution.
- The generated ARC story system separates immutable normalized facts, versioned analysis, versioned web rendering, and standalone export.

Existing README statements that are stale, overly brittle, or tied to an older acceptance snapshot must be corrected or replaced with durable descriptions verified from current commands. The legacy Prime Gateway section remains only if clearly labeled as compatibility/history and must not imply that native Asterion Prime wraps or depends on prime-agent.

## Visual Treatment

The replay GIF uses the ARC palette, nearest-neighbor scaling, and readable pacing. Multi-frame actions remain visible rather than being collapsed into one frame. The final state holds longer than intermediate frames.

The supplied full-report screenshot is shown near the interactive-artifact explanation at approximately 620 CSS pixels wide. It must not span the full README content width. Its caption explains that the report contains replay, frame diffs, evidence-cited narration, and post-solve understanding. The screenshot links conceptually to the standalone export instructions; it must not point to a local Desktop or ignored artifact path.

The existing Asterion ARC header artwork may appear as a secondary banner, but the real replay and report screenshot are the primary visual evidence.

## Verification

- Regenerate images directly from the committed run-story schema and the local sealed run artifact.
- Verify both README files contain mutual language links and matching section structure.
- Verify every CLI command against current `--help` output or the implementing source.
- Verify every architecture and result claim against current code, manifests, tests, or normalized run data.
- Render or inspect both Markdown files for broken relative links and image dimensions.
- Verify the report screenshot is repository-relative and rendered at approximately 620 pixels wide.
- Run focused documentation link/format checks and the existing run-story tests; do not run provider-backed work.
- Do not modify the solve result, rerun the ARC environment, or invoke a model for this documentation update.
- Update GitHub About/Topics only after local documentation verification, then read the values back with `gh repo view`.
