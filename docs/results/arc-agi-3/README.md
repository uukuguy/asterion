# Asterion Prime P7 public-game result

The 2026-10-07 research snapshot solves all 25 public ARC-AGI-3 games, 183/183 levels, with 6781 saved route actions using `gpt-6.1-sol` and seed 0. The local saved-route score is 100.00. The [machine-readable result](p7-public-2026-10-07.json) lists per-game and per-level action counts and the final runtime code snapshot.

The new [Competition Mode scorecard](https://arcprize.org/scorecards/60c10b53-9b8d-4af9-aae7-85f81543198a) has normally closed with an official score of **100.00**, 25/25 games, 183/183 levels, and 6781 actions. The closed receipt matches every selected game route; all 25 source certificates, winner pointers and source metadata remain unchanged.

This result followed iterative local research, failed attempts, generic infrastructure repairs between attempts, operator-controlled retries and selected cognition resets, and accumulated experience. The LLM inside P7 generated game hypotheses, executable models and candidate plans. Final software changes include [compact actor context delivery](https://github.com/uukuguy/asterion/commit/b5c2469303bec10a99dfe87e2bd473efd683e278) and [RESET episode isolation](https://github.com/uukuguy/asterion/commit/2f258ff3e74478805f63e08daa437acf9ca53a21); these change generic research machinery. The published final commit does not imply all routes were produced by that one fixed version.

The official run replays the saved certified routes without a model call. It validates these routes in the official environment; it does not evaluate the solver afresh on unseen games. A clean checkout can run the producing system but does not contain this operator's historical experience or certified roster. The linked result concerns public games; total research cost was not audited.

The [read-only console](https://asterion-p7-console.vercel.app) exposes public progress, replay frames and recorded game understanding. The code that creates hypotheses, runs experiments and solves games is in the main repository; saved actions alone are not the method.

The [community submission criteria](https://github.com/arcprize/ARC-AGI-Community-Leaderboard/blob/main/CONTRIBUTING.md) call for a general-purpose open producing system, a novel contribution, and an ARC-AGI-3 Competition scorecard. They do not require an unattended, empty-history 100-score run; the evaluation protocol above describes how this result was obtained.
