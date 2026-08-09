import type {
  AgentSystemManifest,
  AgentRuntimeClient,
  AssemblyManifest,
  BenchmarkSuiteManifest,
  CapabilityPackageManifest,
  CapabilityManifest,
  CapabilitySourceDeclaration,
  CapabilitySourceLock,
  ControlCommand,
  ControlEvent,
  ControlPlaneManifest,
  RunEvent,
  RunRequest,
  RuntimeManifest,
} from "../src/index.js";

export const fixtureAgentSystem: AgentSystemManifest = {
  protocol: "asterion.agent-system/v1",
  system_id: "research.system",
  version: "1.0.0",
  control_plane: { control_plane_id: "fake.control", version: "1.0.0" },
  applications: [
    {
      provider_id: "example.provider",
      application_id: "alpha",
      version: "1.0.0",
      runtime_id: "fake.runtime",
    },
  ],
  policies: [],
  host_capabilities: [],
  control_capabilities: ["session-lifecycle"],
};

export const fixtureControlPlane: ControlPlaneManifest = {
  protocol: "asterion.control-plane/v1",
  control_plane_id: "fake.control",
  version: "1.0.0",
  commands: ["session.create"],
  events: ["session.created"],
  capabilities: ["session-lifecycle"],
  continuation_media_type: "application/vnd.asterion.control-capsule",
  checkpoint_version: "1.0.0",
  compatibility_ids: ["asterion.agent-control/v1"],
};

export const fixtureControlCommand: ControlCommand = {
  protocol: "asterion.agent-control/v1",
  command_id: "command-1",
  session_id: "session-1",
  authority_revision: 1,
  type: "session.create",
  payload: {
    system_id: "research.system",
    system_version: "1.0.0",
    goal_id: "goal-1",
    goal_ref: "goal-ref-1",
  },
};

export const fixtureControlEvent: ControlEvent = {
  protocol: "asterion.agent-control/v1",
  event_id: "event-1",
  session_id: "session-1",
  generation: 1,
  sequence: 1,
  emitted_at: "2026-08-09T15:00:00Z",
  type: "session.running",
  payload: { reason_code: "started" },
};

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
  conformance: [],
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
