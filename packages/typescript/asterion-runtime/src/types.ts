export const RUNTIME_PROTOCOL_VERSION = "asterion.agent-runtime/v1" as const;
export const PROTOCOL_VERSION = RUNTIME_PROTOCOL_VERSION;
export const CAPABILITY_PROTOCOL_VERSION = "asterion.capability/v1" as const;
export const APPLICATION_ASSEMBLY_PROTOCOL_VERSION =
  "asterion.application-assembly/v1" as const;
export const CAPABILITY_PACKAGE_PROTOCOL_VERSION =
  "asterion.capability-package/v1" as const;
export const BENCHMARK_SUITE_PROTOCOL_VERSION =
  "asterion.benchmark-suite/v1" as const;
export const CAPABILITY_SOURCE_PROTOCOL_VERSION =
  "asterion.capability-source/v1" as const;
export const CAPABILITY_LOCK_PROTOCOL_VERSION =
  "asterion.capability-lock/v1" as const;
export const AGENT_SYSTEM_PROTOCOL = "asterion.agent-system/v1" as const;
export const CONTROL_PLANE_PROTOCOL = "asterion.control-plane/v1" as const;
export const AGENT_CONTROL_PROTOCOL = "asterion.agent-control/v1" as const;

export type ProtocolVersion = typeof RUNTIME_PROTOCOL_VERSION;
export type CapabilityProtocolVersion = typeof CAPABILITY_PROTOCOL_VERSION;
export type ApplicationAssemblyProtocolVersion =
  typeof APPLICATION_ASSEMBLY_PROTOCOL_VERSION;
export type CapabilityPackageProtocolVersion =
  typeof CAPABILITY_PACKAGE_PROTOCOL_VERSION;
export type BenchmarkSuiteProtocolVersion =
  typeof BENCHMARK_SUITE_PROTOCOL_VERSION;
export type CapabilitySourceProtocolVersion =
  typeof CAPABILITY_SOURCE_PROTOCOL_VERSION;
export type CapabilityLockProtocolVersion =
  typeof CAPABILITY_LOCK_PROTOCOL_VERSION;
export type AgentSystemProtocolVersion = typeof AGENT_SYSTEM_PROTOCOL;
export type ControlPlaneProtocolVersion = typeof CONTROL_PLANE_PROTOCOL;
export type AgentControlProtocolVersion = typeof AGENT_CONTROL_PROTOCOL;

export interface AgentSystemApplicationRef {
  readonly provider_id: string;
  readonly application_id: string;
  readonly version: string;
  readonly runtime_id: string;
}

export interface AgentSystemManifest {
  readonly protocol: AgentSystemProtocolVersion;
  readonly system_id: string;
  readonly version: string;
  readonly control_plane: {
    readonly control_plane_id: string;
    readonly version: string;
  };
  readonly applications: readonly AgentSystemApplicationRef[];
  readonly policies: readonly string[];
  readonly host_capabilities: readonly string[];
  readonly control_capabilities: readonly string[];
}

export type ControlCommandType =
  | "action.resolve"
  | "checkpoint.request"
  | "input.submit"
  | "session.attach"
  | "session.cancel"
  | "session.create"
  | "session.pause"
  | "session.resume";

export type ControlEventType =
  | "action.proposed"
  | "budget.reported"
  | "checkpoint.created"
  | "fault.raised"
  | "goal.updated"
  | "session.budget-limited"
  | "session.cancelled"
  | "session.completed"
  | "session.created"
  | "session.failed"
  | "session.paused"
  | "session.recovery-required"
  | "session.running";

export interface ControlPlaneManifest {
  readonly protocol: ControlPlaneProtocolVersion;
  readonly control_plane_id: string;
  readonly version: string;
  readonly commands: readonly ControlCommandType[];
  readonly events: readonly ControlEventType[];
  readonly capabilities: readonly string[];
  readonly continuation_media_type: string;
  readonly checkpoint_version: string;
  readonly compatibility_ids: readonly string[];
}

interface ControlCommandBase<T extends ControlCommandType, P> {
  readonly protocol: AgentControlProtocolVersion;
  readonly command_id: string;
  readonly session_id: string;
  readonly authority_revision: number;
  readonly type: T;
  readonly payload: P;
}

interface ReasonPayload {
  readonly reason_code: string;
}

export type ActionResolution =
  | "admitted"
  | "rejected"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "uncertain";

