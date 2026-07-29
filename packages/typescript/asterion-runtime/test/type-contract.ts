import type {
  AgentRuntimeClient,
  AssemblyManifest,
  BenchmarkSuiteManifest,
  CapabilityPackageManifest,
  CapabilityManifest,
  CapabilitySourceDeclaration,
  CapabilitySourceLock,
  RunEvent,
  RunRequest,
  RuntimeManifest,
} from "../src/index.js";

export const fixtureAssembly: AssemblyManifest = {
  protocol: "asterion.application-assembly/v1",
  application_id: "dci.local-research",
  version: "1.0.0",
  runtime_id: "pi.reference",
  capability_packages: [{ package_id: "dci", version: "1.0.0" }],
  capabilities: [{ capability_id: "dci.research", version: "1.0.0" }],
  host_capabilities: [],
  host_policies: [],
  host_events: ["run.started"],
  host_artifacts: ["text/plain"],
};

export const fixtureCapability: CapabilityManifest = {
  protocol: "asterion.capability/v1",
  capability_id: "dci.research",
  version: "1.0.0",
  kind: "capability",
  provides_capabilities: ["research.local-corpus"],
  requires_capabilities: ["filesystem.read"],
  requires_policies: ["policy.local-corpus"],
  emits_events: ["artifact.created"],
  consumes_events: ["run.started"],
  produces_artifacts: ["application/vnd.dci.research+json"],
  consumes_artifacts: ["text/plain"],
};

export const fixtureCapabilityPackage: CapabilityPackageManifest = {
  protocol: "asterion.capability-package/v1",
  package_id: "example.package",
  version: "1.0.0",
  capabilities: [{ capability_id: "example.benchmark", version: "1.0.0" }],
  benchmark_suites: [{ suite_id: "example.suite", version: "1.0.0" }],
  resources: [],
};

export const fixtureBenchmarkSuite: BenchmarkSuiteManifest = {
  protocol: "asterion.benchmark-suite/v1",
  suite_id: "example.suite",
  version: "1.0.0",
  owner_package: { package_id: "example.package", version: "1.0.0" },
  tasks: [
    {
      task_id: "example.task",
      capability: { capability_id: "example.benchmark", version: "1.0.0" },
      binding_id: "example.task",
      metric_contract_id: "example.metric/v1",
      result_contract_id: "example.result/v1",
      note: "",
    },
  ],
  artifact_media_types: ["application/json"],
  default_case_limit: 1,
  default_concurrency: 1,
};

export const fixtureCapabilitySource: CapabilitySourceDeclaration = {
  protocol: "asterion.capability-source/v1",
  source_id: "example.source",
  kind: "local-directory",
  package_ref: { package_id: "example.package", version: "1.0.0" },
  payload_sha256: "a".repeat(64),
};

export const fixtureCapabilityLock: CapabilitySourceLock = {
  protocol: "asterion.capability-lock/v1",
  entries: [
    {
      package_ref: { package_id: "example.package", version: "1.0.0" },
      payload_sha256: "a".repeat(64),
      source_id: "example.source",
    },
  ],
};

export class FixtureClient implements AgentRuntimeClient {
  readonly manifest: RuntimeManifest = {
    protocol: "asterion.agent-runtime/v1",
    runtime_id: "typescript-fixture",
    capabilities: ["filesystem.read"],
  };

  async *run(
    _request: RunRequest,
    _options?: { signal?: AbortSignal },
  ): AsyncIterable<RunEvent> {
    yield {
      protocol: "asterion.agent-runtime/v1",
      run_id: "typescript-host",
      sequence: 1,
      type: "run.started",
      payload: { capabilities: ["filesystem.read"] },
    };
    yield {
      protocol: "asterion.agent-runtime/v1",
      run_id: "typescript-host",
      sequence: 2,
      type: "run.completed",
      payload: { status: "completed" },
    };
  }
}
