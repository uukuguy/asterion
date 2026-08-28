import { readFileSync } from "node:fs";

import {
  Ajv2020,
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";

import type {
  ActionKind,
  AuthRequest,
  ModelSelectionRequest,
  AgentSystemManifest,
  AssemblyManifest,
  BenchmarkSuiteManifest,
  CapabilityPackageManifest,
  CapabilityManifest,
  CapabilitySourceDeclaration,
  CapabilitySourceLock,
  ControlCommand,
  ControlEvent,
  ControlPlaneManifest,
  ClientEvent,
  ClientIntent,
  RunEvent,
  RunRequest,
  RuntimeManifest,
  OperationReceipt,
  OperationRequestDescriptor,
  OperationTransaction,
  SessionContextCommand,
  SessionContextReceipt,
} from "./types.js";

function readSchema(name: string): object {
  return JSON.parse(
    readFileSync(new URL(`../schemas/${name}`, import.meta.url), "utf8"),
  ) as object;
}

const ajv = new Ajv2020({
  allErrors: true,
  formats: { "date-time": { type: "string", validate: isValidClientUtcTimestamp } },
  strictTypes: false,
});
const manifestValidator = ajv.compile(readSchema("runtime-manifest.schema.json"));
const capabilityManifestValidator = ajv.compile(
  readSchema("capability-manifest.schema.json"),
);
const assemblyManifestValidator = ajv.compile(
  readSchema("application-assembly.schema.json"),
);
const capabilityPackageManifestValidator = ajv.compile(
  readSchema("capability-package.schema.json"),
);
const benchmarkSuiteManifestValidator = ajv.compile(
  readSchema("benchmark-suite.schema.json"),
);
const capabilitySourceDeclarationValidator = ajv.compile(
  readSchema("capability-source.schema.json"),
);
const capabilitySourceLockValidator = ajv.compile(
  readSchema("capability-lock.schema.json"),
);
const requestValidator = ajv.compile(readSchema("run-request.schema.json"));
const eventValidator = ajv.compile(readSchema("event.schema.json"));
const agentSystemValidator = ajv.compile(readSchema("agent-system.schema.json"));
const controlPlaneValidator = ajv.compile(
  readSchema("control-plane-manifest.schema.json"),
);
const controlCommandValidator = ajv.compile(
  readSchema("control-command.schema.json"),
);
const controlEventValidator = ajv.compile(
  readSchema("control-event.schema.json"),
);
const sessionContextCommandValidator = ajv.compile(
  readSchema("session-context-command.schema.json"),
);
const sessionContextReceiptValidator = ajv.compile(
  readSchema("session-context-receipt.schema.json"),
);
const clientIntentValidator = ajv.compile(
  readSchema("agent-client-intent.schema.json"),
);
const clientEventValidator = ajv.compile(
  readSchema("agent-client-event.schema.json"),
);
const operationRequestDescriptorValidator = ajv.compile(
  readSchema("operation-request-descriptor.schema.json"),
);
const operationTransactionValidator = ajv.compile(
  readSchema("operation-transaction.schema.json"),
);
const operationReceiptValidator = ajv.compile(
  readSchema("operation-receipt.schema.json"),
);
const authRequestValidator = ajv.compile(readSchema("auth-request.schema.json"));
const modelSelectionRequestValidator = ajv.compile(
  readSchema("model-selection-request.schema.json"),
);

const EFFECT_COUNTERS = [
  "credential_value_reads",
  "provider_model_requests",
  "network_operations",
  "package_manager_operations",
  "os_process_restart_operations",
  "external_telemetry_deliveries",
  "uploads",
] as const;
const FORBIDDEN_OPERATION_KEYS = new Set([
  "api_key", "authorization", "body", "credential", "destination", "path",
  "prompt", "refresh_token", "text", "token",
]);

export class ProtocolValidationError extends Error {
  constructor(label: string, errors: readonly ErrorObject[] | null | undefined) {
    const first = errors?.[0];
    const location = first?.instancePath || "/";
    const reason = first?.message || "violates Asterion Agent Runtime Protocol v1";
    super(`${label} ${location} ${reason}`);
    this.name = "ProtocolValidationError";
  }
}

export class OperationProtocolError extends ProtocolValidationError {
  constructor(label: string, errors: readonly ErrorObject[] | null | undefined) {
    super(label, errors);
    this.name = "OperationProtocolError";
  }
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const child of Object.values(value as Record<string, unknown>)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}

function immutableSnapshot<T>(value: T): T {
  return deepFreeze(structuredClone(value));
}

function requireValid<T>(
  label: string,
  validator: ValidateFunction,
  value: unknown,
): T {
  if (!validator(value)) {
    throw new ProtocolValidationError(label, validator.errors);
  }
  return immutableSnapshot(value as T);
}

function requireOperationValid<T>(
  label: string,
  validator: ValidateFunction,
  value: unknown,
): T {
  if (!validator(value)) {
    throw new OperationProtocolError(label, validator.errors);
  }
  return immutableSnapshot(value as T);
}

function requireNoForbiddenOperationKeys(value: unknown): void {
  if (value === null || typeof value !== "object") {
    return;
  }
  if (Array.isArray(value)) {
    for (const child of value) requireNoForbiddenOperationKeys(child);
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN_OPERATION_KEYS.has(key)) {
      throw new OperationProtocolError("operation value", null);
    }
    requireNoForbiddenOperationKeys(child);
  }
}

