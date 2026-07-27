# Capability Package Author Workflow

`asterion capability` provides a provider-free author loop for canonical
capability package payloads. The commands do not accept source-discovery,
provider-locator, executable-command, environment, or monetary options.

## Initialize the checked-in template

Create a new source envelope beneath an existing directory:

```bash
uv run asterion capability init ./example-capability
```

`TARGET` must not already exist. The command copies Asterion's checked-in
minimal template, including:

```text
example-capability/
├── example/
│   └── provider.py
└── payload/
    ├── benchmark-suites/
    ├── capabilities/
    ├── capability-package.json
    ├── conformance/
    └── resources/
```

Initialization prints only the package ID, version, and canonical payload
digest. It never prints the target path.

## Validate and inspect a payload

Validate the exact portable closure:

```bash
uv run asterion capability validate ./example-capability/payload
```

Inspect its safe public identity:

```bash
uv run asterion capability inspect ./example-capability/payload
```

Both commands call the canonical payload API. `inspect` does not import package
code; it emits only package, capability, suite, and resource IDs plus content
digests. Validation failures use the body-free `asterion: command failed`
message so private paths and invalid document content do not reach public
output.

## Run conformance

Run the public SDK conformance checks for the canonical local envelope:

```bash
uv run asterion capability test ./example-capability
```

The first author-tool phase intentionally fixes the local factory to
`example.provider:create_provider` and the source ID to `example.local`. These
values are not CLI options. `test` loads that factory through the hardened
explicit-local-source adapter and then calls
`asterion.capability_sdk.run_capability_conformance`.

Because `test` imports code from the explicitly selected local envelope, run it
only for source you trust. Conformance does not execute capability
implementations, runtimes, model services, benchmarks, or full datasets.

## Staged archive boundary

Archive materialization and form conversion require a separate approved
design. The exact selectors are accepted now so automation can detect the
boundary without mistaking either operation for an implemented feature:

```bash
uv run asterion capability pack example.package@1.0.0
uv run asterion capability convert example.package@1.0.0
```

Both commands validate the exact `PACKAGE@VERSION` argument and exit with an
explicit `unsupported pending archive-form approval` result. They do not
create, modify, or convert package material.
