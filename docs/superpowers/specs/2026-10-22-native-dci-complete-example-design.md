# Native DCI complete example

## Decision

`prepare_native_application` stays the one Native door. This spec adds one application on that door: `native.dci-complete@1.0.0`. It runs the existing DCI complete chain for one labeled question: retrieval, Judge, the one-case tally, analysis, and export.

The corpus is the host option `corpus.local-root`. The Judge is an operator-managed host service supplied by the example. The product factory `_open_answer_judge_service` stays locked to provider `dci-agent-lite` and application `dci.complete-application@1.0.0`. The example does not call that factory.

`src/asterion/agents/native/application.py` and `src/asterion/agents/native/__init__.py` stay as they are. The existing entry already accepts one option map and one managed-service map whose keys together equal the assembly host capabilities and do not overlap. `native.packages@1.0.0` stays first in the provider tuple. `native.dci-research@1.0.0`, `native.controlled-code@1.0.0`, and `examples/applications/native_dci.py` stay as they are.

This follows decision D-2026-10-20-04. It does not add a decision record. Prime stays on `prepare_prime_application`. The one question does not close D-2026-07-31-02 and does not authorize a dataset run.

This document does not authorize `make native-dci-complete-example`. Implementation proves the preset with injected configuration. It does not call a model.

## Application

Add `src/asterion/applications/native/assemblies/native-dci-complete.json`.

- Protocol `asterion.application-assembly/v1`.
- Application `native.dci-complete` at version `1.0.0`.
- Runtime `pi.reference`.
- Package `dci@1.0.0` only.
- Capabilities, in this order: `dci.analysis@1.0.0`, `dci.benchmark@1.0.0`, `dci.evaluation@1.0.0`, `dci.export@1.0.0`, `dci.research@1.0.0`, `policy.local-corpus@1.0.0`.
- Host capabilities `corpus.local-root` and `evaluation.answer-judge`.
- Empty host policies, host events, and host artifacts.

`src/asterion/applications/native/provider.py` appends this application after `native.controlled-code`. The provider id stays `native`. The provider source does not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`. There is no new `asterion.application_index` entry. `pyproject.toml` stays unchanged.

`tools/check_promotion.py` adds `applications/native/assemblies/native-dci-complete.json` with schema `asterion.application-assembly/v1`.

The installed `dci` package already binds the complete stages. When the input protocol is `asterion.dci.complete-input/v1`, the transitional research binding delegates to `DciCompleteResearchImplementation`. Evaluation, benchmark, analysis, and export stay on their complete bindings. This spec adds no capability implementation.

`policy.local-corpus` stays declarative. One composed run executes the other five capabilities. Research calls `runtime.run` once, with the question text alone. Evaluation calls `evaluation.answer-judge`. Benchmark records `{"total": 1, "judged": 1, "correct": 0 or 1, "failed": 0}`. Analysis aggregates that one row. Export records `analysis_sha256` and `total`. The entry still creates one runtime.

## Question and input

The question is the existing `BASIC_CASES` entry whose `case_id` is `runtime-context-and-judge`. At the time of this spec that entry is:

```text
Read the files in the current directory. Do not use web search. Use rg instead of grep when searching. Question: In the Bonang Matheba interview where the third-to-last question asks about the origin of the name given to her by radio listeners, what is the interviewer's first name? Answer with just the first name and one supporting file path.
```

Its `corpus_subdir` is `bc_plus_docs`. Its `expected_answer` is `Adaku`.

The example selects that entry from `BASIC_CASES` in `asterion.capabilities.dci.implementation.reproduction.verification`. It requires exactly one match and a non-empty string `expected_answer`. It builds one JSON object whose keys are exactly `protocol`, `question`, and `gold_answer`. `protocol` is `INPUT_PROTOCOL` from `asterion.capabilities.dci.implementation.complete`. `question` and `gold_answer` come from that entry. The object is the `run` input text. The London retrieval question stays on `native.dci-research` and is not given a gold answer here.

## Development example

Add `examples/applications/native_dci_complete.py`. Do not use `from __future__ import annotations`.

`run_native_dci_complete(*, runtime_factories, runtime_options, corpus_root, managed_judge, run_id)` prepares `native.dci-complete` at version `1.0.0` and runs it once. The host option is `corpus.local-root` with `root` set to `corpus_root`. The managed map contains `evaluation.answer-judge` and the caller-supplied async context manager. The helper calls `prepare_native_application` and then `run`. It does not load `.env`, resolve an assembly, open `HostServiceFactoryRegistry` itself, or select an application by list position.

The live path owns the real Judge. `open_managed_answer_judge(config)` is an async context manager in the example. It yields an object with `public_identity` and `async judge(*, question, gold_answer, predicted_answer, signal)`. `public_identity` is `judge_public_identity(config)` with the key `judge_api_key_env` removed. `judge` calls `judge_answer_async` and returns that mapping only when `is_correct` is a bool and `judge_request_fingerprint` is a str. If `signal` is not `None` and `signal.cancelled` is true before the call returns, the wrapper cancels the task and the call fails. `JudgeConfig`, `judge_answer_async`, and `judge_public_identity` come from `asterion.capabilities.dci.implementation.evaluation.judge`. The example does not import or call `_open_answer_judge_service`.

`main` is the only function that calls `load_dotenv(root / ".env", override=False)` when that file exists. Importing the module does not read `.env` and does not spawn Pi.

`examples/README.md` gains one sentence: `` `applications/native_dci_complete.py` runs the Native DCI complete application through `prepare_native_application`. `` The retrieval sentence stays.

## Live preset

Add `examples/native_dci_complete_example.sh` with mode `0755`, and the Make target `native-dci-complete-example`.

The shell is:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --with "python-dotenv>=1.0.0" python examples/applications/native_dci_complete.py --live
```

