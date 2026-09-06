import assert from "node:assert/strict";
import { join } from "node:path";
import test from "node:test";
test("projects only the private daemon stage when native startup fails", async () => {
  const { PrimeP4DevelopmentError, runPrimeP4DevelopmentSmoke } = await import("../dist/src/index.js");
  await assert.rejects(
    runPrimeP4DevelopmentSmoke(join(process.cwd(), "../../../3th-party/prime-agent")),
    (error) => error instanceof PrimeP4DevelopmentError && error.stage === "daemon-start:error",
  );
});
