# Private P7 research archive

Keep the complete research history outside the public repository. The cloud console
is a compressed presentation copy; the GitHub result JSON and images are evidence
of the result. Neither replaces the original research records.

## Create and check a snapshot

From a committed Asterion checkout:

```bash
make p7-archive
make p7-archive-verify
```

The default destination is `../asterion-research-archive/arc-agi-3/`.
Use `DEST=/private/storage/arc-agi-3` to select another directory outside the
repository and source data. Use `SNAPSHOT=/path/to/completed/snapshot` to verify
one older snapshot. These commands are offline: they do not run a model, game
engine or official submission, and do not change live records or certificates.

Each snapshot retains all discovered `.asterion-private/prime-p7-*` histories,
manual P7 research and public result files. This includes successful and failed
attempts, raw and reconstructed recordings, intermediate frames, action traces,
WorldMap revisions, IPython artifacts, source links, certificates, winner pointers,
official receipts and the 25 fixed-name HTML replays. The default Make entry also
copies external ARC environment files, archived games and SDK wheels.

The snapshot contains:

| Item | Purpose |
| --- | --- |
| `data/` | Original relative paths and file bytes from the operator workspace |
| `arc-assets/` | Offline game assets and SDK wheels, when configured |
| `source.bundle` | Committed source history and all Git refs, including the P7 release tag |
| `manifest.json` | SHA256 and size of every saved file; source commit, roots, missing roots and exclusions |

Credentials and configuration files such as `.env`, deployment tokens and Pi auth
files are excluded. Virtual environments, dependency caches and the continuously
changing cloud publisher projection are rebuildable and excluded with reasons in
the manifest. This is a **private** archive: research traces can contain model
inputs and outputs. Do not publish the archive or add it to GitHub.

New directories use mode `700`; saved files use `600`. The tool copies independent
files, checks source hashes before and after copying, and verifies the complete
snapshot before publishing its directory and replacing `latest.json`. A changed
source, missing file, symlink, capacity failure or hash mismatch produces a visible
error. A failed attempt does not replace the last successful pointer. The bundle
contains committed files only; the manifest reports a dirty source checkout.

## Retention and a second copy

Keep the initial 100-point archive as a permanent baseline. Create a new snapshot
after a meaningful research milestone; existing snapshots are never overwritten
or automatically deleted. Check available space before adding another full copy.

Copy the **whole completed snapshot**, including its manifest and source bundle,
to a second private disk or private backup storage, then run:

```bash
make p7-archive-verify SNAPSHOT=/second/storage/snapshot
```

A second directory on the same disk does not protect against disk failure. No
external backup destination or upload is configured by this tool.

## Research and recovery

Verify a snapshot before using it. Clone `source.bundle` into a new research
checkout, then copy `data/.asterion-private/` into that isolated checkout. Keep
`arc-assets/` separate and install from the saved wheels when needed. Supply fresh
operator credentials through the normal local configuration; credentials are not
part of the archive.

Start with the saved official receipt and winner pointers, and follow their source
links into run summaries, certificates, traces and WorldMap revisions. Preserve
the producing code identity of each certificate. Do not overwrite live data,
rewrite old certificates or assume that a newer framework commit produced every
saved solution. Any new engine replay or model run remains a separate operation.
