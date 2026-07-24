import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

import {
  ProtocolValidationError,
  validateAssemblyManifest,
  validateEventStream,
  validatePackageManifest,
  validateRunRequest,
  validateRuntimeManifest,
} from "../dist/src/index.js";

const fixtures = new URL("../../../../tests/fixtures/agent_runtime/v1/", import.meta.url);
const packageFixtures = new URL(
  "../../../../tests/fixtures/packages/v1/",
  import.meta.url,
);
const referenceManifestRoots = [
  new URL("../../../../src/asterion/capabilities/dci_research/manifests/", import.meta.url),
  new URL("../../../../src/asterion/capabilities/controlled_code/manifests/", import.meta.url),
];
const sourceDirectory = new URL("../src/", import.meta.url);
const schemaCopyScript = new URL("../scripts/copy-schemas.mjs", import.meta.url);
const assemblyFixtures = new URL(
  "../../../../tests/fixtures/assembly/v1/",
  import.meta.url,
);
const referenceAssemblyRoots = [
  new URL(
    "../../../../src/asterion/applications/dci_agent_lite/assemblies/",
    import.meta.url,
  ),
  new URL(
    "../../../../src/asterion/applications/controlled_code/assemblies/",
    import.meta.url,
  ),
];

async function readJson(name) {
  return JSON.parse(await readFile(new URL(name, fixtures), "utf8"));
}

async function readPackageJson(name) {
  return JSON.parse(await readFile(new URL(name, packageFixtures), "utf8"));
}

async function readJsonl(name) {
  return (await readFile(new URL(name, fixtures), "utf8"))
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

test("validates the shared runtime manifest fixtures", async () => {
  const copyScript = await readFile(schemaCopyScript, "utf8");
  for (const source of [
    "../../../../schemas/agent-runtime/v1",
    "../../../../schemas/packages/v1/package-manifest.schema.json",
    "../../../../schemas/assembly/v1/assembly.schema.json",
  ]) {
    assert.ok(copyScript.includes(source), source);
  }

  const valid = await readJson("valid-runtime-manifest.json");
  const invalid = await readJson("invalid-runtime-manifest.json");

  assert.deepEqual(validateRuntimeManifest(valid), valid);
  assert.throws(() => validateRuntimeManifest(invalid), ProtocolValidationError);
});

test("validates shared requests and complete event streams", async () => {
  const request = {
    protocol: "dci.agent-runtime/v1",
    run_id: "typescript-host",
    input: { text: "Investigate the fixture corpus" },
    requested_capabilities: ["filesystem.read"],
  };
  assert.deepEqual(validateRunRequest(request), request);
  assert.throws(
    () => validateRunRequest({ ...request, requested_capabilities: ["shell", "shell"] }),
    ProtocolValidationError,
  );

  for (const name of [
    "valid-research.jsonl",
    "valid-cancelled.jsonl",
    "valid-artifact.jsonl",
  ]) {
    const events = await readJsonl(name);
    assert.deepEqual(validateEventStream(events), events);
  }
  for (const name of [
    "invalid-sequence-gap.jsonl",
    "invalid-unmatched-tool-result.jsonl",
    "invalid-post-terminal.jsonl",
  ]) {
    const events = await readJsonl(name);
    assert.throws(() => validateEventStream(events), ProtocolValidationError);
  }
});

test("validates the shared package manifest fixture", async () => {
  const valid = await readPackageJson("valid-capability.json");

  assert.deepEqual(validatePackageManifest(valid), valid);
});

test("rejects every shared invalid package manifest fixture", async () => {
  for (const name of [
    "invalid-unknown-field.json",
    "invalid-duplicate-edge.json",
    "invalid-package-id.json",
    "invalid-forbidden-command.json",
  ]) {
    const invalid = await readPackageJson(name);
    assert.throws(() => validatePackageManifest(invalid), ProtocolValidationError);
  }
});

test("rejects package edge arrays that are not sorted", async () => {
  const valid = await readPackageJson("valid-capability.json");
  const unsorted = {
    ...valid,
    provides_capabilities: ["z.last", "a.first"],
  };

  assert.throws(() => validatePackageManifest(unsorted), ProtocolValidationError);
});

test("validates every checked-in reference package manifest", async () => {
  const entries = (
    await Promise.all(
      referenceManifestRoots.map(async (root) =>
        (await readdir(root))
          .filter((name) => name.endsWith(".json"))
          .map((name) => ({ name, root })),
      ),
    )
  ).flat();
  const names = entries.map(({ name }) => name).sort();
  assert.deepEqual(names, [
    "code-quality-evaluation.json",
    "code-quality-workflow.json",
    "controlled-code-policy.json",
    "dci-analysis.json",
    "dci-benchmark.json",
    "dci-evaluation.json",
    "dci-export.json",
    "dci-research.json",
    "execution-audit-observability.json",
    "local-corpus-policy.json",
    "protocol-observability.json",
  ]);
  for (const { name, root } of entries) {
    const manifest = JSON.parse(
      await readFile(new URL(name, root), "utf8"),
    );
    assert.deepEqual(validatePackageManifest(manifest), manifest);
  }
});

test("keeps package composition outside the TypeScript host", async () => {
  const sources = await Promise.all(
    (await readdir(sourceDirectory))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => readFile(new URL(name, sourceDirectory), "utf8")),
  );
  const publicSource = sources.join("\n");

  assert.doesNotMatch(publicSource, /composePackages|PackageComposition/);
});

test("validates the shared assembly fixtures", async () => {
  const valid = JSON.parse(
    await readFile(new URL("valid-dci.json", assemblyFixtures), "utf8"),
  );
  const invalid = JSON.parse(
    await readFile(new URL("invalid-unknown-field.json", assemblyFixtures), "utf8"),
  );
  assert.deepEqual(validateAssemblyManifest(valid), valid);
  assert.throws(() => validateAssemblyManifest(invalid), ProtocolValidationError);
});

test("validates every checked-in reference assembly", async () => {
  const entries = (
    await Promise.all(
      referenceAssemblyRoots.map(async (root) =>
        (await readdir(root))
          .filter((name) => name.endsWith(".json"))
          .map((name) => ({ name, root })),
      ),
    )
  ).flat();
  const names = entries.map(({ name }) => name).sort();
  assert.deepEqual(names, [
    "controlled-code-validation.json",
    "dci-complete-application-claude.json",
    "dci-complete-application-pi.json",
    "dci-local-research.json",
    "dci-research-capability-claude.json",
    "dci-research-capability.json",
  ]);
  for (const { name, root } of entries) {
    const assembly = JSON.parse(
      await readFile(new URL(name, root), "utf8"),
    );
    assert.deepEqual(validateAssemblyManifest(assembly), assembly);
  }
});

test("rejects non-canonical assembly arrays", async () => {
  const valid = JSON.parse(
    await readFile(new URL("valid-dci.json", assemblyFixtures), "utf8"),
  );
  assert.throws(
    () => validateAssemblyManifest({ ...valid, packages: [...valid.packages].reverse() }),
    ProtocolValidationError,
  );
  assert.throws(
    () => validateAssemblyManifest({ ...valid, host_events: ["z.last", "a.first"] }),
    ProtocolValidationError,
  );
});

test("keeps assembly resolution outside the TypeScript host", async () => {
  const sources = await Promise.all(
    (await readdir(sourceDirectory))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => readFile(new URL(name, sourceDirectory), "utf8")),
  );
  assert.doesNotMatch(sources.join("\n"), /resolveAssembly|AssemblyPlan/);
});
