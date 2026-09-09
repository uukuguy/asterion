# Asterion README and ARC-AGI-3 Achievement Design

## Purpose

Update the repository introduction so Asterion's framework identity, architecture, capability model, runtimes, and application portfolio are unmistakably primary. Document one real, verified ARC-AGI-3 achievement as a compact application case study without allowing it to dominate the project narrative or overstating its scope. The documentation must work for both international and Chinese readers and must use real visual evidence rather than generic promotional imagery.

## Deliverables

- `README.md`: canonical English README.
- `README.zh-CN.md`: complete Simplified Chinese counterpart.
- A mutual language switch at the top of both files: `English | 简体中文`.
- `docs/assets/arc-agi-3/solve-replay.gif`: compact animation derived from the 30 normalized frames of the sealed run.
- `docs/assets/arc-agi-3/solve-report.png`: the operator-supplied full-report screenshot copied into the repository without resizing.

Both image assets are documentation evidence generated from normalized run data. They must not contain private worker text, credentials, local paths, prompts, or provider payloads.

## Narrative Order

1. Asterion name, one-sentence framework definition, language switch, and concise research status.
2. Why Asterion exists: deterministic composition, exact identities, multiple runtimes, controlled execution, explicit host authority, and verifiable evidence.
3. Current architecture, dependency direction, language ownership, and closed public contracts.
4. Framework building blocks: capability packages, assemblies, providers, runners, runtimes, host services, and evidence.
5. Agent implementations and application portfolio, clearly separating Asterion Prime, Asterion Native, P1-P7, DCI, controlled-code, and legacy compatibility surfaces.
6. ARC-AGI-3 as one compact application case study with the real replay, exact run facts, a short explanation of the challenge, and a restrained report thumbnail.
7. Installation, provider-free discovery, ARC artifact commands, external resources, DCI, development, and promotion guidance.
8. Compatibility and historical notes that distinguish native Asterion Prime from legacy Prime Gateway integration.

The Asterion framework narrative should occupy roughly 70-80% of the README. The ARC-AGI-3 case study should occupy roughly 20-30%, appear only after the framework and application model are established, and demonstrate what the framework enables rather than redefine what the project is.

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

- Description: `Composable multi-runtime agent application framework for deterministic capability assembly, controlled execution, and verifiable AI applications.`
- Website: `https://github.com/uukuguy/asterion#architecture`
- Topics: `agent-framework`, `agentic-ai`, `llm`, `multi-runtime`, `capability-system`, `interactive-reasoning`, `arc-agi-3`, `pi`, `python`, `typescript`, `rust`.

Read the metadata back after mutation and report the exact resulting values. Do not change repository visibility, features, branch settings, releases, or any other GitHub configuration.

## ARC Case-Study Explanation

The compact ARC case study explains four constraints in plain language:

- the objective and object semantics are hidden;
- the world is stateful across actions;
- the agent must perform online, falsifiable experiments;
- actions are bounded and success is determined by environment state, not by persuasive text.

The detailed solve architecture may be summarized in prose or shown as a compact flowchart, but the README's primary diagram must describe the Asterion framework itself:

```text
CLI / host → selected provider → exact assembly → catalog / composer
           → exact implementations → runner → runtime / host services
```

The case study may then summarize the solve evidence path:

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

The README must not open with ARC artwork or read visually like an ARC-specific repository. Its first visual is the Asterion architecture or building-block model rendered in Markdown/Mermaid.

The replay GIF uses the ARC palette, nearest-neighbor scaling, and readable pacing. Multi-frame action timing remains visible. It is displayed as a compact application-case-study visual, approximately 320-380 CSS pixels wide rather than as a hero image. The final state holds longer than intermediate frames.

The supplied full-report screenshot is shown as an optional detail thumbnail near the application case study at approximately 420-480 CSS pixels wide. It must not span the full README content width or visually compete with the project architecture. Its caption explains that the report contains replay, frame diffs, evidence-cited narration, and post-solve understanding. The screenshot links conceptually to the standalone export instructions; it must not point to a local Desktop or ignored artifact path.

The existing Asterion ARC header artwork is omitted from the README. The real replay and report screenshot remain evidence inside the ARC application case study, not project branding.

## Verification

- Regenerate images directly from the committed run-story schema and the local sealed run artifact.
- Verify both README files contain mutual language links and matching section structure.
- Verify every CLI command against current `--help` output or the implementing source.
- Verify every architecture and result claim against current code, manifests, tests, or normalized run data.
- Render or inspect both Markdown files for broken relative links and image dimensions.
- Verify Asterion framework material precedes the ARC case study and occupies the clear majority of both README files.
- Verify the replay renders at approximately 320-380 pixels wide and the report screenshot at approximately 420-480 pixels wide.
- Run focused documentation link/format checks and the existing run-story tests; do not run provider-backed work.
- Do not modify the solve result, rerun the ARC environment, or invoke a model for this documentation update.
- Update GitHub About/Topics only after local documentation verification, then read the values back with `gh repo view`.