The shell does not source a file and does not use `set -a`. The Make recipe does not call the shell. The human command is `make native-dci-complete-example`. The recipe line, starting with a tab, is:

```text
$(UV_BIN) run --with "python-dotenv>=1.0.0" python examples/applications/native_dci_complete.py --live
```

`.PHONY` lists `native-dci-complete-example` beside `native-dci-example`. The help line `DCI bounded examples:` gains `native-dci-complete-example` at the end. The target sits directly after `native-dci-example`. `pyproject.toml` stays unchanged. `python-dotenv` arrives through `--with`, as it does for the retrieval preset.

`main` accepts only `--live`. Any other argument list prints `native-dci-complete-example: use --live` to stderr and returns 2.

Readiness uses the git repository root and the same path checks as `examples/applications/native_dci.py`. A failed check prints one public reason to stderr, prints nothing to stdout, returns 2, and does not prepare or run:

- `missing DCI_PROVIDER`
- `missing DCI_MODEL`
- `pi checkout is unavailable`
- `node executable is unavailable`
- `agent directory is unavailable`
- `corpus is unavailable`
- `answer judge service is unavailable`
- `evidence parent is unavailable`

The corpus directory is `$ASTERION_DCI_CORPUS_ROOT/bc_plus_docs` when that variable is an absolute path. Otherwise it is `<repository>/corpus/bc_plus_docs`. It must pass `path_is_exact(..., require_directory=True)`, and `any(item.is_file() for item in directory.rglob("*"))` must be true. The preset does not require `wiki_dump.jsonl`.

The Judge check calls `JudgeConfig.from_env()` and requires a non-empty `api_key`. Any failure becomes `answer judge service is unavailable`. The preset does not print the exception, the config, or the key.

Readiness creates `<repository>/outputs` when that directory is missing. An existing outputs directory must be a real non-symlink directory. The evidence root `<repository>/outputs/native-dci-complete-example` may be missing. The preset does not delete it. A failed evidence check uses `evidence parent is unavailable`.

The run id is `native-dci-complete-` plus `uuid.uuid4().hex`.

The factory options match the retrieval preset, with these values:

- `cwd` is the absolute `bc_plus_docs` directory checked above.
- `evidence_root` is `<repository>/outputs/native-dci-complete-example`.
- `tools` is `read,grep`.
- `max_turns` is `6`.
- `command`, `environment`, `provider`, and `model` follow the retrieval preset.
- The preset does not pass `cwd_host_capability`, a thinking level, `bash`, or `rg`.

On success the preset prints one JSON object, with sorted keys, and returns 0. The keys are exactly `application_id`, `correct`, `run_id`, `status`, and `total`. `application_id` is `native.dci-complete`. `status` is `completed`. `total` is the integer `1`. `correct` is the integer `0` or `1`. Those two numbers are `value["total"]` and `value["correct"]` on the single artifact whose `media_type` is `application/vnd.dci.benchmark+json`. `value["judged"]` is `1` and `value["failed"]` is `0`. Success also requires one artifact whose `media_type` is `application/vnd.dci.export+json` and whose `value["total"]` is the integer `1`, plus event types `research.completed`, `evaluation.completed`, `benchmark.completed`, `analysis.completed`, and `export.completed`. The stdout object does not include the question, the gold answer, the prediction, the Judge reason, the fingerprint, `analysis_sha256`, or any credential.

