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
export const SESSION_CONTEXT_PROTOCOL = "asterion.session-context/v1" as const;
export const AGENT_CLIENT_PROTOCOL = "asterion.agent-client/v1" as const;
export const OPERATION_PROTOCOL = "asterion.operation/v1" as const;

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
export type SessionContextProtocolVersion = typeof SESSION_CONTEXT_PROTOCOL;
export type AgentClientProtocolVersion = typeof AGENT_CLIENT_PROTOCOL;
export type OperationProtocolVersion = typeof OPERATION_PROTOCOL;

export type OperationFeatureId =
  | "operation.auth"
  | "operation.controlled-update-restart"
  | "operation.doctor"
  | "operation.model-selection"
  | "operation.settings-keybindings"
  | "operation.telemetry-usage";

export interface OperationRequestDescriptor {
  readonly protocol: OperationProtocolVersion;
  readonly request_kind: string;
  readonly request_ref: string;
  readonly request_sha256: string;
  readonly media_type: string;
  readonly byte_count: number;
  readonly purpose: string;
  readonly client_id: string;
  readonly session_id: string;
  readonly generation: number;
  readonly authority_revision: number;
}

export interface OperationTransaction {
  readonly protocol: OperationProtocolVersion;
  readonly operation_id: string;
  readonly request: OperationRequestDescriptor;
  readonly session_id: string;
  readonly client_id: string;
  readonly generation: number;
  readonly authority_revision: number;
  readonly authority_id: string;
  readonly idempotency_key: string;
  readonly feature_id: OperationFeatureId;
  readonly requested_at: string;
}

export interface OperationEffectCounts {
  readonly credential_value_reads: number;
  readonly provider_model_requests: number;
  readonly network_operations: number;
  readonly package_manager_operations: number;
  readonly os_process_restart_operations: number;
  readonly external_telemetry_deliveries: number;
  readonly uploads: number;
}

export interface OperationReceipt {
  readonly protocol: OperationProtocolVersion;
  readonly receipt_id: string;
  readonly operation_id: string;
  readonly request_ref: string;
  readonly request_sha256: string;
  readonly purpose: string;
  readonly session_id: string;
  readonly client_id: string;
  readonly generation: number;
  readonly authority_revision: number;
  readonly authority_id: string;
  readonly idempotency_key: string;
  readonly feature_id: OperationFeatureId;
  readonly status: "succeeded" | "rejected" | "failed" | "cancelled" | "uncertain";
  readonly reason_code: string;
  readonly receipt_ref: string;
  readonly reconciliation_ref: string | null;
  readonly effect_counts: OperationEffectCounts;
  readonly completed_at: string;
}

export type AuthRequest =
  | { readonly action: "auth.status" }
  | {
      readonly action: "auth.store";
      readonly credential_ref: string;
      readonly subject_digest: string;
      readonly precedence: number;
    }
  | { readonly action: "auth.clear"; readonly credential_ref: string }
  | {
      readonly action: "auth.refresh";
      readonly refresh_ref: string;
      readonly subject_digest: string;
      readonly precedence: number;
    };

export interface ModelSelectionRequest {
  readonly catalog_id: string;
  readonly model_id: string;
  readonly thinking_level: string;
  readonly service_tier: string;
  readonly transport_id: string;
}

export type SettingsKeybindingsRequest =
  | {
      readonly type: "setting";
      readonly name: "theme";
      readonly scope: "global";
      readonly value: "dark" | "light" | "system";
    }
  | {
      readonly type: "setting";
      readonly name: "theme";
      readonly scope: "project";
      readonly value: "dark" | "light" | "system";
      readonly project_id: string;
    }
  | {
      readonly type: "setting";
      readonly name: "telemetry.enabled";
      readonly scope: "global";
      readonly value: boolean;
    }
  | {
      readonly type: "setting";
      readonly name: "telemetry.enabled";
      readonly scope: "project";
      readonly value: boolean;
      readonly project_id: string;
    }
  | {
      readonly type: "keybinding";
      readonly name: "app.session.new" | "app.input.clear" | "app.interrupt";
      readonly scope: "global";
      readonly value: string;
    }
  | {
      readonly type: "keybinding";
      readonly name: "app.session.new" | "app.input.clear" | "app.interrupt";
      readonly scope: "project";
      readonly value: string;
      readonly project_id: string;
    };

