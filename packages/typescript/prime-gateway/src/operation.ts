/** Closed, body-free operation dispatch for the private Prime sidecar. */

import { createHash } from "node:crypto";

import {
  validateOperationReceipt,
  validateOperationTransaction,
} from "@dci/agent-runtime";
import type { OperationReceipt, OperationTransaction } from "@dci/agent-runtime";

import { canonicalJsonBytes } from "./durable-store.js";

export class PrimeOperationError extends Error {
  constructor() {
    super("Prime operation failed");
    this.name = "PrimeOperationError";
  }
}

export interface PrimeOperationDispatcher {
  execute(transaction: OperationTransaction): Promise<OperationReceipt>;
  cancel(operationId: string, authorityRevision: number): Promise<OperationReceipt>;
  reconcile(transaction: OperationTransaction): Promise<OperationReceipt>;
}

interface OperationRecord {
  readonly digest: string;
  readonly transaction: OperationTransaction;
  receipt: OperationReceipt;
  reconciliationAttempts: number;
}

/**
 * Serializes one exact operation identity.  It never receives a request body:
 * request references are resolved only by the host-owned operation service.
 */
export class PrimeOperationGateway {
  private readonly records = new Map<string, OperationRecord>();
  private readonly tails = new Map<string, Promise<void>>();

  constructor(private readonly dispatcher: PrimeOperationDispatcher) {
    if (
      dispatcher === null || typeof dispatcher !== "object" ||
      typeof dispatcher.execute !== "function" ||
      typeof dispatcher.cancel !== "function" ||
      typeof dispatcher.reconcile !== "function"
    ) throw new PrimeOperationError();
  }

  async execute(value: unknown): Promise<OperationReceipt> {
    const transaction = validateTransaction(value);
    return this.serialized(transaction.operation_id, async () => {
      const digest = transactionDigest(transaction);
      const existing = this.records.get(transaction.operation_id);
      if (existing !== undefined) {
        if (existing.digest !== digest) throw new PrimeOperationError();
        return existing.receipt;
      }
      const receipt = validateReceipt(await this.dispatcher.execute(transaction), transaction);
      this.records.set(transaction.operation_id, {
        digest,
        transaction,
        receipt,
        reconciliationAttempts: 0,
      });
      return receipt;
    });
  }

  async cancel(operationId: unknown, authorityRevision: unknown): Promise<OperationReceipt> {
    if (
      typeof operationId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u.test(operationId) ||
      !Number.isSafeInteger(authorityRevision) || Number(authorityRevision) < 1
    ) throw new PrimeOperationError();
    return this.serialized(operationId, async () => {
      const existing = this.records.get(operationId);
      if (existing === undefined || existing.transaction.authority_revision !== authorityRevision) {
        throw new PrimeOperationError();
      }
      if (existing.receipt.status !== "uncertain") return existing.receipt;
      const receipt = validateReceipt(
        await this.dispatcher.cancel(operationId, Number(authorityRevision)),
        existing.transaction,
      );
      existing.receipt = receipt;
      return receipt;
    });
  }

  async reconcile(value: unknown): Promise<OperationReceipt> {
    const transaction = validateTransaction(value);
    return this.serialized(transaction.operation_id, async () => {
      const existing = this.records.get(transaction.operation_id);
      if (
        existing === undefined ||
        existing.digest !== transactionDigest(transaction)
      ) throw new PrimeOperationError();
      if (existing.receipt.status !== "uncertain") return existing.receipt;
      existing.reconciliationAttempts += 1;
      const receipt = validateReceipt(
        await this.dispatcher.reconcile(transaction),
        transaction,
      );
      existing.receipt = receipt;
      return receipt;
    });
  }

  private async serialized<T>(operationId: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.tails.get(operationId) ?? Promise.resolve();
    let release: (() => void) | undefined;
    const current = new Promise<void>((resolve) => { release = resolve; });
    this.tails.set(operationId, current);
    await previous.catch(() => undefined);
    try {
      return await operation();
    } catch {
      throw new PrimeOperationError();
    } finally {
      release!();
      if (this.tails.get(operationId) === current) this.tails.delete(operationId);
    }
  }
}

function validateTransaction(value: unknown): OperationTransaction {
  try {
    return validateOperationTransaction(value);
  } catch {
    throw new PrimeOperationError();
  }
}

function validateReceipt(value: unknown, transaction: OperationTransaction): OperationReceipt {
  let receipt: OperationReceipt;
  try {
    receipt = validateOperationReceipt(value);
  } catch {
    throw new PrimeOperationError();
  }
  if (
    receipt.operation_id !== transaction.operation_id ||
    receipt.request_ref !== transaction.request.request_ref ||
    receipt.request_sha256 !== transaction.request.request_sha256 ||
    receipt.purpose !== transaction.request.purpose ||
    receipt.session_id !== transaction.session_id ||
    receipt.client_id !== transaction.client_id ||
    receipt.generation !== transaction.generation ||
    receipt.authority_revision !== transaction.authority_revision ||
    receipt.authority_id !== transaction.authority_id ||
    receipt.idempotency_key !== transaction.idempotency_key ||
    receipt.feature_id !== transaction.feature_id
  ) throw new PrimeOperationError();
  return receipt;
}

export function transactionDigest(transaction: OperationTransaction): string {
  return createHash("sha256").update(canonicalJsonBytes(transaction)).digest("hex");
}
