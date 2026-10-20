# Asterion peer foundation

**Goal:** Keep Prime a product-independent harness on one Asterion Pi process. Give Native one host for multiple capability packages. Leave DCI as the retrieval package.

**Authority:** The user confirmed this shape on 2026-10-20 and asked to implement it in order. Decision D-2026-10-20-04. No paid model run, benchmark, official card, or L9 rerun is authorized.

## Packages

| ID | Status | Outcome | Depends on | Acceptance |
|---|---|---|---|---|
| P-PI-1 | done | One Pi process owner. Prime requests and closes sessions through `PiRpcSession`. The one-shot `pi.reference` facade uses the same `PiChildProcess`. | Closed completion worklist | Provider-free tests. Prime launch code does not signal a process group. `PiRpcSession` keeps `PiChildProcess`; `stop` and `force_close` reap through it, and `force_close` does not take the command lock. The one-shot facade uses that same spawn and reap. No model run. |
| P-NATIVE-1 | done | One Native provider assembles the `dci` package and the `controlled-code` package. | P-PI-1 | A provider-free assembly resolves both packages against `pi.reference`. Each package keeps its own behavior. The base does not import either package. |
| P-CITE-1 | done | `prime-*-native` packages cite a Prime receipt. | P-PI-1 | `prepare_prime_application` remains the Prime execution door. A citation package records media type, digest, and run identity. It does not contain a second Prime implementation. Provider-free tests. No model run. |

## Current slice

`P-PI-1`, `P-NATIVE-1`, and `P-CITE-1` are done. The Native provider `native` resolves application `native.packages@1.0.0` against `pi.reference`. The assembly names `controlled-code@1.0.0` and `dci@1.0.0`. Each package keeps the implementations from its own factory. The base does not import either package. The six `prime-*-native` packages record media type, digest, and run identity. They do not execute Prime. `prepare_prime_application` remains the Prime execution door. Operators P1 through P6 read that digest from the Prime runtime they already build. The worklist has no pending package.

## Boundary

IPython, tool allowlists, accepted notes, compaction content, and P7 admission stay in Prime. Framework behavior that more than one Native package needs becomes a Native package. The base does not gain domain tools or a second runner. Prime CLI scope stays undecided.
