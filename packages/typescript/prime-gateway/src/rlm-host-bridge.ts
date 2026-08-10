export interface RlmSpawnProposal {
  readonly requestId: string;
  readonly childId: string;
}

export interface RlmSpawnResolution {
  readonly resolution: "admitted" | "rejected" | "uncertain";
  readonly childId: string;
}

export interface RlmHostBridgeOptions {
  readonly sessionId: string;
  readonly admitSpawn: (proposal: RlmSpawnProposal) => Promise<RlmSpawnResolution>;
  readonly waitForTerminal: (childId: string) => Promise<unknown>;
}

export class RlmHostBridge {
  private readonly spawns = new Map<string, { readonly childId: string; readonly promise: Promise<RlmSpawnResolution> }>();

  constructor(private readonly options: RlmHostBridgeOptions) {
    if (options.sessionId.length === 0) throw new TypeError("RLM bridge is invalid");
  }

  async proposeSpawn(proposal: RlmSpawnProposal): Promise<RlmSpawnResolution> {
    if (proposal.requestId.length === 0 || proposal.childId.length === 0) {
      throw new TypeError("RLM proposal is invalid");
    }
    const existing = this.spawns.get(proposal.requestId);
    if (existing !== undefined) {
      if (existing.childId !== proposal.childId) throw new TypeError("RLM proposal conflicts");
      return existing.promise;
    }
    const promise = this.admit(proposal);
    this.spawns.set(proposal.requestId, { childId: proposal.childId, promise });
    return promise;
  }

  private async admit(proposal: RlmSpawnProposal): Promise<RlmSpawnResolution> {
    const resolution = await this.options.admitSpawn(Object.freeze({ ...proposal }));
    if (resolution.childId !== proposal.childId) throw new TypeError("RLM admission is invalid");
    return Object.freeze({ ...resolution });
  }
}
