# P7 Vercel Console Synchronization Implementation Plan

> For agentic workers: execute with explicit file ownership; preserve other workers and background games.

**Goal:** Deploy the existing observation/replay console on Vercel and continuously push local public data to cloud storage.

**Architecture:** [Approved synchronization boundary](../specs/2026-10-06-p7-vercel-console-sync.md); private Blob objects, immutable content hashes, commit cloud index last. Local producer owns synchronization; cloud read API never contacts local machine.

**Tech Stack:** Existing Python console exporter, Node Vercel Functions, official @vercel/blob SDK, gzip JSON, existing JS/CSS.

## Task1 — Local producer

Owner: campaign_repair. Files tools/p7_console_cloud_sync.py and focused unittest. Read public HTTP projections from127.0.0.1:57515; capture source-bound manifests/details/pages/previews, stage compressed objects and an exact route index. SHA-equal object reuse; changes retry on409. No raw/private trace or tokens. Emit finite diagnostics and synchronization timestamps. Publisher transport invokes the deployment-owned Blob uploader; credentials explicitly supplied by operator.

- [x] Capture25/183 and allcurrent saved public routes.
- [x] Bind metadata/pages to source/revision, publish complete index last, preserve prior view on failures.
- [x] Incremental capture30seconds, normal upload1800seconds, saved-progress upload at least60seconds apart, own lock and finite request controls; test changed-source and interrupted-upload boundaries.

## Task2 — Vercel read app and upload transport

Owner: dedicated implementation worker. Files deploy/p7-console-vercel/ only. Serve same-shaped cloud APIs and existing consoleUI; no local network proxy. Node SDK privateBlob get/put, gzip objects, fixed routeindex. Readonly controls: no operator POST API. Credentials excluded from browser/deployment source.

- [x] Exact cloud route resolution/publicshape response plus readonly UI; no arbitrary URL/path access.
- [x] CLI uploader handles content-addressed immutable objects and final index commit using explicit token.
- [x] Focused Node checks reject missing/corrupt source and unauthorized mutation.

## Task3 — Integration and deployment

Owner: root. Verify existingVercel login, create separateasterion-p7-console project/privateBlob store, keep existingprojects unchanged. Inspect/measure cloud dataset, completebootstrap then deployproduction and startownedlocal sync daemon. Verify hosted25gamecounts/replaycognition/framepages and a laterautomaticindex; fixed57515/fourguests remain. Commit implementation and checkpoint.

- [x] Named checks and changed-code review.
- [x] Initial Blob push and production deployment.
- [x] Actual cloud read/sync evidence, localactivity markers, durable deployment instructions and focusedcommit.

## Released evidence

- Production: https://asterion-p7-console.vercel.app, readonly public projection; initial25games/183previews and saved frame/cognition route hashes verified.
- Local producer tests and10cloud Node checks pass; independent changed-code review clear. Actual HTTP replay probes include AR25L8, SP80L1 and RE86L8 last frames.
- Automatic publisher PID46549 advanced the cloud pointer without redeploy; uploads preserve previous complete generation on capture failures. Initial31packs/4.9MBgzip; later retained objects below7MB,46attemptedPUTs. Hobby quota is account-wide; local1500-attempt guard reserves margin and does not measure unrelated usage.
- User opening/switch rule: saved full completion opensL1; partial completion opens first unsaved level. Polling retains viewing selection. Core73cc02ed51relatedDOM checks and cloudf5d76bad10Node checks pass; actualcloudinitialAR25L1/read-onlyGET7/pending0/exit0 verified; final localfullpromotion25/provider0,558resourcehashes andsame-portserviceupdatePASS; bothactualHTML/GETs showAR25L1. Deployment proofs recorded in live checkpoint.
- Chrome connection selection succeeded, but browser command transport timed out twice; HTTP/DOM checks do not establish Chrome visual acceptance.
