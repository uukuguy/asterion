import type {
  AgentSystemManifest,
  AgentRuntimeClient,
  ClientEvent,
  ClientIntent,
  AssemblyManifest,
  BenchmarkSuiteManifest,
  CapabilityPackageManifest,
  CapabilityManifest,
  CapabilitySourceDeclaration,
  CapabilitySourceLock,
  ControlCommand,
  ControlEvent,
  ControlPlaneManifest,
  OperationReceipt,
  OperationRequestDescriptor,
  OperationTransaction,
  AuthRequest,
  ModelSelectionRequest,
  SettingsKeybindingsRequest,
  RunEvent,
  RunRequest,
  RuntimeManifest,
  SessionContextCommand,
  SessionContextReceipt,
} from "../src/index.js";

export const fixtureAuthRequest: AuthRequest = {
  action: "auth.store",
  credential_ref: "credential-ref-1",
  subject_digest: "a".repeat(64),
  precedence: 4,
};

export const fixtureModelSelectionRequest: ModelSelectionRequest = {
  catalog_id: "fixture-catalog-1",
  model_id: "fixture.model.small",
  thinking_level: "low",
  service_tier: "standard",
  transport_id: "fixture.transport-1",
};

export const fixtureSettingsKeybindingsRequest: SettingsKeybindingsRequest = {
  type: "setting",
  name: "theme",
  scope: "global",
  value: "dark",
};

export const fixtureOperationRequestDescriptor: OperationRequestDescriptor = {
  protocol: "asterion.operation/v1",
  request_kind: "operation.auth-request",
  request_ref: "request-1",
  request_sha256: "a".repeat(64),
  media_type: "application/json",
  byte_count: 1,
  purpose: "operation.auth.read",
  client_id: "client-1",
  session_id: "session-1",
  generation: 1,
  authority_revision: 1,
};

export const fixtureOperationTransaction: OperationTransaction = {
  protocol: "asterion.operation/v1",
  operation_id: "operation-1",
  request: fixtureOperationRequestDescriptor,
  session_id: "session-1",
  client_id: "client-1",
  generation: 1,
  authority_revision: 1,
  authority_id: "authority-1",
  idempotency_key: "idempotency-1",
  feature_id: "operation.auth",
  requested_at: "2026-08-10T15:00:00Z",
};

export const fixtureOperationReceipt: OperationReceipt = {
  protocol: "asterion.operation/v1",
  receipt_id: "receipt-1",
  operation_id: "operation-1",
  request_ref: "request-1",
  request_sha256: "a".repeat(64),
  purpose: "operation.auth.read",
  session_id: "session-1",
  client_id: "client-1",
  generation: 1,
  authority_revision: 1,
  authority_id: "authority-1",
  idempotency_key: "idempotency-1",
  feature_id: "operation.auth",
  status: "succeeded",
  reason_code: "operation-succeeded",
  receipt_ref: "receipt-public-1",
  reconciliation_ref: null,
  effect_counts: {
    credential_value_reads: 0,
    provider_model_requests: 0,
    network_operations: 0,
    package_manager_operations: 0,
    os_process_restart_operations: 0,
    external_telemetry_deliveries: 0,
    uploads: 0,
  },
  completed_at: "2026-08-10T15:00:01Z",
};

export const fixtureClientIntent: ClientIntent = {
  protocol: "asterion.agent-client/v1",
  intent_id: "intent-1",
  client_id: "client-1",
  session_id: "session-1",
  authority_revision: 1,
  type: "input.submit",
  payload: {
    content_ref: "private-input-1",
    delivery: "direct",
    input_id: "input-1",
  },
};

export const fixtureClientEvent: ClientEvent = {
  protocol: "asterion.agent-client/v1",
  event_id: "event-1",
  session_id: "session-1",
  generation: 1,
  sequence: 1,
  emitted_at: "2026-08-10T15:00:00Z",
  type: "message.available",
  payload: {
    content_ref: "private-message-1",
    media_type: "text/plain",
    message_id: "message-1",
    role: "assistant",
    sha256: "a".repeat(64),
    size: 13,
  },
};

export const fixtureSessionContextCommand: SessionContextCommand = {
  protocol: "asterion.session-context/v1",
  command_id: "context-command-1",
  session_id: "session-1",
  generation: 1,
  authority_revision: 1,
  idempotency_key: "context-operation-1",
  operation: "session.tree.read",
  payload: { continuation_id: "continuation-1" },
};

export const fixtureSessionContextReceipt: SessionContextReceipt = {
  protocol: "asterion.session-context/v1",
  receipt_id: "context-receipt-1",
  command_id: "context-command-1",
  session_id: "session-1",
  generation: 1,
  operation: "session.tree.read",
  status: "succeeded",
  reason_code: "session-context-succeeded",
  payload: {
    evidence_ref: "evidence-1",
    result: {
      continuation_id: "continuation-1",
      nodes: [],
      leaf_id: null,
    },
  },
};

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