export interface TelemetryUsageSnapshot {
  readonly aggregate_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly controller_tokens: number;
  readonly cost_micros: number;
}

export interface TelemetryUsageRequest {
  readonly source_id: "application" | "child" | "controller";
  readonly event_name: "usage.reported";
  readonly event_count: number;
  readonly result_sha256: string;
  readonly usage: TelemetryUsageSnapshot;
}

export interface ClientCursor {
  readonly generation: number;
  readonly sequence: number;
}

export type ClientIntentType =
  | "command.invoke"
  | "export.request"
  | "extension-ui.respond"
  | "input.submit"
  | "session.attach"
  | "session.cancel"
  | "session.create"
  | "session.detach"
  | "session.pause"
  | "session.resume"
  | "share.request";

export interface ClientIntentBase<T extends string, P> {
  readonly protocol: AgentClientProtocolVersion;
  readonly intent_id: string;
  readonly client_id: string;
  readonly session_id: string;
  readonly authority_revision: number;
  readonly type: T;
  readonly payload: P;
}

export type ClientIntent =
  | ClientIntentBase<
      "command.invoke",
      {
        readonly arguments_ref: string;
        readonly command_name: string;
        readonly command_revision: number;
      }
    >
  | ClientIntentBase<
      "export.request",
      {
        readonly destination_ref: string;
        readonly expires_at_ms: number;
        readonly export_id: string;
        readonly max_bytes: number;
        readonly media_type: string;
        readonly reference_ids: readonly string[];
        readonly visibility: "private" | "public";
      }
    >
  | ClientIntentBase<
      "extension-ui.respond",
      {
        readonly cancelled: boolean;
        readonly request_id: string;
        readonly response_ref: string;
      }
    >
  | ClientIntentBase<
      "input.submit",
      {
        readonly content_ref: string;
        readonly delivery: "direct" | "steer" | "follow_up";
        readonly input_id: string;
      }
    >
  | ClientIntentBase<"session.attach", { readonly cursor: ClientCursor }>
  | ClientIntentBase<"session.cancel", ReasonPayload>
  | ClientIntentBase<
      "session.create",
      { readonly goal_id: string; readonly goal_ref: string }
    >
  | ClientIntentBase<"session.detach", ReasonPayload>
  | ClientIntentBase<"session.pause", ReasonPayload>
  | ClientIntentBase<"session.resume", ReasonPayload>
  | ClientIntentBase<
      "share.request",
      { readonly expires_at_ms: number; readonly export_id: string; readonly share_id: string }
    >;

export type ClientEventType =
  | "artifact.available"
  | "commands.changed"
  | "export.created"
  | "extension-ui.requested"
  | "fault.raised"
  | "message.available"
  | "session.state"
  | "session.terminal"
  | "share.created"
  | "tool.completed"
  | "tool.started"
  | "usage.reported";

export interface ClientEventBase<T extends string, P> {
  readonly protocol: typeof AGENT_CLIENT_PROTOCOL;
  readonly event_id: string;
  readonly session_id: string;
  readonly generation: number;
  readonly sequence: number;
  readonly emitted_at: string;
  readonly type: T;
  readonly payload: P;
}

