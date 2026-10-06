# P7 Vercel Console Synchronization

User-authorized deployment; user explicitly requires local-to-cloud synchronization and selects observation/replay only remotely. Local four-game solving and port57515 continue.

## Architecture

Local publisher reads only public console projections, validates source/revision/frame cursors, and pushes immutable gzip JSON objects, packed into approximately1MiB cloud objects, into a private Vercel Blob store. It publishes a cloud index last, after every referenced object is durable. Vercel serves the existing console UI and same-shaped read APIs entirely from cloud objects. No tunnel, inbound local network connection, remote runner, raw trace upload, or operator credentials in browser data.

## Data and freshness

Bootstrap the25-game catalog/183initialviews, current selected saved game manifests/details/all32-framepages, overview and safe session/attempt state. Immutable route IDs and generations bind frames/actions/cognition together. Subsequent scans reuse SHA256-equal objects and publish only new/changed projections. Index pointers update last; failed uploads retain the last complete cloud view and visible synchronization age. The publisher scans every30seconds and coalesces ordinary uploads every30minutes; saved progress has priority with a60second minimum, with one writer and finite perrequest controls. A source changing during capture is retried, never mixed with another source or replaced by empty records.

## Remote behavior

Observe progress and replay using existing compact UI. The user prioritizes sharing major progress and saved replays; remote polling runs every5minutes, while opening a game reads immediately. Explicit game switches openL1 for full saved completion and the first unpassed level otherwise; polling preserves selection. Remote controls are explicitly read-only; POST play/start/pause/stop routes return405 and visible controls remain disabled/labeled. Local controls and solving remain independent. Initial preparation/parsing happens in the local background publisher, never on remote game selection. Metadata and frame pages remain separate; source-bound pages serve at most32frames; the server authorizes private Blob reads.

## Boundaries

Only existing public shapes are uploaded. Store token stays operator/server-side, .env/private files excluded from git/deployment. Private blobs require authorization. Cloud index binds route keys to exact content hashes and public object types; no arbitrary URL/path proxy or filesystem lookup. Failed sync must be observable and must not invalidate local certificates or scores.

## Free-plan controls

Verified2026-10-06: team plan is Hobby. Official Blob allowances:1GB storage,10GB downloads,10000 simple and2000 advanced operations. Publisher packs files and reuses immutable pack receipts, never performs a LIST for normal sync, and only publishes changed logical generations. Every attempted PUT is counted locally before the call, including failures. Operator guard1500attempts/month reserves margin for unrelated usage; this is a local guard, not an account-wide usage meter. Cloud retained pack size is tracked without listing, warns750MiB and rejects900MiB. No automatic plan upgrade. Remote metadata refresh and public errors expose data-update age; source capture and upload status remain distinct.

## Acceptance

A deployed Vercel URL shows25games and real current saved results; sampled old/new games show exact action counts/cognition/lastframes. Updating local data yields a later cloud index automatically without redeploy. Local solving keeps four slots and original deadlines. Record uncompressed/compressed bytes and deployed evidence; no README expansion requested.
