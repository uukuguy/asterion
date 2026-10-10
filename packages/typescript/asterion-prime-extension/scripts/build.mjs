import { build } from "esbuild";
import { basename, dirname, resolve } from "node:path";

const output = process.argv.slice(2);
if (output.length > 1 || (output.length === 1 && !output[0].startsWith("--outfile="))) {
  throw new Error("Prime extension build arguments are invalid");
}
// Preserve the existing isolated hatch build override. All selected resources
// always share the same output directory and are compiled in one invocation.
const core = resolve(output[0]?.slice("--outfile=".length) ?? "dist/ipython-extension.mjs");
await build({
  entryPoints: {
    [basename(core).slice(0, -4)]: "src/ipython-extension.ts",
    "p7-research-extension": "src/p7-research-extension.ts",
    "p7-legacy-extension": "src/p7-legacy-extension.ts",
  },
  outdir: dirname(core), outExtension: {".js": ".mjs"},
  bundle: true, platform: "node", format: "esm", target: "node20",
  supported: {"template-literal": false}, legalComments: "none",
  minifySyntax: true, minifyWhitespace: true,
});
