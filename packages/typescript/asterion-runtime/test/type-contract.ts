import type {
  AgentRuntimeClient,
  AssemblyManifest,
  PackageManifest,
  RunEvent,
  RunRequest,
  RuntimeManifest,
} from "../src/index.js";

export const fixtureAssembly: AssemblyManifest = {
  protocol: "dci.assembly/v1",
  application_id: "dci.local-research",
  version: "1.0.0",
  runtime_id: "pi.reference",
  packages: [{ package_id: "dci.research", version: "1.0.0" }],
  host_capabilities: [],
  host_policies: [],
  host_events: ["run.started"],
  host_artifacts: ["text/plain"],
};

export const fixturePackage: PackageManifest = {
  protocol: "dci.package/v1",
  package_id: "dci.research",
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

export class FixtureClient implements AgentRuntimeClient {
  readonly manifest: RuntimeManifest = {
    protocol: "dci.agent-runtime/v1",
    runtime_id: "typescript-fixture",
    capabilities: ["filesystem.read"],
  };

  async *run(
    _request: RunRequest,
    _options?: { signal?: AbortSignal },
  ): AsyncIterable<RunEvent> {
    yield {
      protocol: "dci.agent-runtime/v1",
      run_id: "typescript-host",
      sequence: 1,
      type: "run.started",
      payload: { capabilities: ["filesystem.read"] },
    };
    yield {
      protocol: "dci.agent-runtime/v1",
      run_id: "typescript-host",
      sequence: 2,
      type: "run.completed",
      payload: { status: "completed" },
    };
  }
}
