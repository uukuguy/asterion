# DCI Capability Architecture and Gap Audit

> Status: approved design baseline, 2026-07-24. This document is an
> implementation audit, not evidence that a provider-backed benchmark or a
> published paper score was rerun.

## Purpose and sources

This audit maps the public claims of DCI to the authoritative standalone
Asterion implementation. It distinguishes four states that must not be
collapsed:

- **Packaged** — a resource is included in the source tree or wheel.
- **Bound** — an installed provider exposes the resource through an exact
  application binding.
- **Executable** — the bound graph resolves to one runtime and one exact
  implementation for every executable package.
- **Verified** — a named command passed inside its stated boundary.

The external baselines are:

- [DCI paper, arXiv:2605.05242v1](https://arxiv.org/abs/2605.05242)
- [DCI-Agent-Lite GitHub repository](https://github.com/DCI-Agent/DCI-Agent-Lite)
- GitHub source pin inspected for this audit:
  [`271f37e71f053bf0c99c05ce6d2fb53b841d922e`](https://github.com/DCI-Agent/DCI-Agent-Lite/commit/271f37e71f053bf0c99c05ce6d2fb53b841d922e)

The paper, its appendix, and the GitHub implementation are separate sources.
Where they differ, Asterion must record the selected source rather than
silently treating the GitHub implementation as the paper method.

## Architectural boundary

Asterion has two DCI-facing execution planes:

```text
generic framework plane

asterion CLI
  → selected installed provider
    → exact application and runtime-specific assembly
      → explicit local package catalog
        → deterministic composer
          → exact implementation bindings
            → sequential composed runner
              → selected runtime and injected host services

DCI product plane

asterion-dci CLI
  → DCI configuration and preflight
    → Pi or Claude Code execution
      → run evidence and resume
        → Judge or IR metric
          → benchmark analysis and export
            → paper contracts and reproduction comparison
```

The generic plane must stay domain-neutral. DCI configuration, prompts,
datasets, credentials, Judge behavior, and reproduction policy belong to the
product plane or to explicitly injected host services.

## Installed application reachability

The `dci-agent-lite` provider exposes exactly two application identities:

| Application | Runtime assemblies | Executable packages | Product meaning |
| --- | --- | --- | --- |
| `dci.research-capability@1.0.0` | Pi, Claude Code | `dci.research` | One local-corpus research run |
| `dci.complete-application@1.0.0` | Pi, Claude Code | research, evaluation, benchmark, analysis, export | One question-and-gold five-stage verification chain |

`dci.complete-application` is not a full dataset benchmark. Its benchmark
implementation emits `total=1` and `judged=1`; the batch benchmark belongs to
the `asterion-dci benchmark` product command.

Two packaged resources are not provider-reachable:

- `applications/dci_agent_lite/assemblies/dci-local-research.json`
- `capabilities/dci_research/manifests/protocol-observability.json`

Installed acceptance currently counts six packaged assemblies while the two
providers bind five assemblies in total. Therefore its
`application-assemblies` result proves packaged inventory, not provider
reachability or executable closure.

## DCI README claim mapping

| Upstream claim | Asterion evidence | Status | Qualification |
| --- | --- | --- | --- |
| Direct access to raw corpus through terminal tools | Pi and Claude Code research paths expose read/search tools | Implemented | The generic manifest names `filesystem.read`; corpus authority remains implicit in runtime cwd/configuration |
| No fixed retriever or hosted retrieval API | Research implementation delegates search strategy to the Agent | Implemented | Model-provider calls remain external operations |
| Zero index, embeddings, vector database, or offline build | No index construction or retrieval database exists in the product path | Implemented | Resource setup downloads or validates corpora but does not index them |
| Minimal Pi plus bash/read workflow | `asterion-dci` defaults to Pi and `read,bash` | Implemented with divergence | Installed complete Pi forces `read,grep`, so it is a restricted verifier rather than the faithful open-bash setup |
| Private/local document assistant | Corpora remain operator-owned local files and are not uploaded to a hosted retrieval service | Partially supported | Relevant document content can still be sent to the selected model provider; do not claim that data never leaves the machine |
| L0–L4 context management | Five immutable context profiles and a TypeScript Pi extension are packaged | Partial | Numeric settings match the paper table; L3/L4 behavioral equivalence is not yet proven |
| QA and IR benchmark coverage | Thirteen dataset identities and sixteen experiment scopes are packaged | Implemented as contracts | Full datasets and published scores were not rerun |
| Reported benchmark superiority | Reproduction targets and comparison schemas exist | Not verified | A contract or dry-run plan is not experimental evidence |

## Dataset and launcher reconciliation

The official GitHub README exposes eleven unique datasets through twelve
launchers: one BrowseComp-Plus dataset with two configurations, six QA
datasets, and four BRIGHT datasets. Asterion adds ArguAna and SciFact from the
paper's BEIR evaluation, producing thirteen dataset identities and fourteen
standalone launchers.

The two BEIR launchers are Asterion additions based on the paper and must be
labelled as such. They are not GitHub launcher parity.

The README describes the six QA datasets as fifty examples each. The paper
appendix instead uses the full Bamboogle test set of 125 examples and random
fifty-example selections for the other QA datasets. Asterion correctly models
the paper-full Bamboogle scope separately and does not bind the upstream
sample-fifty launcher to that scope.

## Package graph audit

The complete application declares:

```text
policy.local-corpus
  → dci.research
    → dci.evaluation
      → dci.benchmark
        → dci.analysis
          → dci.export
```

Portable artifacts order the executable stages. However, the question, gold
answer, predicted answer, and private output directory also pass through
`DciCompleteAttemptStore`. The artifacts prove stage continuity but are not the
complete data flow.

The following boundary gaps remain:

1. Pi implementations can invoke `EnvironmentDciRunExecutor` directly instead
   of using the selected `AgentRuntimeClient`; Claude Code uses the runtime
   client.
2. Runtime cwd, provider, model, tools, and Judge configuration can be resolved
   again during execution rather than being fixed in the resolved plan.
3. Judge access is environment-owned but is neither declared as an assembly
   host capability nor injected as a read-only service.
4. Local corpus authority is represented by runtime cwd and environment
   configuration, not an explicit operator-owned host service.
5. `complete_application_identity()` hashes `complete.py`, manifests, and
   assemblies but not all imported implementation modules that affect
   evaluation, analysis, bridging, and Judge behavior.
6. The benchmark reuse identity does not include a transitive implementation
   digest.

## Protocol and composition audit

Read-only minimal counterexamples on 2026-07-24 produced these results:

| Counterexample | Current result | Required invariant |
| --- | --- | --- |
| `tool.call` followed by terminal event without a result | Accepted | Every call has exactly one result before terminal |
| Runtime ID `../runtime` | Accepted | IDs use the canonical identifier grammar |
| Unsorted runtime/request/start capability arrays | Accepted | All contract arrays are sorted and unique |
| Host and package both provide one capability | Accepted; host precedence can remove the package dependency | Provider overlap fails closed |
| Multiple packages emit the same event | Accepted | Multi-provider semantics must be explicit; v1 should reject ambiguity |
| Multiple packages produce the same artifact media type | Accepted | Multi-provider semantics must be explicit; v1 should reject ambiguity |
| Mutation of `PackageCatalog.entries[*].manifest` | Changes later `select()` output | Catalog snapshots are deeply immutable |
| Package declares output but returns none | Accepted | v1 must define whether declarations are allowed or guaranteed output |
| Duplicate event instances or multiple artifacts of one media type | Accepted | Cardinality must be explicit |

The TypeScript runtime validator consumes shared fixtures. Python lacks a
direct shared-fixture protocol test, and the composer and catalog lack direct
unit-test surfaces. The existing unmatched-tool fixture checks a result with no
call; it does not check a call that remains unresolved at terminal.

### Approved v1 interpretation

The implementation plans use these semantics:

- Runtime, application, package, capability, policy, event, and media-type IDs
  use their contract's canonical grammar.
- Arrays documented as canonical are sorted and unique in schema-adjacent
  validators in both languages.
- Every tool call has exactly one later result before the terminal event.
- Provider overlap across host, runtime, and packages is ambiguity and fails
  closed.
- `emits_events` and `produces_artifacts` describe allowed output types.
  Cardinality remains implementation-specific in v1; empty output is allowed
  unless a package-specific implementation contract requires an output.
- Artifact IDs are unique across one complete application result.
- Package inputs and results, catalog snapshots, resolved plans, and validated
  TypeScript values must not expose mutable contract state.
- Adding manifest fields for artifact IDs, cardinality, or richer routing
  requires a new protocol version rather than silently extending v1.

## Paper, GitHub, and Asterion experiment semantics

Three provenance families are approved:

| Family | Authority | Purpose |
| --- | --- | --- |
| `paper-reference/*` | Paper and appendix only | Reproduce reported methodology; unreported values remain explicit unknowns or operator-supplied parameters |
| `upstream-github/<commit>/*` | One exact GitHub commit | Reproduce the public implementation, including behavior that differs from the paper |
| `asterion-safe/*` | Asterion contracts | Preserve stricter validation, safer defaults, and intentionally improved metrics |

They must have distinct prompt, Judge, metric, runtime, dataset-selection, and
implementation identities. Results from different families are not
cache-compatible or directly labelled as equivalent.

### Prompt and Judge differences

- Asterion QA uses the short GitHub prompt plus an Asterion sentence requiring
  a non-empty final answer. It is not the detailed QA prompt in paper
  Appendix C1.
- The IR prompt closely follows the GitHub implementation and paper method.
- Asterion includes a final-answer recovery prompt that is not part of the
  reported paper contract.
- The paper Judge asks GPT-4.1 for extracted answer, yes/no correctness,
  reasoning, and confidence.
- Asterion and the inspected GitHub commit use a JSON object with
  `is_correct`, `normalized_prediction`, and `reason`. The inspected GitHub
  default Judge is GPT-5.4-nano, while the paper reports GPT-4.1.

The current `dci.paper-answer-judge/gpt-4.1/v1` label points at an
Asterion-owned JSON schema rather than the Appendix C3 semantic contract and
must be corrected before paper-comparable scoring.

### Ranking metric difference

The inspected GitHub implementation computes NDCG from the returned list
without deduplication. Repeating one relevant document twice can produce a
score of approximately `1.63093`. Asterion deduplicates first and clamps the
result to `[0,1]`.

The Asterion behavior is safer but is not exact GitHub parity. The two metrics
need separate identities:

- `ndcg@10-binary-upstream-list/v1`
- `ndcg@10-binary-deduplicated/v1`

The paper calls the metric NDCG@10 but does not specify duplicate handling, so
paper-reference must record this as an unresolved method detail rather than
silently selecting either implementation.

### Resolution metric difference

Coverage and localization formulas match the paper:

```text
coverage-any  = 1 when at least one gold document is surfaced
coverage-mean = surfaced-gold / all-gold
coverage-all  = 1 when every gold document is surfaced

ν(x) = max(1, ceil(characters(x) / cseg))
ψ(a,b) = max(1 - log(a) / log(b), 0)
```

The paper does not report a numeric `cseg` or a read/evidence overlap
threshold. Asterion hard-codes `4096` characters and `0.5` overlap in its paper
ablation rows; these are Asterion-defined parameters and must be labelled.

Trajectory alignment is not yet comparable to the paper:

- exact `path:line:text` grep output is validated against the corpus;
- a read result must occur uniquely in the gold document, otherwise it falls
  back to full-document localization;
- bash pipelines return only full-document fallbacks for gold document paths
  literally present in the command;
- dominant paper patterns such as `rg | head` and `rg | rg` normally expose
  paths in output rather than as command arguments, so current alignment can
  miss both coverage and localization;
- path-only output is not recognized as surfaced evidence.

## Full reproduction boundary

`asterion-dci paper describe` currently reports
`paper_full_executable=false`. A dry-run can enumerate thirteen datasets,
sixteen scopes, 1,978 Agent operations, and 1,455 Judge operations, but it does
not execute them.

The current full-execution authorization is an in-memory object. The
`paper reproduce --authorize-full` command can issue the object and then exits;
the benchmark CLI has no supported route to consume that authority. The
estimated budget is metadata, accepts zero, and is not an enforced operation
or currency cap.

Reproduction comparison consumes a `RunManifest`, but production benchmark
output has no complete path that compiles its evidence into that manifest.
Only the DCI-Agent-CC main target is represented; Lite and the tool, context,
and corpus ablations do not form a complete executable target matrix.

## Prioritized gap register

| ID | Priority | Gap | Completion evidence |
| --- | --- | --- | --- |
| P1 | Blocker | Runtime v1 accepts noncanonical arrays/IDs and unresolved tool calls | Shared Python/TS valid and invalid fixture suite passes |
| P2 | Blocker | Composer accepts hidden host precedence and multi-provider ambiguity | Direct composition matrix rejects every overlap |
| P3 | High | Catalog and TS validation return mutable contract state | Mutation tests fail before and pass after deep snapshotting |
| A1 | Blocker | Generic CLI imports DCI configuration and `.env` contaminates provider-free tests | Generic CLI tests pass from repository cwd with sentinel `.env` |
| A2 | High | Provider acceptance counts inventory rather than executable closure | Report separately proves packaged, bound, composed, bound-implementation counts |
| A3 | High | Pi bypasses selected runtime and execution re-resolves authority | Both runtimes execute only through the selected runtime client |
| A4 | High | Corpus and Judge are implicit environment services | Assembly-declared, host-injected service preflight and redaction tests pass |
| E1 | Blocker | `paper-reference` mixes paper, GitHub, and Asterion semantics | Three distinct immutable provenance families and cache keys exist |
| E2 | High | Context L3/L4 behavioral parity is unproven | Golden trajectory tests cover thresholds, retained turns, summary gating, failure limit |
| E3 | High | Pipeline/path-only evidence is missed | Hand-calculated trajectory fixtures match expected coverage/localization |
| E4 | High | Full authorization and budget are not executable authority | One authorized bounded scope consumes authority once and enforces a positive cap |
| E5 | High | Benchmark evidence cannot compile into comparison input | Validated RunManifest is emitted and accepted by compare without manual conversion |
| D1 | Medium | Documentation overstates CLI neutrality, closure, paths, and verification | `make docs-check` and claim audit pass |

## Delivery sequence

Implementation is split into three independently reviewable plans:

1. [Protocol and composition hardening](../superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md)
2. [Application authority and executable closure](../superpowers/plans/2026-07-24-asterion-application-authority.md)
3. [DCI provenance and reproduction parity](../superpowers/plans/2026-07-24-dci-provenance-reproduction.md)

The order is intentional. Experimental evidence must not be promoted through
an ambiguous or mutable framework graph, and provider-backed work must not
start until authority and cost boundaries are explicit.

## Verification snapshot

Provider-free checks observed during the audit:

```text
uv run asterion list
  PASS: controlled-code and dci-agent-lite discovered

uv run asterion describe --provider dci-agent-lite
  PASS: product description rendered without provider requests

uv run asterion verify --provider dci-agent-lite --level acceptance
  PASS: inventory closure; provider-backed operations 0; full dataset no

uv run asterion-dci paper describe
  PASS: 13 datasets, 16 scopes, 20 ablation rows, 5 context profiles
  paper_full_executable=false
```

Focused Python and TypeScript suites passed earlier in this audit. The full
`make check` was not green: three generic CLI tests were contaminated by the
repository `.env`, and one CI assertion expected Node 22.19 while the active
environment exposed Node 20. These failures remain open and must not be
reported as PASS.

No provider-backed benchmark or published paper score was rerun for this
audit.
