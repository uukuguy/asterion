# Git Recovery Closure — 2026-08-30

## Scope and safety boundary

This record closes the branch/worktree sprawl created by repeated H-024,
H-035, H-036, and callback verification. It does not push, rewrite, or update
`origin/main`.

- Verified integration head: `6e4343884031467ecfca796b8a48c04d1bd6ff8e`.
- Local `main` before promotion: `262b2fdf0085294e89078a6311c9034d489e4667`.
- Local `main` after promotion: `6e4343884031467ecfca796b8a48c04d1bd6ff8e`.
- Unchanged `origin/main`: `f1316bb780cf01406b99b8b549461cd02df24138`.
- Audit population: 54 registered worktrees, 19 distinct HEADs, four local
  branches, 14 dirty non-primary worktrees, and six distinct worktree HEADs
  not ancestral to promoted `main`.

## Recovery artifacts

Before any obsolete state is removed:

- 23 temporary refs under `refs/recovery/pre-phase3/` preserve the integration
  head, old named branch tips, old local main, and every distinct worktree HEAD.
- `.git/asterion-pre-phase3-recovery-20260830.bundle.tmp` is a verified,
  complete-history provisional bundle containing 28 refs: all local branches,
  all recovery refs, and `origin/main`.
- `.git/asterion-pre-phase3-uncommitted-20260830/` contains 12 non-empty
  full-index binary patches for tracked/index differences.
- `013-task5-untracked-source.tar.gz` contains exactly 14 untracked source or
  fixture files from the Task 5 verification tree. It contains no dependency,
  environment, cache, or build directory.
- High-confidence private-key and provider-token scans found no match in the
  retained patches or untracked-source archive.

Generated benchmark-suite temp directories and the H-024 `3th-party` symlink
are classified as reproducible/non-unique and are not copied into the
uncommitted archive. Ignored environments, `node_modules`, caches, Rust target
trees, build output, and private evidence are never retained.

## Local branch audit

| Branch | Audited tip before cleanup | Relationship and disposition |
|---|---|---|
| `main` | `6e4343884031` | Promoted verified integration head; retain. |
| `recovery/pre-consolidation-root-20260830` | `6e4343884031` | Same tip as `main`; remove after final bundle. |
| `h024-ecosystem-capabilities` | `3b2cd3217776` | Historical line preserved by recovery ref/bundle; remove. |
| `feature/prime-ecosystem-parity` | `67d2fc324b3c` | Historical divergent line and dirty journal preserved separately; remove after its worktree. |

## Worktree audit

`Dirty` is `tracked/untracked-root` count from porcelain status. `Copies` is
the number of registered worktrees at that exact HEAD. `Main ancestor` records
commit reachability only; divergent state is still retained in recovery
artifacts. `$REPO` denotes the current repository root and `$DARWIN_TMP` the
operator's Darwin temporary root; private absolute prefixes are intentionally
not published.

