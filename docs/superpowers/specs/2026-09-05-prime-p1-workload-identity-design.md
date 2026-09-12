# Prime P1 Workload Identity Migration

## Decision

The existing P1 `WORKLOAD_DIGEST` is the hash of the final result projection.
It must not be used as the identity of the work the model is authorized to
perform. Preserve it as `expected_result_sha256` and define the workload as
canonical bytes included in the fixed image fixture.

`image/fixture/workload.json` is the sole workload truth. It contains only
fixed scenario identity, IPython-only tool/count constraints, fixture hashes,
required oracle/mutation facts, and the expected result digest. It contains no
prompt, credential, command, path, provider/model choice, or environment
value. The authority owns the fixed private prompt and binds its private
request digest later.

## Shape

```json
{
  "capability_ref":"prime.ipython-coding@1.0.0",
  "expected_result_sha256":"f4eb…",
  "final_oracle_passed":true,
  "format":"asterion.prime-ipython-coding-workload/v1",
  "initial_oracle_passed":false,
  "ipython_tool_call_count":1,
  "model_request_count":1,
  "model_tools":["ipython"],
  "oracle_sha256":"…",
  "prime_sdk_ref":"prime-agent@0.7.1",
  "starter_sha256":"…",
  "version":"1.0.0",
  "workload_id":"prime.ipython-coding",
  "workspace_mutation_required":true
}
```

`sha256(canonical workload bytes)` is the new workload identity. Parsing is
strict canonical UTF-8 JSON with exact keys and relations. The first slice
defines and validates this artifact only; it does not change the launcher,
request contract, image lock, or runtime. Those consumers migrate together in
the following slice, without compatibility fallback.

## Verification

Development tests cover the exact golden bytes/digest, strict rejection of a
representative malformed artifact, separation of workload and result digests,
and zero Docker/network/provider/subprocess work. Consumer migration later
must prove all lock/launcher/contract projections agree on the new digest.
