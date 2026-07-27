import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  BENCHMARK_SUITE_PROTOCOL_VERSION,
  CAPABILITY_PROTOCOL_VERSION,
  CAPABILITY_LOCK_PROTOCOL_VERSION,
  CAPABILITY_PACKAGE_PROTOCOL_VERSION,
  CAPABILITY_SOURCE_PROTOCOL_VERSION,
  RUNTIME_PROTOCOL_VERSION,
  ProtocolValidationError,
  validateAssemblyManifest,
  validateBenchmarkSuiteManifest,
  validateCapabilityPackageManifest,
  validateCapabilityManifest,
  validateCapabilitySourceDeclaration,
  validateCapabilitySourceLock,
  validateEventStream,
  validateRunRequest,
  validateRuntimeManifest,
} from "../dist/src/index.js";
import { addAsterionSchemaKeywords } from "../dist/src/validation.js";

const fixtures = new URL("../../../../tests/fixtures/agent_runtime/v1/", import.meta.url);
const capabilityFixtures = new URL(
  "../../../../tests/fixtures/capabilities/v1/",
  import.meta.url,
);
const capabilityPackageFixtures = new URL(
  "../../../../tests/fixtures/capability_packages/v1/",
  import.meta.url,
);
const benchmarkSuiteFixtures = new URL(
  "../../../../tests/fixtures/benchmark_suite/v1/",
  import.meta.url,
);
const capabilitySourceFixtures = new URL(
  "../../../../tests/fixtures/capability_source/v1/",
  import.meta.url,
);
const referenceManifestRoots = [
  new URL("../../../../src/asterion/capabilities/dci_research/manifests/", import.meta.url),
  new URL("../../../../src/asterion/capabilities/controlled_code/payload/capabilities/", import.meta.url),
];
const sourceDirectory = new URL("../src/", import.meta.url);
const schemaCopyScript = new URL("../scripts/copy-schemas.mjs", import.meta.url);
const assemblyFixtures = new URL(
  "../../../../tests/fixtures/application_assembly/v1/",
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

test("exports the Asterion-owned runtime protocol identity", () => {
  assert.equal(RUNTIME_PROTOCOL_VERSION, "asterion.agent-runtime/v1");
});

test("exports the Asterion-owned application assembly identity", async () => {
  const runtime = await import("../dist/src/index.js");
  assert.equal(
    runtime.APPLICATION_ASSEMBLY_PROTOCOL_VERSION,
    "asterion.application-assembly/v1",
  );
});

async function readJson(name) {
  return JSON.parse(await readFile(new URL(name, fixtures), "utf8"));
}

async function readCapabilityJson(name) {
  return JSON.parse(await readFile(new URL(name, capabilityFixtures), "utf8"));
}

async function readCapabilityPackageJson(name) {
  return JSON.parse(
    await readFile(new URL(name, capabilityPackageFixtures), "utf8"),
  );
}

async function readBenchmarkSuiteJson(name) {
  return JSON.parse(
    await readFile(new URL(name, benchmarkSuiteFixtures), "utf8"),
  );
}

async function readCapabilitySourceJson(name) {
  return JSON.parse(
    await readFile(new URL(name, capabilitySourceFixtures), "utf8"),
  );
}

async function readAssemblyJson(name) {
  return JSON.parse(await readFile(new URL(name, assemblyFixtures), "utf8"));
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
    "../../../../schemas/capabilities/v1/capability-manifest.schema.json",
    "../../../../schemas/application-assembly/v1/application-assembly.schema.json",
    "../../../../schemas/capability-packages/v1/capability-package.schema.json",
    "../../../../schemas/benchmark-suite/v1/benchmark-suite.schema.json",
    "../../../../schemas/capability-source/v1/source.schema.json",
    "../../../../schemas/capability-source/v1/lock.schema.json",
  ]) {
    assert.ok(copyScript.includes(source), source);
  }

  const valid = await readJson("valid-runtime-manifest.json");
  assert.deepEqual(validateRuntimeManifest(valid), valid);
  for (const name of [
    "invalid-runtime-manifest.json",
    "invalid-noncanonical-runtime-id.json",
    "invalid-unsorted-runtime-capabilities.json",
  ]) {
    const invalid = await readJson(name);
    assert.throws(() => validateRuntimeManifest(invalid), ProtocolValidationError);
  }
});

test("validates capability-package object arrays by exact tuple keys", async () => {
  assert.equal(
    CAPABILITY_PACKAGE_PROTOCOL_VERSION,
    "asterion.capability-package/v1",
  );
  const valid = await readCapabilityPackageJson("valid-minimal.json");
  assert.deepEqual(validateCapabilityPackageManifest(valid), valid);
  for (const name of [
    "invalid-unsorted-refs.json",
    "invalid-duplicate-refs.json",
  ]) {
    const invalid = await readCapabilityPackageJson(name);
    assert.throws(
      () => validateCapabilityPackageManifest(invalid),
      ProtocolValidationError,
    );
  }

  for (const [field, value] of [
    ["capabilities", [...valid.capabilities].reverse()],
    ["benchmark_suites", [
      { suite_id: "example.zulu", version: "1.0.0" },
      { suite_id: "example.alpha", version: "1.0.0" },
    ]],
    ["resources", [
      {
        resource_id: "example.zulu",
        media_type: "application/json",
        sha256: "a".repeat(64),
      },
      {
        resource_id: "example.alpha",
        media_type: "application/json",
        sha256: "b".repeat(64),
      },
    ]],
  ]) {
    assert.throws(
      () => validateCapabilityPackageManifest({ ...valid, [field]: value }),
      ProtocolValidationError,
      field,
    );
  }
});