export type ControlCommand =
  | ControlCommandBase<
      "session.create",
      {
        readonly system_id: string;
        readonly system_version: string;
        readonly goal_id: string;
        readonly goal_ref: string;
      }
    >
  | ControlCommandBase<
      "session.attach",
      { readonly cursor: { readonly generation: number; readonly sequence: number } }
    >
  | ControlCommandBase<
      "input.submit",
      {
        readonly input_id: string;
        readonly delivery: "direct" | "steer" | "follow_up";
        readonly content_ref: string;
      }
    >
  | ControlCommandBase<"session.pause", ReasonPayload>
  | ControlCommandBase<"session.resume", ReasonPayload>
  | ControlCommandBase<"session.cancel", ReasonPayload>
  | ControlCommandBase<
      "checkpoint.request",
      { readonly checkpoint_id: string }
    >
  | ControlCommandBase<
      "action.resolve",
      {
        readonly action_id: string;
        readonly resolution: ActionResolution;
        readonly reason_code: string;
        readonly receipt_ref: string | null;
      }
    >;

export interface ActionBudget {
  readonly controller_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
  readonly deadline_ms: number;
}

export interface ControlUsage {
  readonly controller_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
}

export type ActionKind =
  | "application.invoke"
  | "checkpoint.create"
  | "child.cancel"
  | "child.message"
  | "child.spawn"
  | "goal.complete"
  | "goal.fail"
  | "input.request"
  | "session.pause";

export type ActionTarget =
  | {
      readonly kind: "application";
      readonly provider_id: string;
      readonly application_id: string;
      readonly version: string;
      readonly runtime_id: string;
    }
  | { readonly kind: "child"; readonly child_id: string }
  | { readonly kind: "checkpoint"; readonly checkpoint_id: string }
  | { readonly kind: "goal"; readonly goal_id: string }
  | { readonly kind: "input"; readonly request_id: string }
  | { readonly kind: "session"; readonly session_id: string };

interface ControlEventBase<T extends ControlEventType, P> {
  readonly protocol: AgentControlProtocolVersion;
  readonly event_id: string;
  readonly session_id: string;
  readonly generation: number;
  readonly sequence: number;
  readonly emitted_at: string;
  readonly type: T;
  readonly payload: P;
}

export type GoalStatus =
  | "active"
  | "paused"
  | "needs_input"
  | "budget_limited"
  | "completed"
  | "failed"
  | "cancelled";

export type ControlEvent =
  | ControlEventBase<
      "session.created",
      {
        readonly goal_id: string;
        readonly authority_id: string;
        readonly authority_revision: number;
      }
    >
  | ControlEventBase<"session.running", ReasonPayload>
  | ControlEventBase<"session.paused", ReasonPayload>
  | ControlEventBase<"session.recovery-required", ReasonPayload>
  | ControlEventBase<"session.completed", ReasonPayload>
  | ControlEventBase<"session.failed", ReasonPayload>
  | ControlEventBase<"session.cancelled", ReasonPayload>
  | ControlEventBase<"session.budget-limited", ReasonPayload>
  | ControlEventBase<
      "goal.updated",
      { readonly goal_id: string; readonly status: GoalStatus }
    >
  | ControlEventBase<
      "action.proposed",
      {
        readonly action_id: string;
        readonly authority_revision: number;
        readonly idempotency_key: string;
        readonly kind: ActionKind;
        readonly target: ActionTarget;
        readonly input_ref: string;
        readonly expected_artifacts: readonly string[];
        readonly budget: ActionBudget;
        readonly causal_parent_ids: readonly string[];
      }
    >
  | ControlEventBase<
      "checkpoint.created",
      {
        readonly checkpoint_id: string;
        readonly capsule_id: string;
        readonly capsule_digest: string;
        readonly control_plane_id: string;
        readonly control_plane_version: string;
        readonly checkpoint_version: string;
        readonly covered_sequence: number;
        readonly storage_ref: string;
      }
    >
  | ControlEventBase<"budget.reported", ControlUsage>
  | ControlEventBase<
      "fault.raised",
      {
        readonly code: string;
        readonly recoverable: boolean;
        readonly evidence_ref: string | null;
      }
    >;

export interface CapabilityPackageRef {
  readonly package_id: string;
  readonly version: string;
}

export interface CapabilityRef {
  readonly capability_id: string;
  readonly version: string;
}

export interface BenchmarkSuiteRef {
  readonly suite_id: string;
  readonly version: string;
}