export type ClientEvent =
  | ClientEventBase<
      "artifact.available",
      { readonly artifact_id: string; readonly artifact_ref: string; readonly media_type: string; readonly sha256: string; readonly size: number }
    >
  | ClientEventBase<"commands.changed", { readonly commands: readonly string[]; readonly revision: number }>
  | ClientEventBase<
      "export.created",
      { readonly artifact_id: string; readonly artifact_ref: string; readonly export_id: string; readonly media_type: string; readonly sha256: string; readonly size: number; readonly visibility: "private" | "public" }
    >
  | ClientEventBase<"extension-ui.requested", { readonly deadline_ms: number; readonly method: string; readonly payload_ref: string; readonly request_id: string }>
  | ClientEventBase<"fault.raised", { readonly code: string; readonly evidence_ref: string; readonly recoverable: boolean }>
  | ClientEventBase<"message.available", { readonly content_ref: string; readonly media_type: string; readonly message_id: string; readonly role: "assistant" | "system" | "tool" | "user"; readonly sha256: string; readonly size: number }>
  | ClientEventBase<"session.state", { readonly reason_code: string; readonly status: "budget_limited" | "cancelled" | "completed" | "creating" | "failed" | "idle" | "needs_input" | "paused" | "running" }>
  | ClientEventBase<"session.terminal", { readonly reason_code: string; readonly status: "budget_limited" | "cancelled" | "completed" | "failed" }>
  | ClientEventBase<"share.created", { readonly export_id: string; readonly share_id: string; readonly share_ref: string }>
  | ClientEventBase<"tool.completed", { readonly call_id: string; readonly is_error: boolean; readonly media_type: string; readonly result_ref: string; readonly sha256: string; readonly size: number }>
  | ClientEventBase<"tool.started", { readonly arguments_ref: string; readonly call_id: string; readonly name: string; readonly sha256: string; readonly size: number }>
  | ClientEventBase<"usage.reported", { readonly aggregate_tokens: number; readonly application_tokens: number; readonly child_tokens: number; readonly controller_tokens: number; readonly cost_micros: number }>;

export type SessionContextOperation =
  | "session.attachment.bind"
  | "session.branch.summarize"
  | "session.clone"
  | "session.compact"
  | "session.continuation.delete"
  | "session.continuation.resume"
  | "session.describe"
  | "session.fork"
  | "session.label.set"
  | "session.name.set"
  | "session.tree.navigate"
  | "session.tree.read";

export interface SessionContextBudget {
  readonly controller_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
  readonly deadline_ms: number;
}

export interface SessionContextUsage {
  readonly controller_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
}

interface SessionContextCommandBase<T extends SessionContextOperation, P> {
  readonly protocol: SessionContextProtocolVersion;
  readonly command_id: string;
  readonly session_id: string;
  readonly generation: number;
  readonly authority_revision: number;
  readonly idempotency_key: string;
  readonly operation: T;
  readonly payload: P;
}

type ContinuationPayload = { readonly continuation_id: string };
type ContinuationEntryPayload = ContinuationPayload & {
  readonly entry_id: string;
};

export type SessionContextCommand =
  | SessionContextCommandBase<
      "session.attachment.bind",
      {
        readonly input_id: string;
        readonly attachment_id: string;
        readonly body_ref: string;
        readonly media_type: string;
        readonly sha256: string;
        readonly size: number;
      }
    >
  | SessionContextCommandBase<
      "session.branch.summarize",
      ContinuationEntryPayload & {
        readonly instructions_ref: string | null;
        readonly budget: SessionContextBudget;
      }
    >
  | SessionContextCommandBase<"session.clone", ContinuationPayload>
  | SessionContextCommandBase<
      "session.compact",
      ContinuationPayload & {
        readonly instructions_ref: string | null;
        readonly budget: SessionContextBudget;
      }
    >
  | SessionContextCommandBase<"session.continuation.delete", ContinuationPayload>
  | SessionContextCommandBase<"session.continuation.resume", ContinuationPayload>
  | SessionContextCommandBase<"session.describe", Record<string, never>>
  | SessionContextCommandBase<
      "session.fork",
      ContinuationEntryPayload & { readonly position: "at" | "before" }
    >
  | SessionContextCommandBase<
      "session.label.set",
      ContinuationEntryPayload & { readonly label_ref: string | null }
    >
  | SessionContextCommandBase<"session.name.set", { readonly name_ref: string }>
  | SessionContextCommandBase<"session.tree.navigate", ContinuationEntryPayload>
  | SessionContextCommandBase<"session.tree.read", ContinuationPayload>;

