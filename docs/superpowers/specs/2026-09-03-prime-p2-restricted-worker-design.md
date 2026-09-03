# Prime P2 Restricted Long-Context Worker Design

## Scope

Implement formal bounded evidence for prime.programmatic-long-context/v1
through a separate sealed worker. The existing provider-free compatibility
fixture remains useful mechanical evidence but can never become bounded
evidence. P1 behavior remains unchanged. P3–P7 remain External-limited.

## Closed Boundary

The only accepted P2 role is prime.programmatic-long-context. Its request
contains only exact role, image, run, challenge, workload digest, and finite
limits. It never contains corpus content, prompts, programs, paths, commands,
environment values, credentials, or provider configuration.

P2 has a separate image, entrypoint, seccomp identity, fixed workload digest,
fixture corpus, oracle, and result schema. It rejects P1 identities; P1 rejects
P2 identities. Shared lifecycle types may be reused, but no generic worker
descriptor, role parameter, or caller-selected command is introduced.

## Private Protocol

The P2 launcher uses one bounded canonical sequence:

self-check → exact release identity → host-brokered model response → real Prime
IPython-only tool call → fixed oracle → session disposal → one completion.

Frames bind worker, run, challenge, workload, sequence, kind, and bounded
bytes. Extra, reordered, duplicate, malformed, oversized, post-terminal, or
deadline-expired frames fail closed. The host broker response is committed to
the executed program digest; raw prompts, programs, corpus, paths, output, and
model payloads never enter public values.

The sole completion contains normalized safe facts: IPython-only arrays,
corpus identity/count, selected count, model-response/program/aggregate/oracle
digests, tool-call count, success, and session-disposed. Its canonical result
bytes determine the restricted-worker result digest.

## Evidence

A P2 bounded reducer requires all of:

- exact P2 worker-bound result and cleanup lifecycle;
- exact P2 scenario/role boundary receipt;
- revoked/quiescent bounded host broker receipt;
- causal response/program digest binding;
- exact fixed corpus, oracle, workload, and normalized result identities.

It issues only through the existing boundary evidence gate. Compatibility
reports, local tool calls, or their disposed/reaped assertions cannot satisfy
any of these conditions.

## Platform and Verification

The image recipe is platform-neutral. Promoted arm64 and amd64 execution
digests are separate explicit locks; a multi-architecture index does not prove
a platform-specific run. No host detection, fallback, emulation, or implicit
platform selection is allowed.

Provider-free tests cover denial, role/workload separation, protocol ordering,
caps, canonicality, redaction, broker binding, cleanup, and acceptance
orchestration. Docker/model/network live execution is separately authorized
and cannot be claimed by those tests.

