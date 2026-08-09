import { createHash, randomUUID } from "node:crypto";
import { lstat } from "node:fs/promises";
import { join } from "node:path";
import { TextDecoder } from "node:util";

import {
  GatewayStoreCorruptionError,
  atomicWriteFile,
  canonicalJsonBytes,
  ensurePrivateDirectory,
  readPrivateRegularFile,
} from "./durable-store.js";
import type {
  StorageFaultInjector,
} from "./durable-store.js";

export type PrivateValueRef = `private:${string}`;

export interface PrivateResultProjection {
  readonly receiptRef: string;
  readonly artifactIds: readonly string[];
  readonly mediaTypes: readonly string[];
}

export interface PrivateValueStoreOptions {
  readonly faultInjector?: StorageFaultInjector;
}

const PRIVATE_VALUE_FORMAT = "asterion.prime-private-value/v1";
const PRIVATE_REF_PATTERN = /^private:(?<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/u;
const OPAQUE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MEDIA_TYPE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/u;
const HEADER_LIMIT_BYTES = 1024;
const INPUT_LIMIT_BYTES = 1024 * 1024;
const RESULT_LIMIT_BYTES = 64 * 1024;
const CAPSULE_LIMIT_BYTES = 8 * 1024 * 1024;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });

type PrivateValueKind = "input" | "result" | "capsule";

interface PrivateValueHeader {
  readonly format: typeof PRIVATE_VALUE_FORMAT;
  readonly reference: PrivateValueRef;
  readonly kind: PrivateValueKind;
  readonly size: number;
  readonly digest: string;
}

export class PrivateValueInvalidError extends Error {
  constructor() {
    super("Prime private value is invalid");
    this.name = "PrivateValueInvalidError";
  }
}

export class PrivateValueWriteError extends Error {
  constructor() {
    super("Prime private value write failed");
    this.name = "PrivateValueWriteError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  );
}

function isSortedUnique(values: readonly string[]): boolean {
  return values.every(
    (value, index) => index === 0 || String(values[index - 1]) < value,
  );
}

function deepFreeze<T>(value: T): T {
  if (
    (Array.isArray(value) || isRecord(value)) &&
    !Object.isFrozen(value)
  ) {
    for (const child of Object.values(value)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function limitForKind(kind: PrivateValueKind): number {
  if (kind === "input") {
    return INPUT_LIMIT_BYTES;
  }
  if (kind === "result") {
    return RESULT_LIMIT_BYTES;
  }
  return CAPSULE_LIMIT_BYTES;
}

function parseReference(reference: string): string {
  const match = PRIVATE_REF_PATTERN.exec(reference);
  if (match?.groups?.id === undefined) {
    throw new PrivateValueInvalidError();
  }
  return match.groups.id;
}

function validateProjection(value: unknown): PrivateResultProjection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["receiptRef", "artifactIds", "mediaTypes"]) ||
    typeof value.receiptRef !== "string" ||
    !OPAQUE_ID_PATTERN.test(value.receiptRef) ||
    !Array.isArray(value.artifactIds) ||
    value.artifactIds.some(
      (item) => typeof item !== "string" || !OPAQUE_ID_PATTERN.test(item),
    ) ||
    !isSortedUnique(value.artifactIds as string[]) ||
    !Array.isArray(value.mediaTypes) ||
    value.mediaTypes.some(
      (item) => typeof item !== "string" || !MEDIA_TYPE_PATTERN.test(item),
    ) ||
    !isSortedUnique(value.mediaTypes as string[])
  ) {
    throw new PrivateValueInvalidError();
  }
  return deepFreeze({
    receiptRef: value.receiptRef,
    artifactIds: [...(value.artifactIds as string[])],
    mediaTypes: [...(value.mediaTypes as string[])],
  });
}

function parseHeader(value: unknown, reference: PrivateValueRef): PrivateValueHeader {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["format", "reference", "kind", "size", "digest"]) ||
    value.format !== PRIVATE_VALUE_FORMAT ||
    value.reference !== reference ||
    (value.kind !== "input" && value.kind !== "result" && value.kind !== "capsule") ||
    !Number.isSafeInteger(value.size) ||
    Number(value.size) < 0 ||
    typeof value.digest !== "string" ||
    !DIGEST_PATTERN.test(value.digest)
  ) {
    throw new PrivateValueInvalidError();
  }
  return Object.freeze({
    format: PRIVATE_VALUE_FORMAT,
    reference,
    kind: value.kind,
    size: Number(value.size),
    digest: value.digest,
  });
}

export class PrivateValueStore {
  private readonly faultInjector: StorageFaultInjector | undefined;

