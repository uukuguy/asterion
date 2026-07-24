# Live Session Checkpoint

> Updated: 2026-07-24 18:49. **Session remains active — not a final handoff.**

## TL;DR

- `docs/architecture/dci-capability-audit.md` is the authoritative mapping from
  paper/GitHub claims to Asterion code, reachability, evidence, and gaps.
- Audit and three implementation plans are committed as `bf4bbfe`.
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
  and one Node-version CI assertion. Do not report it as passing.

## Next steps

Execute, in order:

1. `docs/superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md`
2. `docs/superpowers/plans/2026-07-24-asterion-application-authority.md`
3. `docs/superpowers/plans/2026-07-24-dci-provenance-reproduction.md`

Start with Task 1 of the protocol plan using TDD. Keep commits atomic as
specified by each task.

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
