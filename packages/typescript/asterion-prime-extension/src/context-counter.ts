import {
  canonicalJson,
  projectPrimeContext,
  validatePrimeContextProjection,
  type PrimeContextProjectionV1,
} from "./context-projection.js";

export { canonicalJson, projectPrimeContext, validatePrimeContextProjection } from "./context-projection.js";
export type { PrimeContextProjectionV1 } from "./context-projection.js";

/** Count Asterion units as the UTF-8 byte length of canonical projection JSON. */
export function countRebuiltContext(projection: PrimeContextProjectionV1): number {
  validatePrimeContextProjection(projection);
  return Buffer.byteLength(canonicalJson(projection), "utf8");
}
