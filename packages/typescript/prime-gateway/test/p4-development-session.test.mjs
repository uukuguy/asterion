import assert from "node:assert/strict";
import { join } from "node:path";
import test from "node:test";
test("runs private P4 create detach attach with its exact native cursor", async () => {
  const { runPrimeP4DevelopmentSmoke } = await import("../dist/src/index.js");
  const value = await runPrimeP4DevelopmentSmoke(join(process.cwd(), "../../../3th-party/prime-agent"));
  assert.match(value.activeSessionId, /.+/);
  assert.match(value.cursor.generation, /.+/);
  assert.equal(value.cursor.sequence, 0);
});
