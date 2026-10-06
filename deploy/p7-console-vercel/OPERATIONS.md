# P7 cloud observation console

The Function reads authenticated private Vercel Blob storage only. It never
contacts a local console. The copied P7 UI accepts read-only public projections;
all remote mutation methods return 405. Refresh packaged assets after changing
the source UI:

```sh
npm --prefix deploy/p7-console-vercel ci
npm --prefix deploy/p7-console-vercel run refresh-assets
npm --prefix deploy/p7-console-vercel test
node deploy/p7-console-vercel/upload.mjs --spool <local-spool> --token-file <private-token-file>
```

The local producer writes `objects/<sha256>.json.gz` and atomic `index.json`.
SHA256 identifies uncompressed canonical JSON. Index schema is
`asterion.p7.cloud-index/v1`; `generation` hashes the canonical `routes` map.
Route entries contain `sha256`, `blobPath`, `contentType`, `bytes` and
`compressedBytes`. The uploader validates every route before writing, combines
gzip objects into approximately 1 MiB immutable packs, and adds `packSHA`,
`packPath`, `packBytes` and `offset` to each cloud route. It retains the producer
hash as `logicalGeneration` and recomputes physical `generation`. Readers verify
the whole pack hash and requested object's hash, source, revision and cursor.
Both objects and responses are bounded to 4,500,000 bytes.

The only overwrite is `p7-console/latest.json`, after every referenced pack is
durable. Failed uploads preserve the previous complete cloud index. The local
private `cloud-upload-state.json` receipt records successful immutable packs,
their retained byte sizes, monthly PUT attempts including failures, and the
committed generation. Keep this receipt across scans and restarts. Unchanged
logical generations perform no cloud operations. No HEAD or LIST is used.
Partial uploads resume from their receipts. Uploaded packs are never deleted
automatically; old revision-bound URLs remain indexed by the producer.

The default guard allows 1,500 PUT attempts per UTC calendar month, with a hard
configuration ceiling of 2,000 (`--max-upload-operations`). Writes stop before
exceeding 900 MiB of known retained storage; 750 MiB triggers a visible warning.
The receipt accounts for this application's managed uploads, not unrelated
objects or activity in the store. Use a dedicated private store. The producer
coalesces uploads, normally at 1,800 seconds, with saved-progress priority at a
minimum of 60 seconds. Captures may occur more often without writing remotely.
Quota exhaustion returns a closed `cloud-upload-quota-exceeded` or
`cloud-storage-quota-exceeded` diagnostic; raw SDK errors and credentials are
never printed. This finite guard does not imply unlimited free hosting.

Metadata responses use `no-store`; the server reuses an authenticated index for
up to 60 seconds and immutable pack bytes in a bounded 32 MiB process cache.
Revision-bound detail/frame responses are immutable. `/api/sync-status` exposes
the last committed data timestamp, generation, upload counter and storage
footprint. The timestamp measures the last data update, not a heartbeat; an
unchanged generation needs no write. Cloud overview, session, unsealed replay
and sync status poll every five minutes; opening a game or replay reads
immediately. Local UI polling is unchanged. Local
publisher diagnostics distinguish a failed capture, failed upload and quota
guard; the remote page retains the last complete view.

SDK behavior was checked against the official
[Blob SDK](https://vercel.com/docs/vercel-blob/using-blob-sdk) and
[private storage](https://vercel.com/docs/vercel-blob/private-storage) documents.
`@vercel/blob` is pinned to 2.8.0; private reads use `get()` streams, with
`useCache: false` for the mutable pointer. The runtime token is injected through
`BLOB_READ_WRITE_TOKEN`; local upload uses only an explicit environment value or
token file. Environment files, tokens and Vercel linkage are excluded from git.
