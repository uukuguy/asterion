/** Private, single-request callback client for operator-owned operations. */

import { randomUUID } from "node:crypto";
import { createConnection } from "node:net";
import { isAbsolute } from "node:path";
import { TextDecoder } from "node:util";

import {
  validateOperationReceipt,
  validateOperationTransaction,
} from "@dci/agent-runtime";
import type { OperationReceipt, OperationTransaction } from "@dci/agent-runtime";

import { PrimeOperationError } from "./operation.js";
import type { PrimeOperationDispatcher } from "./operation.js";


export const PRIME_OPERATION_HOST_PROTOCOL = "asterion.prime-operation-host/v1";
export const MAX_OPERATION_HOST_FRAME_BYTES = 64 * 1024;
const TOKEN = /^[0-9a-f]{64}$/u;
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;

export interface PrimeOperationHostDescriptor {
  readonly socketPath: string;
  readonly token: string;
}

export interface PrimeOperationHostIdentity {
  readonly sessionId: string;
  readonly generation: number;
  readonly authorityId: string;
  readonly authorityRevision: number;
  readonly timeoutMs: number;
}

export class PrimeOperationHostClient implements PrimeOperationDispatcher {
  private readonly descriptor: Readonly<PrimeOperationHostDescriptor>;
  private readonly identity: Readonly<PrimeOperationHostIdentity>;

  constructor(descriptor: PrimeOperationHostDescriptor, identity: PrimeOperationHostIdentity) {
    try {
      this.descriptor = snapshotDescriptor(descriptor);
      this.identity = snapshotIdentity(identity);
    } catch {
      throw new PrimeOperationError();
    }
  }

  async execute(value: OperationTransaction): Promise<OperationReceipt> {
    const transaction = this.boundTransaction(value);
    return this.request("operation.execute", { transaction }, transaction);
  }

  async reconcile(value: OperationTransaction): Promise<OperationReceipt> {
    const transaction = this.boundTransaction(value);
    return this.request("operation.reconcile", { transaction }, transaction);
  }

  async cancel(operationId: string, authorityRevision: number): Promise<OperationReceipt> {
    if (
      typeof operationId !== "string" || !OPAQUE_ID.test(operationId) ||
      authorityRevision !== this.identity.authorityRevision
    ) throw new PrimeOperationError();
    return this.request("operation.cancel", { operation_id: operationId }, operationId);
  }

  private boundTransaction(value: OperationTransaction): OperationTransaction {
    let transaction: OperationTransaction;
    try {
      transaction = validateOperationTransaction(value);
    } catch {
      throw new PrimeOperationError();
    }
    if (
      transaction.session_id !== this.identity.sessionId ||
      transaction.generation !== this.identity.generation ||
      transaction.authority_id !== this.identity.authorityId ||
      transaction.authority_revision !== this.identity.authorityRevision
    ) throw new PrimeOperationError();
    return transaction;
  }

  private async request(
    type: "operation.execute" | "operation.reconcile" | "operation.cancel",
    payload: Readonly<{ transaction: OperationTransaction }> | Readonly<{ operation_id: string }>,
    expected: OperationTransaction | string,
  ): Promise<OperationReceipt> {
    const id = `operation-${randomUUID()}`;
    const request = {
      protocol: PRIME_OPERATION_HOST_PROTOCOL,
      id,
      type,
      token: this.descriptor.token,
      session_id: this.identity.sessionId,
      generation: this.identity.generation,
      authority_id: this.identity.authorityId,
      authority_revision: this.identity.authorityRevision,
      ...payload,
    };
    let frame: Buffer;
    try {
      frame = Buffer.from(`${JSON.stringify(request)}\n`, "utf8");
    } catch {
      throw new PrimeOperationError();
    }
    if (frame.byteLength > MAX_OPERATION_HOST_FRAME_BYTES) {
      throw new PrimeOperationError();
    }
    const response = await this.exchange(frame);
    if (
      !isRecord(response) ||
      !hasExactKeys(response, ["protocol", "id", "type", "receipt"]) ||
      response.protocol !== PRIME_OPERATION_HOST_PROTOCOL ||
      response.id !== id ||
      response.type !== "operation.receipt"
    ) throw new PrimeOperationError();
    let receipt: OperationReceipt;
    try {
      receipt = validateOperationReceipt(response.receipt);
    } catch {
      throw new PrimeOperationError();
    }
    this.requireReceiptIdentity(receipt, expected);
    return receipt;
  }

