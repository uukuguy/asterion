import { cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const source = fileURLToPath(
  new URL("../../../../schemas/agent-runtime/v1", import.meta.url),
);
const capabilityManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/capabilities/v1/capability-manifest.schema.json",
    import.meta.url,
  ),
);
const assemblyManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/application-assembly/v1/application-assembly.schema.json",
    import.meta.url,
  ),
);
const capabilityPackageManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/capability-packages/v1/capability-package.schema.json",
    import.meta.url,
  ),
);
const benchmarkSuiteManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/benchmark-suite/v1/benchmark-suite.schema.json",
    import.meta.url,
  ),
);
const capabilitySourceDeclarationSource = fileURLToPath(
  new URL(
    "../../../../schemas/capability-source/v1/source.schema.json",
    import.meta.url,
  ),
);
const capabilitySourceLockSource = fileURLToPath(
  new URL(
    "../../../../schemas/capability-source/v1/lock.schema.json",
    import.meta.url,
  ),
);
const agentSystemSource = fileURLToPath(
  new URL(
    "../../../../schemas/agent-system/v1/agent-system.schema.json",
    import.meta.url,
  ),
);
const controlPlaneSource = fileURLToPath(
  new URL(
    "../../../../schemas/control-plane/v1/control-plane-manifest.schema.json",
    import.meta.url,
  ),
);
const controlCommandSource = fileURLToPath(
  new URL(
    "../../../../schemas/agent-control/v1/command.schema.json",
    import.meta.url,
  ),
);
const controlEventSource = fileURLToPath(
  new URL(
    "../../../../schemas/agent-control/v1/event.schema.json",
    import.meta.url,
  ),
);
const sessionContextCommandSource = fileURLToPath(
  new URL(
    "../../../../schemas/session-context/v1/command.schema.json",
    import.meta.url,
  ),
);
const sessionContextReceiptSource = fileURLToPath(
  new URL(
    "../../../../schemas/session-context/v1/receipt.schema.json",
    import.meta.url,
  ),
);
const agentClientIntentSource = fileURLToPath(
  new URL(
    "../../../../schemas/agent-client/v1/intent.schema.json",
    import.meta.url,
  ),
);
const agentClientEventSource = fileURLToPath(
  new URL(
    "../../../../schemas/agent-client/v1/event.schema.json",
    import.meta.url,
  ),
);
const operationRequestDescriptorSource = fileURLToPath(
  new URL(
    "../../../../schemas/operation/v1/operation-request-descriptor.schema.json",
    import.meta.url,
  ),
);
const operationTransactionSource = fileURLToPath(
  new URL(
    "../../../../schemas/operation/v1/operation-transaction.schema.json",
    import.meta.url,
  ),
);
const operationReceiptSource = fileURLToPath(
  new URL(
    "../../../../schemas/operation/v1/operation-receipt.schema.json",
    import.meta.url,
  ),
);
const destination = `${packageRoot}/dist/schemas`;

rmSync(destination, { force: true, recursive: true });
mkdirSync(destination, { recursive: true });
cpSync(source, destination, { recursive: true });
cpSync(capabilityManifestSource, `${destination}/capability-manifest.schema.json`);
cpSync(
  assemblyManifestSource,
  `${destination}/application-assembly.schema.json`,
);
cpSync(
  capabilityPackageManifestSource,
  `${destination}/capability-package.schema.json`,
);
cpSync(
  benchmarkSuiteManifestSource,
  `${destination}/benchmark-suite.schema.json`,
);
cpSync(
  capabilitySourceDeclarationSource,
  `${destination}/capability-source.schema.json`,
);
cpSync(
  capabilitySourceLockSource,
  `${destination}/capability-lock.schema.json`,
);
cpSync(agentSystemSource, `${destination}/agent-system.schema.json`);
cpSync(
  controlPlaneSource,
  `${destination}/control-plane-manifest.schema.json`,
);
cpSync(controlCommandSource, `${destination}/control-command.schema.json`);
cpSync(controlEventSource, `${destination}/control-event.schema.json`);
cpSync(
  sessionContextCommandSource,
  `${destination}/session-context-command.schema.json`,
);
cpSync(
  sessionContextReceiptSource,
  `${destination}/session-context-receipt.schema.json`,
);
cpSync(agentClientIntentSource, `${destination}/agent-client-intent.schema.json`);
cpSync(agentClientEventSource, `${destination}/agent-client-event.schema.json`);
cpSync(
  operationRequestDescriptorSource,
  `${destination}/operation-request-descriptor.schema.json`,
);
cpSync(operationTransactionSource, `${destination}/operation-transaction.schema.json`);
cpSync(operationReceiptSource, `${destination}/operation-receipt.schema.json`);