A chain that returns without that tally, and any runtime or capability exception, prints the three-key object `application_id`, `run_id`, and `status` with `status` `failed`, prints `native-dci-complete-example: run failed` to stderr, and returns 1. It does not print the exception. A wrong answer that still produces `correct` `0` and `total` `1` is a completed run and returns 0.

`execute_live` follows the retrieval preset. An injected `prepare` is called, and a `prepare` that returns raises `RuntimeError("live prepare injection returned")`, so that return is not reported as success. The real path calls `run_native_dci_complete` with `default_runtime_factory_registry()`, the live runtime options, the resolved corpus, the managed Judge, and the run id. `main` resolves the repository root before `run_live`. A missing root propagates and is not one of the readiness reasons.

## Provider-free tests

Extend `tests/test_native_package_host.py`. The provider application tuple becomes:

- `native.packages@1.0.0`
- `native.dci-research@1.0.0`
- `native.controlled-code@1.0.0`
- `native.dci-complete@1.0.0`

`resolved.applications[0]` stays `native.packages`. The application index still contains `native.packages__1.0.0` and does not contain `native.dci-complete__1.0.0`. The selected complete application has package `dci@1.0.0` and host capabilities `corpus.local-root` and `evaluation.answer-judge`.

Extend `tests/test_native_application.py`. The complete fixture runtime yields one answer artifact whose uri is `final.txt`, and `completed_run_dir(run_id)` is a directory that contains that file as a regular non-symlink file with mode `0o600` and non-empty UTF-8 text. The existing retrieval fixture is not reused for this chain. The fake Judge is an async context manager whose `public_identity` is a JSON-safe mapping and whose `judge` returns `is_correct` and a string `judge_request_fingerprint`.

The tests check all of the following:

- Preparation does not call the runtime factory.
- Preparation fails when the corpus option is missing, when the managed Judge is missing, and when `corpus.local-root` is present in both maps.
- `run` calls the runtime once. The runtime input text equals the `runtime-context-and-judge` question quoted above. It is not the JSON envelope.
- The Judge receives the question, gold `Adaku`, and the text written to `final.txt`.
- One subtest with `is_correct` true produces benchmark `correct` `1`, export `total` `1`, and the five completion events.
- One subtest with `is_correct` false produces benchmark `correct` `0` and still completes the export.
- The entry sources `agents/native/application.py`, `agents/native/__init__.py`, and `applications/native/provider.py` still do not contain `asterion.capabilities.dci`.
- The helper source contains `prepare_native_application`. `load_dotenv` appears only in `main`, with `override=False`.
- Readiness returns 2, with empty stdout, for a missing `bc_plus_docs` directory and for a Judge config without an api key. Neither case calls prepare.
- The success status line contains `total` and `correct` and does not contain the gold answer, the predicted sentinel, or a sentinel api key.
- The shell and Make target contain the `--with "python-dotenv>=1.0.0"` recipe. The shell does not contain `source ` or `set -a`.

The focused command is:

```bash
uv run --with "python-dotenv>=1.0.0" python -m unittest -v tests.test_native_application tests.test_native_package_host
```

The promotion path set is:

```bash
uv run python -c "import runpy; runpy.run_path('tools/check_promotion.py', run_name='promotion_path_check')"
```

A missing offline Node executable stays outside this spec. `docs/status/INDEX.md` links this spec and records that implementation has not started and that no model call is authorized. Implementation leaves that sentence in place until the code lands.

## Out of scope

- Editing `src/asterion/agents/native/application.py` or the Native package exports.
- Opening `_open_answer_judge_service` to provider `native`.
- A second product door for `dci.complete-application`.
- A change to `native.dci-research`, its live preset, or `examples/applications/native_dci.py`.
- Creating `wiki_dump.jsonl` or any corpus file.
- Running `make native-dci-example` or `make native-dci-complete-example`.
- A batch, the 50-case closure in D-2026-07-31-02, `dci.local-benchmark-application`, or a full dataset run.
- A Native copy of Prime P1–P7, or a change to `prepare_prime_application`.
- A Native CLI, a new `application_index` row, or a `pyproject.toml` dependency edit.
- A change to `make dci-preflight` or `asterion-dci run`.
- A decision record, a journal line, or an update to `CURRENT-STATE.md`, `RESUME-NEXT-SESSION.md`, or `MEMORY.md`.
