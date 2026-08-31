# Native Small Verification Host Design

## Goal

Wire the existing operator-owned Prime/DeepSeek configuration into the Native
small-verification preset without exposing configuration or granting framework
code authority to read `.env`.

## Decision

Use the existing Prime Native RLM bounded runtime as the execution host. It
already supplies a model allow-list, a minimal credential environment, private
workspace lifecycle, bounded execution, and body-free receipt reduction. Do
not create a second direct provider client from the DCI configuration, and do
not move `.env` loading into `asterion.control`.

## Boundaries

`src/asterion/applications/` owns configuration resolution and construction of
the host. `src/asterion/control/providers/native/` continues to receive only a
`NativeSmallVerificationPresetResolver`, immutable reservation, and host.

The public operation remains parameter-free. Its fixed reservation is derived
from the exact selected model identity and fixed finite controls held in
operator code. It permits one run only. Failure to read private configuration,
prepare the bounded Prime runtime, complete the run, validate the result, or
write a redacted receipt returns only `External-limited` or `INCOMPLETE`.

## Execution and evidence

The application bridge invokes the established `run_native_rlm_experiment`
path, never raw provider APIs. It projects the private result into a
body-free Native bounded receipt that identifies only the two required feature
IDs, opaque/digested identities, terminal status, bounded usage, and external
operation counters. The reducer accepts no receipt unless both bounded feature
claims and redaction invariants are exact.

`make check` and all provider-free targets remain non-executing. A dedicated
explicit small-verification command may invoke exactly one provider operation;
its public output does not include prompts, answers, credentials, paths, raw
provider output, or internal controls.

## Tests

Provider-free unit tests cover `.env` configuration isolation, exact model
selection digest, fixed reservation construction, missing configuration,
redaction, duplicate-use rejection, receipt validation, and public CLI shape.
The explicit host command is documented as bounded external work and is never
called by ordinary tests or promotion checks.