export interface AssemblyManifest {
  readonly protocol: ApplicationAssemblyProtocolVersion;
  readonly application_id: string;
  readonly version: string;
  readonly runtime_id: string;
  readonly capability_packages: readonly CapabilityPackageRef[];
  readonly capabilities: readonly CapabilityRef[];
  readonly host_capabilities: readonly string[];
  readonly host_policies: readonly string[];
  readonly host_events: readonly string[];
  readonly host_artifacts: readonly string[];
}
export type CapabilityKind =
  | "capability"
  | "workflow"
  | "policy"
  | "memory"
  | "observability"
  | "evaluation"
  | "research";

export interface CapabilityManifest {
  readonly protocol: CapabilityProtocolVersion;
  readonly capability_id: string;
  readonly version: string;
  readonly kind: CapabilityKind;
  readonly provides_capabilities: readonly string[];
  readonly requires_capabilities: readonly string[];
  readonly requires_policies: readonly string[];
  readonly emits_events: readonly string[];
  readonly consumes_events: readonly string[];
  readonly produces_artifacts: readonly string[];
  readonly consumes_artifacts: readonly string[];
}

export interface CapabilityPackageManifest {
  readonly protocol: CapabilityPackageProtocolVersion;
  readonly package_id: string;
  readonly version: string;
  readonly capabilities: readonly CapabilityRef[];
  readonly benchmark_suites: readonly BenchmarkSuiteRef[];
  readonly resources: readonly {
    readonly resource_id: string;
    readonly media_type: string;
    readonly sha256: string;
  }[];
  readonly conformance: readonly {
    readonly resource_id: string;
    readonly media_type: string;
    readonly sha256: string;
  }[];
}

export interface BenchmarkTaskManifest {
  readonly task_id: string;
  readonly capability: CapabilityRef;
  readonly binding_id: string;
  readonly metric_contract_id: string;
  readonly result_contract_id: string;
  readonly note: string;
}

export interface BenchmarkSuiteManifest {
  readonly protocol: BenchmarkSuiteProtocolVersion;
  readonly suite_id: string;
  readonly version: string;
  readonly owner_package: CapabilityPackageRef;
  readonly tasks: readonly BenchmarkTaskManifest[];
  readonly artifact_media_types: readonly string[];
  readonly default_case_limit: number;
  readonly default_concurrency: number;
}

export type CapabilitySourceKind =
  | "archive"
  | "builtin"
  | "local-directory"
  | "python-distribution";

export interface CapabilitySourceDeclaration {
  readonly protocol: CapabilitySourceProtocolVersion;
  readonly source_id: string;
  readonly kind: CapabilitySourceKind;
  readonly package_ref: CapabilityPackageRef;
  readonly payload_sha256: string | null;
}

export interface CapabilitySourceLockEntry {
  readonly package_ref: CapabilityPackageRef;
  readonly payload_sha256: string;
  readonly source_id: string;
}

export interface CapabilitySourceLock {
  readonly protocol: CapabilityLockProtocolVersion;
  readonly entries: readonly CapabilitySourceLockEntry[];
}

export interface RuntimeManifest {
  readonly protocol: ProtocolVersion;
  readonly runtime_id: string;
  readonly capabilities: readonly string[];
}

export interface RunRequest {
  readonly protocol: ProtocolVersion;
  readonly run_id: string;
  readonly input: { readonly text: string };
  readonly requested_capabilities?: readonly string[];
  readonly deadline_ms?: number;
}

interface EventBase<T extends string, P> {
  readonly protocol: ProtocolVersion;
  readonly run_id: string;
  readonly sequence: number;
  readonly type: T;
  readonly payload: P;
}

export type RunEvent =
  | EventBase<"run.started", { readonly capabilities: readonly string[] }>
  | EventBase<"text.delta", { readonly text: string }>
  | EventBase<
      "tool.call",
      {
        readonly call_id: string;
        readonly name: string;
        readonly arguments: Readonly<Record<string, unknown>>;
      }
    >
  | EventBase<
      "tool.result",
      { readonly call_id: string; readonly output: unknown; readonly is_error: boolean }
    >
  | EventBase<
      "usage.reported",
      { readonly input_tokens: number; readonly output_tokens: number }
    >
  | EventBase<
      "artifact.created",
      {
        readonly artifact: {
          readonly artifact_id: string;
          readonly kind: string;
          readonly media_type: string;
          readonly uri?: string;
          readonly sha256?: string;
        };
      }
    >
  | EventBase<"run.completed", { readonly status: "completed" | "cancelled" }>
  | EventBase<"run.failed", { readonly code: string; readonly message: string }>;

export interface AgentRuntimeClient {
  readonly manifest: RuntimeManifest;
  run(
    request: RunRequest,
    options?: { readonly signal?: AbortSignal },
  ): AsyncIterable<RunEvent>;
}
