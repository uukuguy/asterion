import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  GatewayDurableStore,
  GatewayStoreConflictError,
  PrimeContinualHarnessAdapter,
} from "../dist/src/index.js";

const PRIVATE_SENTINEL = "SENTINEL_PRIVATE_HARNESS_BODY";
const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);
const D = "d".repeat(64);

async function withStore(run) {
  const temporary = await mkdtemp(join(tmpdir(), "asterion-continual-harness-"));
  const root = join(temporary, "gateway");
  try {
    await run(root, await GatewayDurableStore.open(root, "session-1"));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

function validHarnessEffect(overrides = {}) {
  return {
    effectId: "harness-effect-1",
    proposalDigest: A,
    scope: {
      primeScope: "local",
      scopeDigest: B,
      projectionRootRef: "private-projection-root-1",
    },
    edits: [
      {
        action: "create",
        entryId: "memory-1",
        expectedVersion: null,
        kind: "memory",
        titleDigest: C,
        bodyDigest: D,
        groupingPathDigest: null,
        metadataDigest: A,
        version: 1,
        bodyText: PRIVATE_SENTINEL,
        pythonReference: null,
        pythonArguments: [],
      },
    ],
    ...overrides,
  };
}

function fakePrimeRefinementModule() {
  return {
    applyCalls: 0,
    loadHarnessState(root, scope) {
      return { root, scope, entries: [] };
    },
    applyRefinementProposal(state, proposal, options) {
      this.applyCalls += 1;
      assert.equal(proposal.edits[0].bodyText, PRIVATE_SENTINEL);
      return { ...state, proposal, options };
    },
    saveHarnessState() {
      return C;
    },
  };
}

test("binds exact effect before applying Prime edits", async () => {
  await withStore(async (root, store) => {
    const module = fakePrimeRefinementModule();
    const adapter = new PrimeContinualHarnessAdapter({ store, module });
    const receipt = await adapter.apply(validHarnessEffect());

    assert.equal(module.applyCalls, 1);
    assert.equal(receipt.status, "succeeded");
    assert.deepEqual(store.harnessEffectResult(receipt.effectId), receipt);
    assert.equal(JSON.stringify(store.snapshot()).includes(PRIVATE_SENTINEL), false);
    assert.equal(JSON.stringify(store.harnessEffectBinding(receipt.effectId)).includes(PRIVATE_SENTINEL), false);
    const reopened = await GatewayDurableStore.open(root, "session-1");
    assert.deepEqual(reopened.harnessEffectResult(receipt.effectId), receipt);
  });
});

test("reopen fences an uncommitted effect without applying twice", async () => {
  await withStore(async (root, store) => {
    await store.bindHarnessEffect(validHarnessEffect());
    const reopened = await GatewayDurableStore.open(root, "session-1");
    const module = fakePrimeRefinementModule();
    const receipt = await new PrimeContinualHarnessAdapter({
      store: reopened,
      module,
    }).apply(validHarnessEffect());

    assert.equal(module.applyCalls, 0);
    assert.equal(receipt.status, "uncertain");
    assert.equal(receipt.snapshotDigest, null);
  });
});

test("closed frame rejects aliases, base prompt, and unsorted edits", async () => {
  await withStore(async (_root, store) => {
    const module = fakePrimeRefinementModule();
    const adapter = new PrimeContinualHarnessAdapter({ store, module });
    await assert.rejects(
      adapter.apply({ ...validHarnessEffect(), provider: "private-provider" }),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      adapter.apply(validHarnessEffect({
        edits: [{ ...validHarnessEffect().edits[0], entryId: "base-system-prompt", kind: "prompt" }],
      })),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      adapter.apply(validHarnessEffect({
        edits: [
          { ...validHarnessEffect().edits[0], entryId: "memory-2" },
          validHarnessEffect().edits[0],
        ],
      })),
      GatewayStoreConflictError,
    );
    assert.equal(module.applyCalls, 0);
  });
});
