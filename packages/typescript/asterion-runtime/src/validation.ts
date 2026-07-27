import { readFileSync } from "node:fs";

import {
  Ajv2020,
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";

import type {
  AssemblyManifest,
  CapabilityManifest,
  RunEvent,
  RunRequest,
  RuntimeManifest,
} from "./types.js";

function readSchema(name: string): object {
  return JSON.parse(
    readFileSync(new URL(`../schemas/${name}`, import.meta.url), "utf8"),
  ) as object;
}

export function addAsterionSchemaKeywords(validator: Ajv2020): Ajv2020 {
  validator.addKeyword({
    keyword: "x-asterion-sorted-unique",
    type: "array",
    schemaType: "boolean",
    validate: (enabled: boolean, data: unknown[]) =>
      !enabled || isSortedUniqueScalarStrings(data),
    errors: false,
  });
  return validator;
}

const ajv = addAsterionSchemaKeywords(new Ajv2020({ allErrors: true }));
const manifestValidator = ajv.compile(readSchema("runtime-manifest.schema.json"));
const capabilityManifestValidator = ajv.compile(
  readSchema("capability-manifest.schema.json"),
);
const assemblyManifestValidator = ajv.compile(
  readSchema("assembly.schema.json"),
);
const requestValidator = ajv.compile(readSchema("run-request.schema.json"));
const eventValidator = ajv.compile(readSchema("event.schema.json"));

export class ProtocolValidationError extends Error {
  constructor(label: string, errors: readonly ErrorObject[] | null | undefined) {
    const first = errors?.[0];
    const location = first?.instancePath || "/";
    const reason = first?.message || "violates Asterion Agent Runtime Protocol v1";
    super(`${label} ${location} ${reason}`);
    this.name = "ProtocolValidationError";
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

function requireSortedUnique(
  label: string,
  values: readonly string[],
): void {
  if (!isSortedUniqueScalarStrings(values)) {
    throw new ProtocolValidationError(label, null);
  }
}

function isSortedUniqueScalarStrings(values: readonly unknown[]): boolean {
  return values.every((value): value is string => typeof value === "string") &&
    !values.some(hasSurrogateCodePoint) &&
    !values.some(
      (value, index) =>
        index > 0 &&
        compareUnicodeScalarStrings(values[index - 1]!, value) >= 0,
    );
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

export function validateRuntimeManifest(value: unknown): RuntimeManifest {
  const manifest = requireValid<RuntimeManifest>(
    "runtime manifest",
    manifestValidator,
    value,
  );
  requireSortedUnique("runtime manifest capabilities", manifest.capabilities);
  return manifest;
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
  if (
    assembly.packages.some(({ package_id, version }) =>
      hasSurrogateCodePoint(package_id) || hasSurrogateCodePoint(version)
    ) ||
    assembly.packages.some((reference, index) => {
      if (index === 0) {
        return false;
      }
      const previous = assembly.packages[index - 1]!;
      const packageIdOrder = compareUnicodeScalarStrings(
        previous.package_id,
        reference.package_id,
      );
      return (
        packageIdOrder > 0 ||
        (packageIdOrder === 0 &&
          compareUnicodeScalarStrings(previous.version, reference.version) >= 0)
      );
    })
  ) {
    throw new ProtocolValidationError("assembly manifest packages", null);
  }
  for (const field of assemblyEdgeFields) {
    requireSortedUnique(`assembly manifest ${field}`, assembly[field]);
  }
  return assembly;
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