function requireOperationIdentity(value: OperationTransaction): void {
  const request = value.request;
  if (
    request.client_id !== value.client_id ||
    request.session_id !== value.session_id ||
    request.generation !== value.generation ||
    request.authority_revision !== value.authority_revision
  ) {
    throw new OperationProtocolError("operation transaction identity", null);
  }
}

function requireOperationReceipt(value: OperationReceipt): void {
  for (const counter of EFFECT_COUNTERS) {
    if (value.effect_counts[counter] !== 0) {
      throw new OperationProtocolError("operation receipt effect counts", null);
    }
  }
}

function requireSortedUnique(
  label: string,
  values: readonly string[],
): void {
  if (
    values.some(hasSurrogateCodePoint) ||
    values.some(
      (value, index) =>
        index > 0 &&
        compareUnicodeScalarStrings(values[index - 1]!, value) >= 0,
    )
  ) {
    throw new ProtocolValidationError(label, null);
  }
}

function isValidClientUtcTimestamp(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?Z$/.exec(value);
  if (match === null || match[1] === "0000") {
    return false;
  }
  const [, year, month, day, hour, minute, second] = match;
  const timestamp = new Date(value);
  return !(
    Number.isNaN(timestamp.getTime()) ||
    timestamp.getUTCFullYear() !== Number(year) ||
    timestamp.getUTCMonth() + 1 !== Number(month) ||
    timestamp.getUTCDate() !== Number(day) ||
    timestamp.getUTCHours() !== Number(hour) ||
    timestamp.getUTCMinutes() !== Number(minute) ||
    timestamp.getUTCSeconds() !== Number(second)
  );
}

function requireClientUtcTimestamp(value: string): void {
  if (!isValidClientUtcTimestamp(value)) {
    throw new ProtocolValidationError("client event timestamp", null);
  }
}

