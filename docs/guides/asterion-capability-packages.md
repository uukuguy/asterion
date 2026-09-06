# Asterion Capability Packages

Capability packages are portable payloads selected from explicit sources. The
portable payload contains only closed protocol documents and declared public
resources. Provider factories and local paths stay in the source declaration,
not in `capability-package.json`.

## Author Commands

```bash
asterion capability init ./my-package --package-id acme.demo
asterion capability validate ./my-package/payload
asterion capability inspect \
  --package acme.demo@0.1.0 \
  --source-id acme.demo.local-directory \
  --root /absolute/path/to/my-package \
  --payload-root payload \
  --module-path provider.py \
  --factory-name create_package \
  --payload-sha256 <validated-payload-sha256>
asterion capability test \
  --package acme.demo@0.1.0 \
  --source-id acme.demo.local-directory \
  --root /absolute/path/to/my-package \
  --payload-root payload \
  --module-path provider.py \
  --factory-name create_package \
  --payload-sha256 <validated-payload-sha256>
```

## Installed Application Extensions

An independently installed Python wheel may publish capability packages,
applications, and provider-owned runtime bindings. Extension Python code imports
only `asterion.capability_sdk` and `asterion.application_sdk` (besides the
standard library and its own package). The two SDKs provide the immutable
capability values and the application, runtime, and event contracts; they do
not expose discovery, composers, registries, runners, or host-service setup.

1. Put each portable capability payload under
   `asterion_capability_packages/<package-id>/<version>/payload/` in the wheel.
   Keep its manifests portable and free of commands, configuration, credentials,
   paths, and mutable state.
2. Publish an exact `asterion.capability_packages` entry point named
   `<package-id>@<version>`. Its selected factory opens that payload through
   `open_portable_payload` and returns an `InstalledCapabilityPackage` with
   exact capability implementation bindings.
3. Put every application assembly under a provider-owned resource root and
   publish an `asterion.applications` entry point. Its factory returns an
   `InstalledApplicationProvider` with exact application, package, and runtime
   identities. Provider-owned runtime factories use `RuntimeFactoryBinding`.
4. Publish `asterion.application_index` entries as
   `<application-id>__<version>` when the application should be selectable by
   its exact identity. Declare the Asterion API compatibility range in the
   wheel metadata, for example `asterion>=0.1.0,<0.2`.

Entry-point metadata discovery does not import provider modules. Provider code
is loaded only after exact selection, and installed extension code runs only
after the framework has composed the selected assembly and bound its declared
runtime. The copyable reference is
`tests/fixtures/extensions/distribution/` and is exercised by
`make test.public-extension`.

```bash
make test.public-extension
```

`validate` opens the portable payload and reports only public identity,
counts, and the payload digest. `inspect` uses an explicit local-directory
source declaration and does not import the provider module. `test` loads only
that selected provider after source identity validation, then runs the public
conformance kit without runtime, Agent, Judge, provider-backed, network, or
dataset work.

`pack` and `convert` currently validate their arguments and then report that
archive forms are unsupported. They do not write output until the archive-form
plan is approved.

## Source Boundary

Use exact local source arguments. Asterion does not scan parent directories,
search sibling repositories, mutate `sys.path`, choose latest versions, or
apply source precedence. Local roots, module paths, provider locators, and
private operator details are not printed in public output.

Built-in, installed-distribution, and local-directory packages are equivalent
source forms. If more than one exact source is visible, resolution fails closed
without an exact source lock—even when the verified payload digests match.
Metadata discovery never imports provider code. Loading the selected installed
extension crosses a trust boundary, so operators must install and select only
code they trust.

Every built-in package must retain a portable externalization fixture, pass the
public conformance kit, and prove equivalent public behavior through a clean
installed distribution and an explicit local source. DCI was validated in that
external-first order; its built-in registration does not make generic framework
code depend on DCI.

Portable manifests must not contain prompts, commands, executable paths,
credentials, provider configuration, environment values, private paths, or
mutable state. Source selection grants no execution authority; host services
and runtimes remain operator-injected after package selection.

Archive and registry source support is deferred. Adding either requires a
separate provenance, verification, trust, and lifecycle design.
