import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  AGENT_CONTROL_PROTOCOL,
  AGENT_SYSTEM_PROTOCOL,
  APPLICATION_ASSEMBLY_PROTOCOL_VERSION,
  BENCHMARK_SUITE_PROTOCOL_VERSION,
  CAPABILITY_LOCK_PROTOCOL_VERSION,
  CAPABILITY_PACKAGE_PROTOCOL_VERSION,
  CAPABILITY_PROTOCOL_VERSION,
  CAPABILITY_SOURCE_PROTOCOL_VERSION,
  CONTROL_PLANE_PROTOCOL,
  SESSION_CONTEXT_PROTOCOL,
  ProtocolValidationError,
  RUNTIME_PROTOCOL_VERSION,
  validateAssemblyManifest,
  validateAgentSystemManifest,
  validateBenchmarkSuiteManifest,
  validateCapabilityPackageManifest,
  validateCapabilityManifest,
  validateCapabilitySourceDeclaration,
  validateCapabilitySourceLock,
  validateControlCommand,
  validateControlEvent,
  validateControlEventStream,
  validateControlPlaneManifest,
  validateSessionContextCommand,
  validateSessionContextReceipt,
  validateEventStream,
  validateRunRequest,
  validateRuntimeManifest,
} from "../dist/src/index.js";