function hasSurrogateCodePoint(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0)!;
    if (codePoint >= 0xd800 && codePoint <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function compareUnicodeScalarStrings(left: string, right: string): number {
  const leftScalars = left[Symbol.iterator]();
  const rightScalars = right[Symbol.iterator]();
  while (true) {
    const leftScalar = leftScalars.next();
    const rightScalar = rightScalars.next();
    if (leftScalar.done || rightScalar.done) {
      if (leftScalar.done && rightScalar.done) {
        return 0;
      }
      return leftScalar.done ? -1 : 1;
    }
    const leftCodePoint = leftScalar.value.codePointAt(0)!;
    const rightCodePoint = rightScalar.value.codePointAt(0)!;
    if (leftCodePoint !== rightCodePoint) {
      return leftCodePoint < rightCodePoint ? -1 : 1;
    }
  }
}

function requireSortedUniqueTuples(
  label: string,
  values: readonly (readonly string[])[],
): void {
  if (
    values.some((value) => value.some(hasSurrogateCodePoint)) ||
    values.some((value, index) => {
      if (index === 0) {
        return false;
      }
      const previous = values[index - 1]!;
      const width = Math.max(previous.length, value.length);
      for (let itemIndex = 0; itemIndex < width; itemIndex += 1) {
        const left = previous[itemIndex];
        const right = value[itemIndex];
        if (left === undefined || right === undefined) {
          return left !== undefined;
        }
        const order = compareUnicodeScalarStrings(left, right);
        if (order !== 0) {
          return order > 0;
        }
      }
      return true;
    })
  ) {
    throw new ProtocolValidationError(label, null);
  }
}

export function validateRuntimeManifest(value: unknown): RuntimeManifest {
  const manifest = requireValid<RuntimeManifest>(
    "runtime manifest",
    manifestValidator,
    value,
  );
  requireSortedUnique("runtime manifest capabilities", manifest.capabilities);
  return manifest;
}

export function validateOperationRequestDescriptor(
  value: unknown,
): OperationRequestDescriptor {
  requireNoForbiddenOperationKeys(value);
  return requireOperationValid<OperationRequestDescriptor>(
    "operation request descriptor",
    operationRequestDescriptorValidator,
    value,
  );
}

export function validateOperationTransaction(value: unknown): OperationTransaction {
  requireNoForbiddenOperationKeys(value);
  const transaction = requireOperationValid<OperationTransaction>(
    "operation transaction",
    operationTransactionValidator,
    value,
  );
  requireOperationIdentity(transaction);
  return transaction;
}

export function validateOperationReceipt(value: unknown): OperationReceipt {
  requireNoForbiddenOperationKeys(value);
  const receipt = requireOperationValid<OperationReceipt>(
    "operation receipt",
    operationReceiptValidator,
    value,
  );
  requireOperationReceipt(receipt);
  return receipt;
}

export function validateAuthRequest(value: unknown): AuthRequest {
  requireNoForbiddenOperationKeys(value);
  return requireOperationValid<AuthRequest>(
    "auth request",
    authRequestValidator,
    value,
  );
}

export function validateModelSelectionRequest(value: unknown): ModelSelectionRequest {
  requireNoForbiddenOperationKeys(value);
  return requireOperationValid<ModelSelectionRequest>(
    "model selection request",
    modelSelectionRequestValidator,
    value,
  );
}

export function validateAgentSystemManifest(
  value: unknown,
): AgentSystemManifest {
  const manifest = requireValid<AgentSystemManifest>(
    "agent system manifest",
    agentSystemValidator,
    value,
  );
  requireSortedUniqueTuples(
    "agent system application portfolio",
    manifest.applications.map((application) => [
      application.provider_id,
      application.application_id,
      application.version,
      application.runtime_id,
    ]),
  );
  requireSortedUnique("agent system policies", manifest.policies);
  requireSortedUnique(
    "agent system host capabilities",
    manifest.host_capabilities,
  );
  requireSortedUnique(
    "agent system control capabilities",
    manifest.control_capabilities,
  );
  return manifest;
}

export function validateControlPlaneManifest(
  value: unknown,
): ControlPlaneManifest {
  const manifest = requireValid<ControlPlaneManifest>(
    "control plane manifest",
    controlPlaneValidator,
    value,
  );
  requireSortedUnique("control plane commands", manifest.commands);
  requireSortedUnique("control plane events", manifest.events);
  requireSortedUnique("control plane capabilities", manifest.capabilities);
  requireSortedUnique(
    "control plane compatibility identities",
    manifest.compatibility_ids,
  );
  return manifest;
}

export function validateControlCommand(value: unknown): ControlCommand {
  const command = requireValid<ControlCommand>(
    "control command",
    controlCommandValidator,
    value,
  );
  if (command.type === "action.resolve") {
    const { resolution, receipt_ref: receiptRef } = command.payload;
    if (
      (resolution === "succeeded" && receiptRef === null) ||
      ((resolution === "admitted" || resolution === "rejected") &&
        receiptRef !== null)
    ) {
      throw new ProtocolValidationError("action resolution receipt", null);
    }
  }
  return command;
}

export function validateSessionContextCommand(
  value: unknown,
): SessionContextCommand {
  return requireValid<SessionContextCommand>(
    "session context command",
    sessionContextCommandValidator,
    value,
  );
}

export function validateSessionContextReceipt(
  value: unknown,
): SessionContextReceipt {
  const receipt = requireValid<SessionContextReceipt>(
    "session context receipt",
    sessionContextReceiptValidator,
    value,
  );
  if (receipt.status === "succeeded" && receipt.operation === "session.tree.read") {
    const entryIds: string[] = [];
    const parents = new Map<string, string | null>();
    for (const node of receipt.payload.result.nodes) {
      entryIds.push(node.entry_id);
      parents.set(node.entry_id, node.parent_id);
    }
    requireSortedUnique("session context tree entries", entryIds);
    if (
      entryIds.length > 0 &&
      [...parents.values()].filter((parent) => parent === null).length !== 1
    ) {
      throw new ProtocolValidationError("session context tree roots", null);
    }
    for (const entryId of entryIds) {
      const visited = new Set<string>();
      let current: string | null = entryId;
      while (current !== null) {
        if (visited.has(current) || !parents.has(current)) {
          throw new ProtocolValidationError("session context tree parent", null);
        }
        visited.add(current);
        current = parents.get(current)!;
      }
    }
    if (
      (receipt.payload.result.leaf_id !== null &&
        !parents.has(receipt.payload.result.leaf_id))
    ) {
      throw new ProtocolValidationError("session context tree leaf", null);
    }
  }
  return receipt;
}

const actionTargetKinds: Readonly<Record<ActionKind, string>> = {
  "application.invoke": "application",
  "checkpoint.create": "checkpoint",
  "child.cancel": "child",
  "child.message": "child",
  "child.spawn": "child",
  "goal.complete": "goal",
  "goal.fail": "goal",
  "input.request": "input",
  "session.pause": "session",
};

export function validateControlEvent(value: unknown): ControlEvent {
  const event = requireValid<ControlEvent>(
    "control event",
    controlEventValidator,
    value,
  );
  if (event.type === "action.proposed") {
    requireSortedUnique(
      "action proposal expected artifacts",
      event.payload.expected_artifacts,
    );
    requireSortedUnique(
      "action proposal causal parents",
      event.payload.causal_parent_ids,
    );
    if (event.payload.target.kind !== actionTargetKinds[event.payload.kind]) {
      throw new ProtocolValidationError("action proposal target", null);
    }
  }
  return event;
}

const terminalControlEvents = new Set<ControlEvent["type"]>([
  "session.budget-limited",
  "session.cancelled",
  "session.completed",
  "session.failed",
]);

export function validateControlEventStream(
  value: unknown,
): readonly ControlEvent[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new ProtocolValidationError("control event stream", null);
  }
  const events = value.map((event) => validateControlEvent(event));
  const sessionId = events[0]!.session_id;
  const generation = events[0]!.generation;
  const eventIds = new Set<string>();
  const terminalIndexes: number[] = [];
  for (const [index, event] of events.entries()) {
    if (
      event.session_id !== sessionId ||
      event.generation !== generation ||
      event.sequence !== index + 1 ||
      eventIds.has(event.event_id)
    ) {
      throw new ProtocolValidationError("control event stream sequence", null);
    }
    eventIds.add(event.event_id);
    if (terminalControlEvents.has(event.type)) {
      terminalIndexes.push(index);
    }
  }
  if (
    terminalIndexes.length !== 1 ||
    terminalIndexes[0] !== events.length - 1
  ) {
    throw new ProtocolValidationError("control event stream terminal", null);
  }
  return immutableSnapshot(events);
}