| # | Exact path | HEAD | Branch/state | Main ancestor | Dirty | Copies |
|---:|---|---|---|---|---:|---:|
| 1 | `$REPO` | `6e4343884031` | `main` | yes | 0/2 | 1 |
| 2 | `/private/tmp/asterion-debug.ZBgg4A` | `296c633c9107` | `detached` | yes | 0/0 | 4 |
| 3 | `/private/tmp/asterion-h024-base.98yRXN/worktree` | `296c633c9107` | `detached` | yes | 0/1 | 4 |
| 4 | `/private/tmp/asterion-h024-candidate.QOKuIt/worktree` | `296c633c9107` | `detached` | yes | 22/0 | 4 |
| 5 | `/private/tmp/asterion-h024-contract-fix` | `358d1064f79b` | `detached` | yes | 3/0 | 2 |
| 6 | `/private/tmp/asterion-h024-env-fix` | `537a31ad8485` | `detached` | yes | 2/0 | 2 |
| 7 | `/private/tmp/asterion-h024-final-gates` | `d98d1b058165` | `detached` | yes | 0/0 | 2 |
| 8 | `/private/tmp/asterion-h024-final2` | `ad99524563e5` | `detached` | yes | 6/0 | 1 |
| 9 | `/private/tmp/asterion-h024-final3` | `537a31ad8485` | `detached` | yes | 0/0 | 2 |
| 10 | `/private/tmp/asterion-h024-final4` | `4ae65abb4ac9` | `detached` | yes | 0/0 | 1 |
| 11 | `/private/tmp/asterion-h024-final5` | `28e29b6c68a7` | `detached` | yes | 1/0 | 1 |
| 12 | `/private/tmp/asterion-h024-final6` | `ef685f4c7838` | `detached` | yes | 0/0 | 1 |
| 13 | `/private/tmp/asterion-h024-gates` | `358d1064f79b` | `detached` | yes | 3/0 | 2 |
| 14 | `/private/tmp/asterion-h024-promotion-fix` | `d98d1b058165` | `detached` | yes | 3/0 | 2 |
| 15 | `/private/tmp/asterion-h024-verified-gates` | `9d7cf94524d6` | `detached` | yes | 0/0 | 1 |
| 16 | `/private/tmp/asterion-h035-clean.QqTOkz/wt` | `9abe7056880a` | `detached` | no | 3/6 | 1 |
| 17 | `/private/tmp/asterion-h036-a8.sWzqgA/repo` | `08c915b7a424` | `detached` | no | 0/6 | 10 |
| 18 | `/private/tmp/asterion-h036-b.DDXqvR/repo` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 19 | `/private/tmp/asterion-h036-detached-a5.5SrPtv/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 20 | `/private/tmp/asterion-h036-detached-a6.nycXYs/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 21 | `/private/tmp/asterion-h036-detached-a7.tPKd5i/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 22 | `/private/tmp/asterion-h036-detached-a8-fresh.6LSbQl/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 23 | `/private/tmp/asterion-h036-detached-a8.5hjyrN/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 24 | `/private/tmp/asterion-h036-detached-a8.C6CzD3/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 25 | `/private/tmp/asterion-h036-detached-a9.Lyqi5C/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 26 | `/private/tmp/asterion-h036-detached-probe1.NQttDY/wt` | `08c915b7a424` | `detached` | no | 0/0 | 10 |
| 27 | `/private/tmp/asterion-task10-045.8CEfrX/wt` | `04532ece2bda` | `detached` | yes | 0/0 | 4 |
| 28 | `/private/tmp/asterion-task10-296.Wxd8bF/wt` | `296c633c9107` | `detached` | yes | 9/0 | 4 |
| 29 | `/private/tmp/asterion-task10-candidate.rtGA0k/wt` | `04532ece2bda` | `detached` | yes | 16/0 | 4 |
| 30 | `/private/tmp/asterion-task10-clean.zsdk3b/wt` | `629f44ad3eec` | `detached` | yes | 0/0 | 1 |
| 31 | `/private/tmp/asterion-task10-preexisting.W3DJod/wt` | `04532ece2bda` | `detached` | yes | 0/0 | 4 |
| 32 | `/private/tmp/asterion-task10-red.FXlGMm/wt` | `04532ece2bda` | `detached` | yes | 0/0 | 4 |
| 33 | `/private/tmp/asterion-task5-verify.O5X39A` | `cb3aa9ac1190` | `detached` | yes | 10/5 | 1 |
| 34 | `$DARWIN_TMP/asterion-h036-b1.7B4YBd/asterion` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 35 | `$DARWIN_TMP/asterion-h036-b1.eNg06b/asterion` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 36 | `$DARWIN_TMP/asterion-h036-b2.9qydOD/asterion` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 37 | `$DARWIN_TMP/asterion-h036-b4.lvpZTH/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 38 | `$DARWIN_TMP/asterion-h036-confirm-d.mqRULV/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 39 | `$DARWIN_TMP/asterion-h036-confirmation-c.kpZ7XG/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 40 | `$DARWIN_TMP/asterion-h036-detached-a10.dCbeRt/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 41 | `$DARWIN_TMP/asterion-h036-detached-a10.m1wLlD/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 42 | `$DARWIN_TMP/asterion-h036-detached-a11.afaLJS/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 43 | `$DARWIN_TMP/asterion-h036-detached-a12.yrNslc/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 44 | `$DARWIN_TMP/asterion-h036-detached-a13.IJd9cG/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 45 | `$DARWIN_TMP/asterion-h036-detached-a9.dg0N9X/wt` | `45a5c041095e` | `detached` | no | 0/0 | 1 |
| 46 | `$DARWIN_TMP/asterion-h036-final-c3.wcAX61/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 47 | `$DARWIN_TMP/asterion-h036-final-d3.50H7FX/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 48 | `$DARWIN_TMP/asterion-h036-final-e.ObNjTX/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 49 | `$DARWIN_TMP/asterion-h036-final-f.Upnfvs/wt` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 50 | `$DARWIN_TMP/asterion-h036-final-g.GJCWSI/wt` | `c32074726cd5` | `detached` | no | 0/0 | 2 |
| 51 | `$DARWIN_TMP/asterion-h036-final-h.OKpeTZ/wt` | `c32074726cd5` | `detached` | no | 0/0 | 2 |
| 52 | `$DARWIN_TMP/asterion-h036-pass-c.KCGds5/asterion` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 53 | `$DARWIN_TMP/asterion-h036.3poTwk/asterion` | `ca3270e80a2f` | `detached` | no | 0/0 | 17 |
| 54 | `$REPO/.worktrees/prime-ecosystem-parity` | `67d2fc324b3c` | `feature/prime-ecosystem-parity` | no | 1/0 | 1 |

## Pending destructive closure

The provisional bundle and uncommitted archive are verified, but this audit
commit intentionally precedes destructive cleanup. The next controlled step is
to create the final bundle, remove worktrees 2–54 by exact registered path,
prune, delete the three obsolete local branches, remove temporary recovery
refs only after the final bundle covers them, and delete only the two audited
primary artifact roots. A final section will record the resulting one-worktree
steady state after it is observed.