export type SessionContextStatus =
  | "succeeded"
  | "rejected"
  | "failed"
  | "cancelled"
  | "uncertain";

export interface SessionContextTreeNode {
  readonly entry_id: string;
  readonly parent_id: string | null;
  readonly kind:
    | "compaction"
    | "custom"
    | "input"
    | "output"
    | "summary"
    | "system"
    | "tool";
  readonly label_sha256: string | null;
  readonly token_count: number;
}

interface SessionContextReceiptBase<
  T extends SessionContextOperation,
  S extends SessionContextStatus,
  R,
> {
  readonly protocol: SessionContextProtocolVersion;
  readonly receipt_id: string;
  readonly command_id: string;
  readonly session_id: string;
  readonly generation: number;
  readonly operation: T;
  readonly status: S;
  readonly reason_code: string;
  readonly payload: {
    readonly evidence_ref: string | null;
    readonly result: R;
  };
}

type ForkCloneResult = {
  readonly source_continuation_id: string;
  readonly new_continuation_id: string;
  readonly active_leaf_id: string | null;
  readonly transition_sha256: string;
};

type SessionContextFailureReceipt = SessionContextReceiptBase<
  SessionContextOperation,
  Exclude<SessionContextStatus, "succeeded">,
  null
>;

export type SessionContextReceipt =
  | SessionContextFailureReceipt
  | SessionContextReceiptBase<
      "session.attachment.bind",
      "succeeded",
      {
        readonly input_id: string;
        readonly attachment_id: string;
        readonly media_type: string;
        readonly sha256: string;
        readonly size: number;
      }
    >
  | SessionContextReceiptBase<
      "session.branch.summarize",
      "succeeded",
      {
        readonly continuation_id: string;
        readonly previous_leaf_id: string | null;
        readonly current_leaf_id: string;
        readonly summary_sha256: string;
        readonly usage: SessionContextUsage;
      }
    >
  | SessionContextReceiptBase<"session.clone", "succeeded", ForkCloneResult>
  | SessionContextReceiptBase<
      "session.compact",
      "succeeded",
      {
        readonly continuation_id: string;
        readonly covered_leaf_id: string;
        readonly before_context_tokens: number;
        readonly after_context_tokens: number;
        readonly summary_sha256: string;
        readonly usage: SessionContextUsage;
      }
    >
  | SessionContextReceiptBase<
      "session.continuation.delete",
      "succeeded",
      { readonly continuation_id: string; readonly deletion_sha256: string }
    >
  | SessionContextReceiptBase<
      "session.continuation.resume",
      "succeeded",
      {
        readonly previous_continuation_id: string;
        readonly current_continuation_id: string;
        readonly transition_sha256: string;
      }
    >
  | SessionContextReceiptBase<
      "session.describe",
      "succeeded",
      {
        readonly continuation_id: string;
        readonly status:
          | "cancelled"
          | "completed"
          | "creating"
          | "failed"
          | "idle"
          | "paused"
          | "recovery-required"
          | "running";
        readonly context_tokens: number;
        readonly turns: number;
        readonly usage: SessionContextUsage;
        readonly name_sha256: string | null;
      }
    >
  | SessionContextReceiptBase<"session.fork", "succeeded", ForkCloneResult>
  | SessionContextReceiptBase<
      "session.label.set",
      "succeeded",
      {
        readonly continuation_id: string;
        readonly entry_id: string;
        readonly label_sha256: string | null;
      }
    >
  | SessionContextReceiptBase<
      "session.name.set",
      "succeeded",
      { readonly continuation_id: string; readonly name_sha256: string }
    >
  | SessionContextReceiptBase<
      "session.tree.navigate",
      "succeeded",
      {
        readonly continuation_id: string;
        readonly previous_leaf_id: string | null;
        readonly current_leaf_id: string | null;
        readonly transition_sha256: string;
      }
    >
  | SessionContextReceiptBase<
      "session.tree.read",
      "succeeded",
      {
        readonly continuation_id: string;
        readonly nodes: readonly SessionContextTreeNode[];
        readonly leaf_id: string | null;
      }
    >;

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