export function validateClientIntent(value: unknown): ClientIntent {
  const intent = requireValid<ClientIntent>(
    "client intent",
    clientIntentValidator,
    value,
  );
  if (intent.type === "export.request") {
    requireSortedUnique("client export references", intent.payload.reference_ids);
  }
  return intent;
}

export function validateClientEvent(value: unknown): ClientEvent {
  const event = requireValid<ClientEvent>(
    "client event",
    clientEventValidator,
    value,
  );
  if (event.type === "commands.changed") {
    requireSortedUnique("client commands", event.payload.commands);
  }
  requireClientUtcTimestamp(event.emitted_at);
  return event;
}

export function validateClientEventStream(
  value: unknown,
): readonly ClientEvent[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new ProtocolValidationError("client event stream", null);
  }
  const events = value.map((event) => validateClientEvent(event));
  const sessionId = events[0]!.session_id;
  const generation = events[0]!.generation;
  const eventIds = new Set<string>();
  const activeCalls = new Set<string>();
  const seenCalls = new Set<string>();
  let terminalSeen = false;
  for (const [index, event] of events.entries()) {
    if (
      event.session_id !== sessionId ||
      event.generation !== generation ||
      event.sequence !== index + 1 ||
      eventIds.has(event.event_id) ||
      terminalSeen
    ) {
      throw new ProtocolValidationError("client event stream sequence", null);
    }
    eventIds.add(event.event_id);
    if (event.type === "tool.started") {
      if (seenCalls.has(event.payload.call_id)) {
        throw new ProtocolValidationError("client event stream tool call", null);
      }
      activeCalls.add(event.payload.call_id);
      seenCalls.add(event.payload.call_id);
    } else if (event.type === "tool.completed") {
      if (!activeCalls.delete(event.payload.call_id)) {
        throw new ProtocolValidationError("client event stream tool call", null);
      }
    } else if (event.type === "session.terminal") {
      if (index !== events.length - 1 || activeCalls.size !== 0) {
        throw new ProtocolValidationError("client event stream terminal", null);
      }
      terminalSeen = true;
    }
  }
  if (!terminalSeen) {
    throw new ProtocolValidationError("client event stream terminal", null);
  }
  return immutableSnapshot(events);
}

