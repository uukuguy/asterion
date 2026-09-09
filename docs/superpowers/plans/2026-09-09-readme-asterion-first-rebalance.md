# Asterion-First README Rebalance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebalance both repository READMEs so Asterion's framework architecture and application model are primary, with ARC-AGI-3 presented as one compact evidence-backed application case study.

**Architecture:** Reorder and rewrite the existing bilingual Markdown without changing runtime code or solve evidence. Lead with Asterion's problem statement, contracts, dependency direction, building blocks, agent implementations, and application portfolio; place the existing ARC evidence after that foundation and reduce its visual and textual weight.

**Tech Stack:** Markdown, Mermaid, GitHub-flavored Markdown API, GitHub CLI, Python documentation checks.

## Global Constraints

- Asterion framework material occupies approximately 70-80% of each README; ARC-AGI-3 occupies approximately 20-30%.
- The first visual describes Asterion architecture; ARC artwork never acts as repository branding.
- Preserve the existing ARC claim boundary and exact run facts.
- Display the replay at 360 CSS pixels and the report screenshot at 460 CSS pixels.
- Keep the English and Simplified Chinese files structurally equivalent and mutually linked.
- Preserve native `asterion.prime` versus historical Prime Gateway separation.
- Do not rerun a model or ARC environment.
- Change only GitHub description and website after local verification; preserve the approved topic set and all other repository settings.

---

### Task 1: Rebalance the Bilingual Repository Introduction

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Consumes: current architecture documents, existing verified ARC assets, and current public CLI commands.
- Produces: matching project-first English and Chinese READMEs with `## Architecture` before `## Applications` and the ARC case study nested under the application portfolio.

- [ ] **Step 1: Rewrite the top-level project narrative**

Use this English section order and mirror it in Chinese:

```markdown
# Asterion
## Why Asterion
## Architecture
## Core building blocks
## Agent implementations
## Applications
### ARC-AGI-3 interactive reasoning
## Install and inspect
## External runtimes and resources
## Security and execution boundaries
## Development and promotion
## Compatibility and history
```

The opening must define Asterion as a composable multi-runtime agent application framework. `Why Asterion` explains deterministic composition, exact identities, explicit authority, replaceable runtimes, and verifiable evidence. `Architecture` contains the primary Mermaid flow from host through provider, assembly, composer, implementation binding, runner, runtime, and injected services.

- [ ] **Step 2: Make framework components and applications concrete**

Add a concise building-block table covering runtime protocol, capability package, application assembly, provider, runner, host service, and evidence. Add an agent-implementation table that identifies Asterion Prime and Asterion Native as peers and states Native's current control-provider boundary. Add an application table containing P1-P7, ARC-AGI-3/P7, DCI, and controlled-code so ARC is visibly one application among several.

- [ ] **Step 3: Compress the ARC application case study**

Keep only:

- one paragraph establishing the completed Level 1 and claim boundary;
- the replay GIF at `width="360"`;
- one compact metrics row or table;
- one short paragraph explaining hidden objectives, stateful interaction, falsifiable experiments, and environment-confirmed success;
- one short evidence-chain line;
- the report screenshot at `width="460"` plus the standalone report regeneration commands.

Remove the dedicated top-level ARC hero, long solve explanation, separate full solve diagram, and separate top-level evidence-preservation section. Move the four-layer artifact explanation into two concise paragraphs below the screenshot.

- [ ] **Step 4: Verify bilingual structure and project emphasis**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path

en = Path("README.md").read_text()
zh = Path("README.zh-CN.md").read_text()
assert en.index("## Architecture") < en.index("## Applications") < en.index("### ARC-AGI-3 interactive reasoning")
assert zh.index("## 架构") < zh.index("## 应用") < zh.index("### ARC-AGI-3 交互推理解题")
for text in (en, zh):
    assert 'width="360"' in text
    assert 'width="460"' in text
    assert text.count("ARC-AGI-3") < 15
    assert "asterion.prime" in text
    assert "asterion.native" in text
assert "README.zh-CN.md" in en and "README.md" in zh
print("Asterion-first README structure: PASS")
PY
make docs-check
uv run python -m unittest -v tests.test_prime_arc_agi_3_run_story
```

Expected: the structure check passes, documentation links pass, and all 10 ARC story tests pass without provider work.

- [ ] **Step 5: Verify GitHub-flavored rendering and commit**

Render both files through `gh api markdown` and assert that their architecture headings, language links, replay, report image, and exact widths appear in the returned HTML. Then commit only the two README files:

```bash
git add README.md README.zh-CN.md
git commit -m "docs: make Asterion primary in repository overview"
```

### Task 2: Align GitHub About With the Framework-First README

**Files:**
- No repository files except append-only `docs/status/JOURNAL.md` bookkeeping after verification.

**Interfaces:**
- Consumes: locally verified `#architecture` section and existing authenticated `gh` session.
- Produces: framework-first GitHub description and website while preserving the exact existing topic set.

- [ ] **Step 1: Update only description and website**

Run:

```bash
gh repo edit uukuguy/asterion \
  --description "Composable multi-runtime agent application framework for deterministic capability assembly, controlled execution, and verifiable AI applications." \
  --homepage "https://github.com/uukuguy/asterion#architecture"
```

- [ ] **Step 2: Read back and assert repository metadata**

Run `gh repo view uukuguy/asterion --json nameWithOwner,description,homepageUrl,repositoryTopics` and assert the exact description and homepage above. Assert topics remain exactly `agent-framework`, `agentic-ai`, `llm`, `multi-runtime`, `capability-system`, `interactive-reasoning`, `arc-agi-3`, `pi`, `python`, `typescript`, and `rust`.

- [ ] **Step 3: Record the correction**

Append one journal line naming the README commit and metadata read-back, then commit only `docs/status/JOURNAL.md` with message `docs: record Asterion-first README correction`.
