# Generic P7 Live Route Optimizer Design

## Goal

Use the existing game-neutral offline ARC optimizer before a P7 live run so a
shorter route can be supplied to the model, while preserving the verified
baseline whenever optimization is unavailable or unsuccessful.

## Design

`run_live()` loads the strongest sealed route for the exact game, converts its
transitions into immutable `PlannerAction` values, and calls
`optimize_arc_route()` with a finite candidate budget and removal bound. Every
candidate uses a fresh ARC engine. Only a candidate whose replay reaches the
requested level with the exact identity and action count is accepted.

The prompt receives the optimized route as a generic replay hypothesis. If no
verified prefix exists, the route is unchanged. If optimization raises or
returns no shorter verified candidate, the original route remains the fallback.
No game ID, coordinate, or puzzle-specific branch is added.

Private run diagnostics record baseline length, optimized length, candidates
replayed, removed indices, and fallback/error status. Public receipts remain
unchanged and never expose prompts, frames, or credentials.

## Verification

- Unit tests cover transition conversion, successful shortening, and safe
  fallback when the optimizer fails.
- The existing optimizer and P7 focused suites must remain green.
- A live BP35 L1 witness is run with debug transcript enabled; the report
  distinguishes offline candidate search from online model actions.