test("validates declarative benchmark-suite fixtures", async () => {
  assert.equal(
    BENCHMARK_SUITE_PROTOCOL_VERSION,
    "asterion.benchmark-suite/v1",
  );
  const valid = await readBenchmarkSuiteJson("valid-minimal.json");
  assert.deepEqual(validateBenchmarkSuiteManifest(valid), valid);
  for (const name of ["invalid-command.json", "invalid-task-order.json"]) {
    const invalid = await readBenchmarkSuiteJson(name);
    assert.throws(
      () => validateBenchmarkSuiteManifest(invalid),
      ProtocolValidationError,
    );
  }
  for (const forbidden of [
    "command",
    "dataset_path",
    "corpus_path",
    "provider",
    "environment",
  ]) {
    const changed = structuredClone(valid);
    changed.tasks[0][forbidden] = "SECRET-AUTHORITY-VALUE";
    assert.throws(
      () => validateBenchmarkSuiteManifest(changed),
      ProtocolValidationError,
    );
  }
});

test("validates operator source and lock fixtures with redacted errors", async () => {
  assert.equal(
    CAPABILITY_SOURCE_PROTOCOL_VERSION,
    "asterion.capability-source/v1",
  );
  assert.equal(
    CAPABILITY_LOCK_PROTOCOL_VERSION,
    "asterion.capability-lock/v1",
  );
  const source = await readCapabilitySourceJson("valid-source.json");
  const lock = await readCapabilitySourceJson("valid-lock.json");
  assert.deepEqual(validateCapabilitySourceDeclaration(source), source);
  assert.deepEqual(validateCapabilitySourceLock(lock), lock);

  for (const [validator, name] of [
    [
      validateCapabilitySourceDeclaration,
      "invalid-private-public-field.json",
    ],
    [validateCapabilitySourceLock, "invalid-duplicate-lock.json"],
  ]) {
    const invalid = await readCapabilitySourceJson(name);
    assert.throws(() => validator(invalid), ProtocolValidationError);
  }

  const sentinel = "SECRET-PRIVATE-LOCATOR";
  const changed = structuredClone(source);
  changed.locator.root = sentinel;
  changed.locator.nested = { value: sentinel };
  try {
    validateCapabilitySourceDeclaration(changed);
    assert.fail("invalid private source locator was accepted");
  } catch (error) {
    assert.ok(error instanceof ProtocolValidationError);
    assert.doesNotMatch(error.message, new RegExp(sentinel));
  }
});

test("returns a deep immutable validation snapshot", async () => {
  const source = await readJson("valid-runtime-manifest.json");
  const validated = validateRuntimeManifest(source);
  source.capabilities.push("z.changed");
  assert.deepEqual(validated.capabilities, ["filesystem.read", "shell"]);
  assert.ok(Object.isFrozen(validated));
  assert.ok(Object.isFrozen(validated.capabilities));
  assert.throws(() => validated.capabilities.push("z.changed"), TypeError);
});

test("validates shared requests and complete event streams", async () => {
  const request = {
    protocol: "asterion.agent-runtime/v1",
    run_id: "typescript-host",
    input: { text: "Investigate the fixture corpus" },
    requested_capabilities: ["filesystem.read"],
  };
  assert.deepEqual(validateRunRequest(request), request);
  assert.throws(
    () => validateRunRequest({ ...request, requested_capabilities: ["shell", "shell"] }),
    ProtocolValidationError,
  );
  const unsortedRequest = await readJson("invalid-unsorted-request-capabilities.json");
  assert.throws(() => validateRunRequest(unsortedRequest), ProtocolValidationError);

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
    "invalid-unmatched-tool-call-at-terminal.jsonl",
    "invalid-post-terminal.jsonl",
    "invalid-unsorted-started-capabilities.jsonl",
  ]) {
    const events = await readJsonl(name);
    assert.throws(() => validateEventStream(events), ProtocolValidationError);
  }
});

test("exports the Asterion-owned capability protocol identity", () => {
  assert.equal(CAPABILITY_PROTOCOL_VERSION, "asterion.capability/v1");
});

test("validates the shared capability manifest fixture", async () => {
  for (const name of [
    "valid-capability.json",
    "valid-unicode-scalar-order.json",
  ]) {
    const valid = await readCapabilityJson(name);
    assert.deepEqual(validateCapabilityManifest(valid), valid);
  }
});