const capabilityEdgeFields = [
  "provides_capabilities",
  "requires_capabilities",
  "requires_policies",
  "emits_events",
  "consumes_events",
  "produces_artifacts",
  "consumes_artifacts",
] as const;

export function validateCapabilityManifest(value: unknown): CapabilityManifest {
  const manifest = requireValid<CapabilityManifest>(
    "capability manifest",
    capabilityManifestValidator,
    value,
  );
  for (const field of capabilityEdgeFields) {
    requireSortedUnique(`capability manifest ${field}`, manifest[field]);
  }
  return manifest;
}

const assemblyEdgeFields = [
  "host_capabilities",
  "host_policies",
  "host_events",
  "host_artifacts",
] as const;

export function validateAssemblyManifest(value: unknown): AssemblyManifest {
  const assembly = requireValid<AssemblyManifest>(
    "assembly manifest",
    assemblyManifestValidator,
    value,
  );
  requireSortedUniqueRefs(
    "assembly manifest capability packages",
    assembly.capability_packages,
    ({ package_id }) => package_id,
    ({ version }) => version,
  );
  requireSortedUniqueRefs(
    "assembly manifest capabilities",
    assembly.capabilities,
    ({ capability_id }) => capability_id,
    ({ version }) => version,
  );
  for (const field of assemblyEdgeFields) {
    requireSortedUnique(`assembly manifest ${field}`, assembly[field]);
  }
  return assembly;
}

export function validateCapabilityPackageManifest(
  value: unknown,
): CapabilityPackageManifest {
  const manifest = requireValid<CapabilityPackageManifest>(
    "capability package manifest",
    capabilityPackageManifestValidator,
    value,
  );
  requireSortedUniqueRefs(
    "capability package capabilities",
    manifest.capabilities,
    ({ capability_id }) => capability_id,
    ({ version }) => version,
  );
  requireSortedUniqueRefs(
    "capability package benchmark suites",
    manifest.benchmark_suites,
    ({ suite_id }) => suite_id,
    ({ version }) => version,
  );
  requireSortedUniqueKeys(
    "capability package resources",
    manifest.resources,
    ({ resource_id }) => resource_id,
  );
  requireSortedUniqueKeys(
    "capability package conformance",
    manifest.conformance,
    ({ resource_id }) => resource_id,
  );
  return manifest;
}

export function validateBenchmarkSuiteManifest(
  value: unknown,
): BenchmarkSuiteManifest {
  const manifest = requireValid<BenchmarkSuiteManifest>(
    "benchmark suite manifest",
    benchmarkSuiteManifestValidator,
    value,
  );
  requireSortedUniqueKeys(
    "benchmark suite tasks",
    manifest.tasks,
    ({ task_id }) => task_id,
  );
  requireSortedUnique(
    "benchmark suite artifact media types",
    manifest.artifact_media_types,
  );
  return manifest;
}