const fixtures = new URL("../../../../tests/fixtures/agent_runtime/v1/", import.meta.url);
const capabilityFixtures = new URL(
  "../../../../tests/fixtures/capabilities/v1/",
  import.meta.url,
);
const referenceManifestRoots = [
  new URL("../../../../src/asterion/capabilities/dci/payload/capabilities/", import.meta.url),
  new URL("../../../../src/asterion/capabilities/controlled_code/manifests/", import.meta.url),
];
const sourceDirectory = new URL("../src/", import.meta.url);
const schemaCopyScript = new URL("../scripts/copy-schemas.mjs", import.meta.url);
const assemblyFixtures = new URL(
  "../../../../tests/fixtures/application_assembly/v1/",
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
const agentSystemFixtures = new URL(
  "../../../../tests/fixtures/agent_system/v1/",
  import.meta.url,
);
const controlPlaneFixtures = new URL(
  "../../../../tests/fixtures/control_plane/v1/",
  import.meta.url,
);
const agentControlFixtures = new URL(
  "../../../../tests/fixtures/agent_control/v1/",
  import.meta.url,
);
const sessionContextFixtures = new URL(
  "../../../../tests/fixtures/session_context/v1/",
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

async function readCapabilityJson(name) {
  return JSON.parse(await readFile(new URL(name, capabilityFixtures), "utf8"));
}

async function readAssemblyJson(name) {
  return JSON.parse(await readFile(new URL(name, assemblyFixtures), "utf8"));
}

async function readFixture(root, name) {
  return JSON.parse(await readFile(new URL(name, root), "utf8"));
}

async function readJsonl(name) {
  return (await readFile(new URL(name, fixtures), "utf8"))
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

test("uses the Asterion-owned runtime protocol identity", () => {
  assert.equal(RUNTIME_PROTOCOL_VERSION, "asterion.agent-runtime/v1");
});

test("validates the shared long-running control contracts", async () => {
  assert.equal(AGENT_SYSTEM_PROTOCOL, "asterion.agent-system/v1");
  assert.equal(CONTROL_PLANE_PROTOCOL, "asterion.control-plane/v1");
  assert.equal(AGENT_CONTROL_PROTOCOL, "asterion.agent-control/v1");

  const system = await readFixture(agentSystemFixtures, "valid-system.json");
  const controlPlane = await readFixture(
    controlPlaneFixtures,
    "valid-manifest.json",
  );
  const createCommand = await readFixture(
    agentControlFixtures,
    "valid-command-session-create.json",
  );
  const proposal = await readFixture(
    agentControlFixtures,
    "valid-event-action-proposed.json",
  );
  const terminal = await readFixture(
    agentControlFixtures,
    "valid-event-terminal.json",
  );

  const validatedSystem = validateAgentSystemManifest(system);
  const validatedControlPlane = validateControlPlaneManifest(controlPlane);
  const validatedCommand = validateControlCommand(createCommand);
  const validatedProposal = validateControlEvent(proposal);
  const validatedTerminal = validateControlEvent(terminal);
  assert.deepEqual(validatedSystem, system);
  assert.deepEqual(validatedControlPlane, controlPlane);
  assert.deepEqual(validatedCommand, createCommand);
  assert.deepEqual(validatedProposal, proposal);
  assert.deepEqual(validatedTerminal, terminal);
  assert.ok(Object.isFrozen(validatedSystem.applications[0]));
  assert.ok(Object.isFrozen(validatedProposal.payload.target));
  assert.throws(
    () => {
      validatedCommand.payload.goal_ref = "changed";
    },
    TypeError,
  );

  for (const [root, name, validate] of [
    [agentSystemFixtures, "invalid-unknown-field.json", validateAgentSystemManifest],
    [agentSystemFixtures, "invalid-unsorted-portfolio.json", validateAgentSystemManifest],
    [controlPlaneFixtures, "invalid-command-family.json", validateControlPlaneManifest],
    [controlPlaneFixtures, "invalid-secret-field.json", validateControlPlaneManifest],
    [agentControlFixtures, "invalid-command-prompt-body.json", validateControlCommand],
    [agentControlFixtures, "invalid-event-sequence.json", validateControlEvent],
    [agentControlFixtures, "invalid-event-provider-payload.json", validateControlEvent],
  ]) {
    const invalid = await readFixture(root, name);
    assert.throws(() => validate(invalid), ProtocolValidationError);
  }
});

test("validates complete control event streams and semantic ordering", async () => {
  const terminal = await readFixture(
    agentControlFixtures,
    "valid-event-terminal.json",
  );
  const events = [
    {
      ...terminal,
      event_id: "event-1",
      sequence: 1,
      type: "session.created",
      payload: {
        goal_id: "goal-1",
        authority_id: "authority-1",
        authority_revision: 1,
      },
    },
    {
      ...terminal,
      event_id: "event-2",
      sequence: 2,
      type: "session.running",
      payload: { reason_code: "started" },
    },
    terminal,
  ];
  assert.deepEqual(validateControlEventStream(events), events);
  assert.throws(
    () => validateControlEventStream([events[0], { ...events[2], sequence: 4 }]),
    ProtocolValidationError,
  );

  const proposal = await readFixture(
    agentControlFixtures,
    "valid-event-action-proposed.json",
  );
  assert.throws(
    () =>
      validateControlEvent({
        ...proposal,
        payload: {
          ...proposal.payload,
          causal_parent_ids: ["task-1", "goal-1"],
        },
      }),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      validateControlEvent({
        ...proposal,
        payload: {
          ...proposal.payload,
          target: { kind: "child", child_id: "child-1" },
        },
      }),
    ProtocolValidationError,
  );
});

test("validates the closed session context extension", async () => {
  assert.equal(SESSION_CONTEXT_PROTOCOL, "asterion.session-context/v1");
  const command = await readFixture(
    sessionContextFixtures,
    "valid-command-tree-read.json",
  );
  const receipt = await readFixture(
    sessionContextFixtures,
    "valid-receipt-tree-read.json",
  );
  const rootNavigation = await readFixture(
    sessionContextFixtures,
    "valid-receipt-tree-navigate-root.json",
  );
  const validatedCommand = validateSessionContextCommand(command);
  const validatedReceipt = validateSessionContextReceipt(receipt);
  assert.deepEqual(validatedCommand, command);
  assert.deepEqual(validatedReceipt, receipt);
  assert.equal(
    validateSessionContextReceipt(rootNavigation).payload.result.current_leaf_id,
    null,
  );
  assert.equal(
    validateSessionContextReceipt({
      ...receipt,
      payload: {
        ...receipt.payload,
        result: { ...receipt.payload.result, leaf_id: null },
      },
    }).payload.result.leaf_id,
    null,
  );
  assert.ok(Object.isFrozen(validatedReceipt.payload.result.nodes[0]));
  assert.throws(
    () => {
      validatedCommand.payload.continuation_id = "changed";
    },
    TypeError,
  );
  assert.throws(
    () => validateSessionContextCommand({
      ...command,
      generation: Number.MAX_SAFE_INTEGER + 1,
    }),
    ProtocolValidationError,
  );
  assert.throws(
    () => validateSessionContextReceipt({
      ...receipt,
      payload: {
        ...receipt.payload,
        result: {
          ...receipt.payload.result,
          nodes: [{
            entry_id: "entry-1",
            parent_id: null,
            kind: "input",
            label_sha256: null,
            token_count: Number.MAX_SAFE_INTEGER + 1,
          }],
          leaf_id: "entry-1",
        },
      },
    }),
    ProtocolValidationError,
  );
  for (const [name, validate] of [
    ["invalid-command-private-path.json", validateSessionContextCommand],
    ["invalid-receipt-provider-payload.json", validateSessionContextReceipt],
    [
      "invalid-receipt-tree-navigate-current-leaf.json",
      validateSessionContextReceipt,
    ],
  ]) {
    const invalid = await readFixture(sessionContextFixtures, name);
    assert.throws(() => validate(invalid), ProtocolValidationError);
  }
});

test("uses the Asterion-owned individual capability protocol identity", () => {
  assert.equal(CAPABILITY_PROTOCOL_VERSION, "asterion.capability/v1");
  assert.throws(
    () =>
      validateCapabilityManifest({
        protocol: "dci." + "package/v1",
        capability_id: "example.research",
      }),
    ProtocolValidationError,
  );
});

test("uses the Asterion-owned application assembly protocol and exact refs", () => {
  assert.equal(
    APPLICATION_ASSEMBLY_PROTOCOL_VERSION,
    "asterion.application-assembly/v1",
  );
  const valid = {
    protocol: "asterion.application-assembly/v1",
    application_id: "example.research",
    version: "1.0.0",
    runtime_id: "example.runtime",
    capability_packages: [
      { package_id: "example", version: "1.0.0" },
      { package_id: "example.extension", version: "1.0.0" },
    ],
    capabilities: [
      { capability_id: "example.policy", version: "1.0.0" },
      { capability_id: "example.research", version: "1.0.0" },
    ],
    host_capabilities: [],
    host_policies: [],
    host_events: [],
    host_artifacts: [],
  };
  const validated = validateAssemblyManifest(valid);
  assert.deepEqual(validated, valid);
  valid.capabilities.push({
    capability_id: "z.changed",
    version: "1.0.0",
  });
  assert.equal(validated.capabilities.length, 2);
  assert.ok(Object.isFrozen(validated));
  assert.ok(Object.isFrozen(validated.capabilities));
  assert.ok(Object.isFrozen(validated.capabilities[0]));
  assert.throws(
    () => {
      validated.capabilities[0].capability_id = "z.changed";
    },
    TypeError,
  );
  valid.capabilities.pop();
  for (const invalid of [
    { ...valid, protocol: "dci." + "assembly/v1" },
    Object.fromEntries(
      Object.entries({ ...valid, packages: valid.capabilities }).filter(
        ([key]) => key !== "capabilities",
      ),
    ),
    {
      ...valid,
      capabilities: [{ package_id: "example.policy", version: "1.0.0" }],
    },
  ]) {
    assert.throws(() => validateAssemblyManifest(invalid), ProtocolValidationError);
  }
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
});

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
    "../../../../schemas/agent-system/v1/agent-system.schema.json",
    "../../../../schemas/control-plane/v1/control-plane-manifest.schema.json",
    "../../../../schemas/agent-control/v1/command.schema.json",
    "../../../../schemas/agent-control/v1/event.schema.json",
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

test("validates capability packages with exact benchmark suite refs", async () => {
  assert.equal(
    CAPABILITY_PACKAGE_PROTOCOL_VERSION,
    "asterion.capability-package/v1",
  );
  const valid = await readFixture(capabilityPackageFixtures, "valid-minimal.json");
  valid.benchmark_suites = [
    { suite_id: "example.alpha", version: "1.0.0" },
    { suite_id: "example.zebra", version: "2.0.0" },
  ];
  const validated = validateCapabilityPackageManifest(valid);
  assert.deepEqual(validated, valid);
  valid.benchmark_suites[0].suite_id = "changed";
  assert.equal(validated.benchmark_suites[0].suite_id, "example.alpha");
  assert.ok(Object.isFrozen(validated.benchmark_suites[0]));
  assert.deepEqual(validated.conformance, [
    {
      resource_id: "externalization.json",
      media_type: "application/json",
      sha256: "516f209e7d4076b2897f2e5c282f709d7c31c7be334e2a80e2a7a6b82e3aecab",
    },
  ]);

  for (const benchmark_suites of [
    [
      { suite_id: "example.zebra", version: "1.0.0" },
      { suite_id: "example.alpha", version: "1.0.0" },
    ],
    [
      { suite_id: "example.alpha", version: "1.0.0" },
      { suite_id: "example.alpha", version: "1.0.0" },
    ],
  ]) {
    assert.throws(
      () =>
        validateCapabilityPackageManifest({
          ...valid,
          benchmark_suites,
        }),
      ProtocolValidationError,
    );
  }
  for (const conformance of [
    [
      {
        resource_id: "example.zebra",
        media_type: "application/json",
        sha256: "a".repeat(64),
      },
      {
        resource_id: "example.alpha",
        media_type: "application/json",
        sha256: "b".repeat(64),
      },
    ],
    [
      {
        resource_id: "example.alpha",
        media_type: "application/json",
        sha256: "a".repeat(64),
      },
      {
        resource_id: "example.alpha",
        media_type: "application/json",
        sha256: "a".repeat(64),
      },
    ],
  ]) {
    assert.throws(
      () =>
        validateCapabilityPackageManifest({
          ...valid,
          conformance,
        }),
      ProtocolValidationError,
    );
  }
});

test("validates closed declarative benchmark suites and semantic order", async () => {
  assert.equal(
    BENCHMARK_SUITE_PROTOCOL_VERSION,
    "asterion.benchmark-suite/v1",
  );
  const valid = await readFixture(benchmarkSuiteFixtures, "valid-minimal.json");
  assert.deepEqual(validateBenchmarkSuiteManifest(valid), valid);
  for (const name of ["invalid-command.json", "invalid-task-order.json"]) {
    const invalid = await readFixture(benchmarkSuiteFixtures, name);
    assert.throws(
      () => validateBenchmarkSuiteManifest(invalid),
      ProtocolValidationError,
    );
  }
  const task = valid.tasks[0];
  for (const field of [
    "command",
    "dataset_path",
    "corpus_path",
    "provider",
    "environment",
  ]) {
    assert.throws(
      () =>
        validateBenchmarkSuiteManifest({
          ...valid,
          tasks: [{ ...task, [field]: "SECRET" }],
        }),
      ProtocolValidationError,
    );
  }
  assert.throws(
    () =>
      validateBenchmarkSuiteManifest({
        ...valid,
        artifact_media_types: ["text/plain", "application/json"],
      }),
    ProtocolValidationError,
  );
});

test("validates public source declarations and exact canonical locks", async () => {
  assert.equal(
    CAPABILITY_SOURCE_PROTOCOL_VERSION,
    "asterion.capability-source/v1",
  );
  assert.equal(CAPABILITY_LOCK_PROTOCOL_VERSION, "asterion.capability-lock/v1");
  const source = await readFixture(capabilitySourceFixtures, "valid-source.json");
  const lock = await readFixture(capabilitySourceFixtures, "valid-lock.json");
  assert.deepEqual(validateCapabilitySourceDeclaration(source), source);
  assert.deepEqual(validateCapabilitySourceLock(lock), lock);
  for (const name of [
    "invalid-private-public-field.json",
    "invalid-registry-kind.json",
    "invalid-duplicate-lock.json",
  ]) {
    const invalid = await readFixture(capabilitySourceFixtures, name);
    const validate = name.includes("lock")
      ? validateCapabilitySourceLock
      : validateCapabilitySourceDeclaration;
    assert.throws(() => validate(invalid), ProtocolValidationError);
  }
  assert.throws(
    () =>
      validateCapabilitySourceLock({
        ...lock,
        entries: [
          {
            ...lock.entries[0],
            package_ref: {
              package_id: "zebra.package",
              version: "1.0.0",
            },
          },
          {
            ...lock.entries[0],
            package_ref: {
              package_id: "alpha.package",
              version: "1.0.0",
            },
          },
        ],
      }),
    ProtocolValidationError,
  );
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
    "invalid-unicode-scalar-order.json",
    "invalid-surrogate-edge.json",
    "invalid-line-terminator-surrogate-edge.json",
  ]) {
    const invalid = await readCapabilityJson(name);
    assert.throws(() => validateCapabilityManifest(invalid), ProtocolValidationError);
  }
});

test("rejects capability edge arrays that are not sorted", async () => {
  const valid = await readCapabilityJson("valid-capability.json");
  const unsorted = {
    ...valid,
    provides_capabilities: ["z.last", "a.first"],
  };

  assert.throws(() => validateCapabilityManifest(unsorted), ProtocolValidationError);
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
    "invalid-interpolated-package-ref-order.json",
    "invalid-unicode-scalar-order.json",
    "invalid-surrogate-edge.json",
    "invalid-line-terminator-surrogate-edge.json",
  ]) {
    const invalid = await readAssemblyJson(name);
    assert.throws(() => validateAssemblyManifest(invalid), ProtocolValidationError);
  }
});

test("canonical schemas reject a surrogate after a line terminator", async () => {
  const ajv = new Ajv2020({ allErrors: true });
  const cases = [
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
    "dci-local-benchmark-application-claude.json",
    "dci-local-benchmark-application-pi.json",
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
    () =>
      validateAssemblyManifest({
        ...valid,
        capabilities: [...valid.capabilities].reverse(),
      }),
    ProtocolValidationError,
  );
  assert.throws(
    () =>
      validateAssemblyManifest({
        ...valid,
        capability_packages: [
          { package_id: "z.last", version: "1.0.0" },
          { package_id: "a.first", version: "1.0.0" },
        ],
      }),
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
