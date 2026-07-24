# Live Session Checkpoint

> Updated: 2026-07-24 21:13. **Session remains active — not a final handoff.**

## TL;DR

- `docs/architecture/dci-capability-audit.md` is the authoritative mapping from
  paper/GitHub claims to Asterion code, reachability, evidence, and gaps.
- Audit and three implementation plans are committed as `bf4bbfe`; approved
  execution-plan corrections are committed as `775710b`.
- The user approved separate `paper-reference`, exact
  `upstream-github/<commit>`, and `asterion-safe` experiment families.
- Work is split into three independently testable plans: protocol/composition,
  application authority, then DCI provenance/reproduction.
- No provider-backed benchmark or published score was rerun.

## Where things stand

- Installed acceptance passes with zero provider operations, but it currently
  proves inventory counts rather than every executable assembly.
- Read-only counterexamples prove unresolved tool calls, noncanonical runtime
  IDs/arrays, host/package overlap, multi-provider event/artifact edges, and
  mutable catalog state are accepted.
- Asterion deduplicated NDCG intentionally differs from the inspected GitHub
  implementation; paper duplicate semantics are unreported.
- Prompt, Judge, trajectory alignment, context behavior, and full
  authorization/reproduction differences are recorded in the audit.
- Full `make check` remains red on three `.env`-contaminated generic CLI tests
  and one Node-version CI assertion. The application-authority plan now owns
  both corrections; do not report the full gate as passing before that plan.
- Protocol Task 7 now removes fictional host edges from both DCI and
  controlled-code graphs.
- Application Task 5 now uses a domain-neutral exact
  `asterion.host_services` factory registry with opaque generic CLI options.
- Protocol Tasks 1–2 are implemented and independently reviewed clean:
  runtime IDs/arrays are canonical across Python, TypeScript, and schemas;
  every runtime tool call must have a matching result before termination.
- Built-in Claude and Pi capability mappers now emit sorted, deduplicated
  capabilities, closing the regression found during Task 1 review.
- Protocol Tasks 3–6 are implemented and independently reviewed clean:
  TypeScript results are deeply immutable; package catalogs store frozen
  snapshots; composition rejects every provider ambiguity; and composed runs
  transport one immutable host/upstream evidence snapshot.
- Task 6 intentionally exposes three product tests whose assemblies declare
  fictional runtime-internal host edges. Approved Task 7 owns that cleanup.
- Protocol Task 7 removed those fictional DCI/controlled-code edges and its
  43 focused tests pass.
- Application-authority Task 1 was pulled forward to remove generic CLI DCI
  configuration authority. CLI/standalone/runtime-default suites pass, and
  `make promotion-check` now passes 18 commands with zero provider operations.
- The tracked root instruction symlink was replaced by portable
  `CLAUDE.md` content `@AGENTS.md`; CI now uses exact Node `22.19.0`.

## Next steps

Execute, in order:

1. `docs/superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md`
2. `docs/superpowers/plans/2026-07-24-asterion-application-authority.md`
3. `docs/superpowers/plans/2026-07-24-dci-provenance-reproduction.md`

Resume with Task 8 of the protocol plan. Protocol Tasks 1–7 and pulled-forward
Application Task 1 are recorded in
`.superpowers/sdd/progress.md`; keep commits atomic as specified by each task.

## Don't go down these paths again

- Do not treat packaged, bound, composed, executable, and verified as synonyms.
- Do not claim `dci.complete-application` is a full dataset benchmark; it is a
  one-question five-stage chain.
- Do not label Asterion-safe prompt, Judge, NDCG, or localization parameters as
  paper semantics.
- Do not make full execution authority persist through `.env`, cache, or prior
  evidence.
- Do not rerun a provider-backed example without explicit operator
  authorization and a finite positive budget.

## Ready-to-paste commands

```bash
git status --short
sed -n '1,220p' docs/architecture/dci-capability-audit.md
sed -n '1,220p' docs/superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md
```