export function validateCapabilitySourceDeclaration(
  value: unknown,
): CapabilitySourceDeclaration {
  return requireValid<CapabilitySourceDeclaration>(
    "capability source declaration",
    capabilitySourceDeclarationValidator,
    value,
  );
}

export function validateCapabilitySourceLock(
  value: unknown,
): CapabilitySourceLock {
  const lock = requireValid<CapabilitySourceLock>(
    "capability source lock",
    capabilitySourceLockValidator,
    value,
  );
  requireSortedUniqueRefs(
    "capability source lock entries",
    lock.entries,
    ({ package_ref }) => package_ref.package_id,
    ({ package_ref }) => package_ref.version,
  );
  return lock;
}

function requireSortedUniqueRefs<T>(
  label: string,
  references: readonly T[],
  identity: (reference: T) => string,
  version: (reference: T) => string,
): void {
  if (
    references.some(
      (reference) =>
        hasSurrogateCodePoint(identity(reference)) ||
        hasSurrogateCodePoint(version(reference)),
    ) ||
    references.some((reference, index) => {
      if (index === 0) {
        return false;
      }
      const previous = references[index - 1]!;
      const identityOrder = compareUnicodeScalarStrings(
        identity(previous),
        identity(reference),
      );
      return (
        identityOrder > 0 ||
        (identityOrder === 0 &&
          compareUnicodeScalarStrings(
            version(previous),
            version(reference),
          ) >= 0)
      );
    })
  ) {
    throw new ProtocolValidationError(label, null);
  }
}

function requireSortedUniqueKeys<T>(
  label: string,
  values: readonly T[],
  key: (value: T) => string,
): void {
  requireSortedUnique(label, values.map(key));
}

export function validateRunRequest(value: unknown): RunRequest {
  const request = requireValid<RunRequest>(
    "run request",
    requestValidator,
    value,
  );
  if (request.requested_capabilities) {
    requireSortedUnique(
      "run request requested_capabilities",
      request.requested_capabilities,
    );
  }
  return request;
}

export function validateEventStream(value: unknown): readonly RunEvent[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new ProtocolValidationError("event stream", null);
  }
  const events = value.map((event) =>
    requireValid<RunEvent>("event", eventValidator, event),
  );
  const runId = events[0]?.run_id;
  const calls = new Set<string>();
  const results = new Set<string>();
  let terminalSeen = false;

  for (const [index, event] of events.entries()) {
    const expectedSequence = index + 1;
    if (event.sequence !== expectedSequence) {
      throw new ProtocolValidationError("event stream sequence", null);
    }
    if (event.run_id !== runId) {
      throw new ProtocolValidationError("event stream run_id", null);
    }
    if (terminalSeen) {
      throw new ProtocolValidationError("event stream terminal", null);
    }
    if (index === 0 && event.type !== "run.started") {
      throw new ProtocolValidationError("event stream start", null);
    }
    if (index > 0 && event.type === "run.started") {
      throw new ProtocolValidationError("event stream start", null);
    }
    if (event.type === "run.started") {
      requireSortedUnique("run.started capabilities", event.payload.capabilities);
    } else if (event.type === "tool.call") {
      if (calls.has(event.payload.call_id)) {
        throw new ProtocolValidationError("tool.call call_id", null);
      }
      calls.add(event.payload.call_id);
    } else if (event.type === "tool.result") {
      if (
        !calls.has(event.payload.call_id) ||
        results.has(event.payload.call_id)
      ) {
        throw new ProtocolValidationError("tool.result call_id", null);
      }
      results.add(event.payload.call_id);
    }
    terminalSeen = event.type === "run.completed" || event.type === "run.failed";
  }
  if (!terminalSeen) {
    throw new ProtocolValidationError("event stream terminal", null);
  }
  if (calls.size !== results.size) {
    throw new ProtocolValidationError("event stream unmatched tool.call", null);
  }
  return immutableSnapshot(events);
}