  private constructor(
    private readonly root: string,
    private readonly privateRoot: string,
    private readonly valuesRoot: string,
    options: PrivateValueStoreOptions,
  ) {
    this.faultInjector = options.faultInjector;
  }

  static async open(
    root: string,
    options: PrivateValueStoreOptions = {},
  ): Promise<PrivateValueStore> {
    const privateRoot = join(root, "private");
    const valuesRoot = join(privateRoot, "values");
    try {
      await ensurePrivateDirectory(root);
      await ensurePrivateDirectory(privateRoot);
      await ensurePrivateDirectory(valuesRoot);
      return new PrivateValueStore(root, privateRoot, valuesRoot, options);
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  async putInput(value: string): Promise<PrivateValueRef> {
    if (typeof value !== "string") {
      throw new PrivateValueInvalidError();
    }
    return this.put("input", Buffer.from(value, "utf8"));
  }

  async readInput(reference: PrivateValueRef): Promise<string> {
    const bytes = await this.read(reference, "input");
    try {
      return UTF8_DECODER.decode(bytes);
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  async putResult(value: PrivateResultProjection): Promise<PrivateValueRef> {
    const projection = validateProjection(value);
    return this.put("result", canonicalJsonBytes(projection));
  }

  async readResult(reference: PrivateValueRef): Promise<PrivateResultProjection> {
    const bytes = await this.read(reference, "result");
    try {
      return validateProjection(JSON.parse(UTF8_DECODER.decode(bytes)));
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueInvalidError();
    }
  }

  async putCapsule(value: Uint8Array): Promise<PrivateValueRef> {
    if (!(value instanceof Uint8Array)) {
      throw new PrivateValueInvalidError();
    }
    return this.put("capsule", Buffer.from(value));
  }

  async readCapsule(reference: PrivateValueRef): Promise<Buffer> {
    return Buffer.from(await this.read(reference, "capsule"));
  }

  toString(): string {
    return "[Prime private value store]";
  }

  private async put(
    kind: PrivateValueKind,
    body: Buffer,
  ): Promise<PrivateValueRef> {
    if (body.byteLength > limitForKind(kind)) {
      throw new PrivateValueInvalidError();
    }
    const reference = `private:${randomUUID()}` as PrivateValueRef;
    const header: PrivateValueHeader = {
      format: PRIVATE_VALUE_FORMAT,
      reference,
      kind,
      size: body.byteLength,
      digest: sha256(body),
    };
    const bytes = Buffer.concat([
      canonicalJsonBytes(header),
      Buffer.from("\n"),
      body,
    ]);
    try {
      await this.ensureRoots();
      await atomicWriteFile(
        this.valuesRoot,
        `${parseReference(reference)}.value`,
        bytes,
        this.faultInjector,
      );
      return reference;
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueWriteError();
    }
  }

  private async read(
    reference: PrivateValueRef,
    expectedKind: PrivateValueKind,
  ): Promise<Buffer> {
    try {
      const identifier = parseReference(reference);
      await this.ensureRoots();
      const path = join(this.valuesRoot, `${identifier}.value`);
      const metadata = await lstat(path);
      if (metadata.isSymbolicLink() || !metadata.isFile()) {
        throw new PrivateValueInvalidError();
      }
      const bytes = await readPrivateRegularFile(
        path,
        HEADER_LIMIT_BYTES + limitForKind(expectedKind) + 1,
      );
      const newline = bytes.indexOf(0x0a);
      if (newline < 1 || newline > HEADER_LIMIT_BYTES) {
        throw new PrivateValueInvalidError();
      }
      let headerValue: unknown;
      try {
        headerValue = JSON.parse(bytes.subarray(0, newline).toString("utf8"));
      } catch {
        throw new PrivateValueInvalidError();
      }
      if (!canonicalJsonBytes(headerValue).equals(bytes.subarray(0, newline))) {
        throw new PrivateValueInvalidError();
      }
      const header = parseHeader(headerValue, reference);
      const body = bytes.subarray(newline + 1);
      if (
        header.kind !== expectedKind ||
        header.size !== body.byteLength ||
        body.byteLength > limitForKind(expectedKind) ||
        sha256(body) !== header.digest
      ) {
        throw new PrivateValueInvalidError();
      }
      return Buffer.from(body);
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueInvalidError();
    }
  }

  private async ensureRoots(): Promise<void> {
    try {
      await ensurePrivateDirectory(this.root);
      await ensurePrivateDirectory(this.privateRoot);
      await ensurePrivateDirectory(this.valuesRoot);
    } catch (error) {
      if (error instanceof GatewayStoreCorruptionError) {
        throw new PrivateValueInvalidError();
      }
      throw error;
    }
  }
}