test("rejects every shared invalid capability manifest fixture", async () => {
  for (const name of [
    "invalid-unknown-field.json",
    "invalid-duplicate-edge.json",
    "invalid-capability-id.json",
    "invalid-forbidden-command.json",
    "invalid-unsorted-edge.json",
    "invalid-unicode-scalar-order.json",
    "invalid-surrogate-edge.json",
    "invalid-line-terminator-surrogate-edge.json",
  ]) {
    const invalid = await readCapabilityJson(name);
    assert.throws(() => validateCapabilityManifest(invalid), ProtocolValidationError);
  }
});

test("returns a deep immutable capability validation snapshot", async () => {
  const source = await readCapabilityJson("valid-capability.json");
  const validated = validateCapabilityManifest(source);
  source.kind = "policy";
  source.provides_capabilities.push("z.changed");
  assert.equal(validated.kind, "research");
  assert.deepEqual(validated.provides_capabilities, ["research.local"]);
  assert.ok(Object.isFrozen(validated));
  assert.ok(Object.isFrozen(validated.provides_capabilities));
  assert.throws(() => validated.provides_capabilities.push("z.changed"), TypeError);
});

test("validates every checked-in reference capability manifest", async () => {
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
    assert.deepEqual(validateCapabilityManifest(manifest), manifest);
  }
});

test("keeps capability composition outside the TypeScript host", async () => {
  const sources = await Promise.all(
    (await readdir(sourceDirectory))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => readFile(new URL(name, sourceDirectory), "utf8")),
  );
  const publicSource = sources.join("\n");

  assert.doesNotMatch(publicSource, /composeCapabilities|CapabilityComposition/);
});

test("validates the shared assembly fixtures", async () => {
  for (const name of [
    "valid-dci.json",
    "valid-canonical-order.json",
  ]) {
    const valid = await readAssemblyJson(name);
    assert.deepEqual(validateAssemblyManifest(valid), valid);
  }
  for (const name of [
    "invalid-unknown-field.json",
    "invalid-interpolated-capability-package-ref-order.json",
    "invalid-interpolated-capability-ref-order.json",
    "invalid-unicode-scalar-order.json",
    "invalid-surrogate-edge.json",
    "invalid-line-terminator-surrogate-edge.json",
  ]) {
    const invalid = await readAssemblyJson(name);
    assert.throws(() => validateAssemblyManifest(invalid), ProtocolValidationError);
  }
});

test("canonical schemas reject noncanonical values directly", async () => {
  const cases = [
    {
      schema: new URL(
        "../../../../schemas/capabilities/v1/capability-manifest.schema.json",
        import.meta.url,
      ),
      fixture: await readCapabilityJson("invalid-unsorted-edge.json"),
    },
    {
      schema: new URL(
        "../../../../schemas/capabilities/v1/capability-manifest.schema.json",
        import.meta.url,
      ),
      fixture: await readCapabilityJson(
        "invalid-line-terminator-surrogate-edge.json",
      ),
    },
    {
      schema: new URL(
        "../../../../schemas/application-assembly/v1/application-assembly.schema.json",
        import.meta.url,
      ),
      fixture: await readAssemblyJson(
        "invalid-line-terminator-surrogate-edge.json",
      ),
    },
  ];
  for (const { schema, fixture } of cases) {
    const ajv = addAsterionSchemaKeywords(new Ajv2020({ allErrors: true }));
    const validate = ajv.compile(JSON.parse(await readFile(schema, "utf8")));
    assert.equal(validate(fixture), false);
    assert.ok(validate.errors);
  }
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
    await readFile(
      new URL("valid-canonical-order.json", assemblyFixtures),
      "utf8",
    ),
  );
  assert.throws(
    () =>
      validateAssemblyManifest({
        ...valid,
        capability_packages: [...valid.capability_packages].reverse(),
      }),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      validateAssemblyManifest({
        ...valid,
        capabilities: [...valid.capabilities].reverse(),
      }),
    ProtocolValidationError,
  );
  assert.throws(
    () => validateAssemblyManifest({ ...valid, host_events: ["z.last", "a.first"] }),
    ProtocolValidationError,
  );
});

test("rejects every legacy assembly identity and field name", async () => {
  const valid = await readAssemblyJson("valid-dci.json");
  const { capabilities, ...withoutCapabilities } = valid;
  for (const invalid of [
    { ...valid, protocol: "dci." + "assembly/v1" },
    { ...withoutCapabilities, packages: capabilities },
    {
      ...valid,
      capabilities: [
        { package_id: "dci.research", version: "1.0.0" },
      ],
    },
  ]) {
    assert.throws(
      () => validateAssemblyManifest(invalid),
      ProtocolValidationError,
    );
  }
});

test("keeps assembly resolution outside the TypeScript host", async () => {
  const sources = await Promise.all(
    (await readdir(sourceDirectory))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => readFile(new URL(name, sourceDirectory), "utf8")),
  );
  assert.doesNotMatch(sources.join("\n"), /resolveAssembly|AssemblyPlan/);
});