  private exchange(frame: Buffer): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const socket = createConnection({ path: this.descriptor.socketPath });
      const chunks: Buffer[] = [];
      let byteCount = 0;
      let settled = false;
      let ended = false;
      const fail = () => {
        if (settled) return;
        settled = true;
        socket.destroy();
        reject(new PrimeOperationError());
      };
      socket.setTimeout(this.identity.timeoutMs, fail);
      socket.once("connect", () => socket.end(frame));
      socket.on("data", (chunk: Buffer) => {
        byteCount += chunk.byteLength;
        if (byteCount > MAX_OPERATION_HOST_FRAME_BYTES) {
          fail();
          return;
        }
        chunks.push(chunk);
      });
      socket.once("error", fail);
      socket.once("end", () => {
        ended = true;
        if (settled) return;
        const responseFrame = Buffer.concat(chunks, byteCount);
        if (
          responseFrame.byteLength === 0 ||
          responseFrame.at(-1) !== 0x0a ||
          responseFrame.subarray(0, -1).includes(0x0a)
        ) {
          fail();
          return;
        }
        try {
          const text = new TextDecoder("utf-8", { fatal: true }).decode(
            responseFrame.subarray(0, -1),
          );
          rejectDuplicateJsonKeys(text);
          const parsed: unknown = JSON.parse(text);
          settled = true;
          resolve(parsed);
        } catch {
          fail();
        }
      });
      socket.once("close", () => {
        if (!ended) fail();
      });
    });
  }

  private requireReceiptIdentity(
    receipt: OperationReceipt,
    expected: OperationTransaction | string,
  ): void {
    if (
      receipt.session_id !== this.identity.sessionId ||
      receipt.generation !== this.identity.generation ||
      receipt.authority_id !== this.identity.authorityId ||
      receipt.authority_revision !== this.identity.authorityRevision ||
      (typeof expected === "string" && receipt.operation_id !== expected) ||
      (typeof expected !== "string" && (
        receipt.operation_id !== expected.operation_id ||
        receipt.request_ref !== expected.request.request_ref ||
        receipt.request_sha256 !== expected.request.request_sha256 ||
        receipt.purpose !== expected.request.purpose ||
        receipt.client_id !== expected.client_id ||
        receipt.idempotency_key !== expected.idempotency_key ||
        receipt.feature_id !== expected.feature_id
      ))
    ) throw new PrimeOperationError();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function positiveInteger(value: unknown): boolean {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function snapshotDescriptor(value: unknown): Readonly<PrimeOperationHostDescriptor> {
  if (!isRecord(value) || !hasExactKeys(value, ["socketPath", "token"])) {
    throw new PrimeOperationError();
  }
  const socketPath = value.socketPath;
  const token = value.token;
  if (
    typeof socketPath !== "string" || !isAbsolute(socketPath) ||
    typeof token !== "string" || !TOKEN.test(token)
  ) throw new PrimeOperationError();
  return Object.freeze({ socketPath, token });
}

function snapshotIdentity(value: unknown): Readonly<PrimeOperationHostIdentity> {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "sessionId", "generation", "authorityId", "authorityRevision", "timeoutMs",
    ])
  ) throw new PrimeOperationError();
  const sessionId = value.sessionId;
  const generation = value.generation;
  const authorityId = value.authorityId;
  const authorityRevision = value.authorityRevision;
  const timeoutMs = value.timeoutMs;
  if (
    typeof sessionId !== "string" || !OPAQUE_ID.test(sessionId) ||
    typeof authorityId !== "string" || !OPAQUE_ID.test(authorityId) ||
    !positiveInteger(generation) || !positiveInteger(authorityRevision) ||
    !positiveInteger(timeoutMs)
  ) throw new PrimeOperationError();
  return Object.freeze({
    sessionId,
    generation: Number(generation),
    authorityId,
    authorityRevision: Number(authorityRevision),
    timeoutMs: Number(timeoutMs),
  });
}

function rejectDuplicateJsonKeys(text: string): void {
  let index = 0;
  const whitespace = () => {
    while (/\s/u.test(text[index] ?? "")) index += 1;
  };
  const string = (): string => {
    const start = index;
    if (text[index] !== '"') throw new PrimeOperationError();
    index += 1;
    while (index < text.length) {
      if (text[index] === "\\") {
        index += 2;
      } else if (text[index] === '"') {
        index += 1;
        return JSON.parse(text.slice(start, index)) as string;
      } else {
        index += 1;
      }
    }
    throw new PrimeOperationError();
  };
  const value = (): void => {
    whitespace();
    if (text[index] === "{") {
      object();
    } else if (text[index] === "[") {
      array();
    } else if (text[index] === '"') {
      string();
    } else {
      const start = index;
      while (index < text.length && !/[\s,}\]]/u.test(text[index] ?? "")) index += 1;
      if (start === index) throw new PrimeOperationError();
    }
    whitespace();
  };
  const object = (): void => {
    index += 1;
    whitespace();
    const keys = new Set<string>();
    if (text[index] === "}") {
      index += 1;
      return;
    }
    while (index < text.length) {
      const key = string();
      if (keys.has(key)) throw new PrimeOperationError();
      keys.add(key);
      whitespace();
      if (text[index] !== ":") throw new PrimeOperationError();
      index += 1;
      value();
      if (text[index] === "}") {
        index += 1;
        return;
      }
      if (text[index] !== ",") throw new PrimeOperationError();
      index += 1;
      whitespace();
    }
    throw new PrimeOperationError();
  };
  const array = (): void => {
    index += 1;
    whitespace();
    if (text[index] === "]") {
      index += 1;
      return;
    }
    while (index < text.length) {
      value();
      if (text[index] === "]") {
        index += 1;
        return;
      }
      if (text[index] !== ",") throw new PrimeOperationError();
      index += 1;
    }
    throw new PrimeOperationError();
  };
  value();
  if (index !== text.length) throw new PrimeOperationError();
}
