"""Safe OpenAI-compatible judge boundary for the independent Asterion DCI product."""

from __future__ import annotations

import hashlib
import asyncio
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


DEFAULT_JUDGE_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_JUDGE_API = "chat-completions"
DEFAULT_JUDGE_MODEL = "deepseek-v4-flash"
DEFAULT_JUDGE_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_JUDGE_THINKING = "disabled"
OFFICIAL_OPENAI_BASE_URL = "https://api.openai.com/v1"
JUDGE_VERDICT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "is_correct": {"type": "boolean"},
        "normalized_prediction": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["is_correct", "normalized_prediction", "reason"],
    "additionalProperties": False,
}


class DciJudgeError(RuntimeError):
    """Safe public error for judge configuration, transport, or response failures."""


@dataclass(frozen=True)
class JudgeConfig:
    """Validated public judge settings with an environment-only credential."""

    base_url: str = DEFAULT_JUDGE_BASE_URL
    api: str = DEFAULT_JUDGE_API
    model: str = DEFAULT_JUDGE_MODEL
    timeout_seconds: int = 120
    max_output_tokens: int = 1024
    json_mode: bool = True
    strict_json_schema: bool = False
    responses_store: bool = False
    thinking: str = DEFAULT_JUDGE_THINKING
    input_price_per_1m: float = 0.0
    cached_input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0
    api_key_env: str = DEFAULT_JUDGE_API_KEY_ENV
    api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        base_url = self.base_url.strip().rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        try:
            parsed.port
        except ValueError as error:
            raise ValueError(
                "Judge base URL must be an absolute HTTP(S) URL with a host"
            ) from error
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError(
                "Judge base URL must be an absolute HTTP(S) URL with a host"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "Judge base URL must not include credentials, query data, or fragments"
            )
        if not self.model.strip():
            raise ValueError("Judge model must not be empty")
        if (
            not math.isfinite(self.timeout_seconds)
            or not math.isfinite(self.max_output_tokens)
            or self.timeout_seconds <= 0
            or self.max_output_tokens <= 0
        ):
            raise ValueError(
                "Judge timeout and output token limit must be greater than zero"
            )
        if self.thinking.strip().lower() not in {"auto", "enabled", "disabled", "omit"}:
            raise ValueError("Judge thinking mode is not recognized")
        prices = (
            self.input_price_per_1m,
            self.cached_input_price_per_1m,
            self.output_price_per_1m,
        )
        if not all(math.isfinite(price) for price in prices) or min(prices) < 0:
            raise ValueError("Judge token prices must be finite and not negative")
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "api", _normalize_api(self.api))
        object.__setattr__(self, "model", self.model.strip())
        object.__setattr__(self, "thinking", self.thinking.strip().lower())
        object.__setattr__(self, "api_key_env", self.api_key_env.strip())

    @classmethod
    def from_env(cls) -> "JudgeConfig":
        """Load shared judge settings with Asterion compatibility aliases."""

        api_key_env = _judge_env("API_KEY_ENV", DEFAULT_JUDGE_API_KEY_ENV)
        return cls(
            base_url=_judge_env("BASE_URL", DEFAULT_JUDGE_BASE_URL),
            api=_judge_env("API", DEFAULT_JUDGE_API),
            model=_judge_env("MODEL", DEFAULT_JUDGE_MODEL),
            timeout_seconds=_judge_env_int("TIMEOUT_SECONDS", 120),
            max_output_tokens=_judge_env_int("MAX_OUTPUT_TOKENS", 1024),
            json_mode=_judge_env_bool("JSON_MODE", True),
            strict_json_schema=_judge_env_bool("STRICT_JSON_SCHEMA", False),
            responses_store=_judge_env_bool("RESPONSES_STORE", False),
            thinking=_judge_env("THINKING", DEFAULT_JUDGE_THINKING),
            input_price_per_1m=_judge_env_float("INPUT_PRICE_PER_1M", 0.0),
            cached_input_price_per_1m=_judge_env_float(
                "CACHED_INPUT_PRICE_PER_1M", 0.0
            ),
            output_price_per_1m=_judge_env_float("OUTPUT_PRICE_PER_1M", 0.0),
            api_key_env=api_key_env,
            api_key=os.environ.get("DCI_EVAL_JUDGE_API_KEY", "").strip()
            or os.environ.get("ASTERION_DCI_JUDGE_API_KEY", "").strip()
            or os.environ.get(api_key_env, "").strip(),
        )

    @property
    def endpoint(self) -> str:
        suffix = "responses" if self.api == "responses" else "chat/completions"
        return f"{self.base_url}/{suffix}"

    @property
    def effective_thinking(self) -> str | None:
        if self.thinking == "omit":
            return None
        if self.thinking != "auto":
            return self.thinking
        if "deepseek" in self.model.lower() or "deepseek.com" in self.base_url.lower():
            return "disabled"
        return None

    def public_dict(self) -> dict[str, object]:
        return {
            "judge_base_url": self.base_url,
            "judge_api": self.api,
            "judge_model": self.model,
            "judge_api_key_env": self.api_key_env,
            "judge_timeout_seconds": self.timeout_seconds,
            "judge_max_output_tokens": self.max_output_tokens,
            "judge_json_mode": self.json_mode,
            "judge_strict_json_schema": self.strict_json_schema,
            "judge_responses_store": self.responses_store,
            "judge_thinking": self.effective_thinking,
            "judge_input_price_per_1m": self.input_price_per_1m,
            "judge_cached_input_price_per_1m": self.cached_input_price_per_1m,
            "judge_output_price_per_1m": self.output_price_per_1m,
        }


def build_judge_request(
    config: JudgeConfig, *, question: str, gold_answer: str, predicted_answer: str
) -> dict[str, object]:
    """Build the complete request whose canonical form is the cache identity."""

    messages = _judge_messages(question, gold_answer, predicted_answer)
    if config.api == "responses":
        payload: dict[str, object] = {
            "model": config.model,
            "max_output_tokens": config.max_output_tokens,
            "input": messages,
        }
        if config.base_url == OFFICIAL_OPENAI_BASE_URL or config.responses_store:
            payload["store"] = config.responses_store
        if config.strict_json_schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "judge_verdict",
                    "strict": True,
                    "schema": JUDGE_VERDICT_SCHEMA,
                }
            }
        return payload
    payload = {
        "model": config.model,
        "max_tokens": config.max_output_tokens,
        "messages": messages,
    }
    if config.json_mode:
        payload["response_format"] = {"type": "json_object"}
    if config.effective_thinking is not None:
        payload["thinking"] = {"type": config.effective_thinking}
    return payload


def _judge_messages(
    question: str, gold_answer: str, predicted_answer: str
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are grading a question-answer benchmark. "
                "Mark the prediction correct only if it identifies the same final answer as the gold answer. "
                "Ignore case, surrounding punctuation, whitespace, and extra explanation or supporting file paths. "
                "Do not give partial credit. Return exactly one compact JSON object. "
                'Example JSON: {"is_correct":true,"normalized_prediction":"example",'
                '"reason":"same answer"}.'
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"Gold answer:\n{gold_answer}\n\n"
                f"Predicted answer:\n{predicted_answer or '[empty]'}\n\n"
                'Return JSON with keys "is_correct" (boolean), "normalized_prediction" (string), and "reason" (string).'
            ),
        },
    ]


def judge_request_fingerprint(
    *, config: JudgeConfig, question: str, gold_answer: str, predicted_answer: str
) -> str:
    return _fingerprint(
        config,
        build_judge_request(
            config,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=predicted_answer,
        ),
    )


def judge_prompt_contract_sha256(config: JudgeConfig) -> str:
    """Return the canonical digest of the body-free Judge prompt contract."""

    return _canonical_json_sha256(
        build_judge_request(
            config,
            question="[question]",
            gold_answer="[gold-answer]",
            predicted_answer="[predicted-answer]",
        )
    )


def judge_request_shape_sha256(config: JudgeConfig) -> str:
    """Return the canonical digest of one sentinel-shaped Judge request."""

    request = build_judge_request(
        config,
        question="[question]",
        gold_answer="[gold-answer]",
        predicted_answer="[predicted-answer]",
    )
    messages_key = "input" if config.api == "responses" else "messages"
    messages = request.get(messages_key)
    if isinstance(messages, list):
        request[messages_key] = [
            {**message, "content": "[content]"}
            if isinstance(message, dict) and "content" in message
            else message
            for message in messages
        ]
    return _canonical_json_sha256(request)


def judge_public_identity(config: JudgeConfig) -> dict[str, object]:
    """Return complete credential- and body-free Judge cache evidence."""

    return {
        **config.public_dict(),
        "endpoint": config.endpoint,
        "request_shape_sha256": judge_request_shape_sha256(config),
        "prompt_contract_sha256": judge_prompt_contract_sha256(config),
    }


def _canonical_json_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def judge_answer_sync(
    *,
    config: JudgeConfig,
    question: str,
    gold_answer: str,
    predicted_answer: str,
    cancel_event: threading.Event | None = None,
) -> dict[str, object]:
    """Use one bounded retry budget and return only validated safe fields."""

    request_payload = build_judge_request(
        config,
        question=question,
        gold_answer=gold_answer,
        predicted_answer=predicted_answer,
    )
    fingerprint = _fingerprint(config, request_payload)
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    request = urllib.request.Request(
        config.endpoint,
        data=json.dumps(request_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    parsed: dict[str, object] | None = None
    usage: dict[str, object] | None = None
    last_failure = "response"
    for attempts in range(1, 4):
        if cancel_event is not None and cancel_event.is_set():
            raise DciJudgeError("DCI judge request was cancelled")
        try:
            with _open_judge_request(
                request, timeout_seconds=config.timeout_seconds
            ) as response:
                candidate = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            error.close()
            if not _retryable_http_status(error.code):
                raise DciJudgeError("DCI judge request was rejected") from error
            last_failure = "transport"
            if attempts == 3:
                break
            _wait_before_retry(
                _retry_delay(attempts, retry_after),
                cancel_event,
            )
            continue
        except (OSError, ValueError, urllib.error.URLError):
            last_failure = "transport"
            if attempts == 3:
                break
            _wait_before_retry(_retry_delay(attempts, None), cancel_event)
            continue
        if cancel_event is not None and cancel_event.is_set():
            raise DciJudgeError("DCI judge request was cancelled")
        if not isinstance(candidate, dict):
            if attempts < 3:
                _wait_before_retry(_retry_delay(attempts, None), cancel_event)
            continue
        parsed = _parse_verdict(candidate, config.api)
        usage = _normalize_usage(candidate.get("usage"))
        if parsed is not None and usage is not None:
            break
        parsed = None
        if attempts < 3:
            _wait_before_retry(_retry_delay(attempts, None), cancel_event)
    if parsed is None:
        if last_failure == "transport":
            raise DciJudgeError("DCI judge transport failed")
        raise DciJudgeError("DCI judge response was invalid")
    assert usage is not None
    return {
        **config.public_dict(),
        "judged_at": datetime.now(timezone.utc).isoformat(),
        "attempts": attempts,
        "judge_request_fingerprint": fingerprint,
        "is_correct": parsed["is_correct"],
        "normalized_prediction": str(parsed.get("normalized_prediction", "")),
        "reason": str(parsed.get("reason", "")),
        "usage": usage,
        "cost_estimate_usd": estimate_judge_cost(usage, config),
    }


async def judge_answer_async(
    *, config: JudgeConfig, question: str, gold_answer: str, predicted_answer: str
) -> dict[str, object]:
    """Run the blocking transport without releasing cancellation before it closes."""

    cancel_event = threading.Event()
    work = asyncio.create_task(
        asyncio.to_thread(
            judge_answer_sync,
            config=config,
            question=question,
            gold_answer=gold_answer,
            predicted_answer=predicted_answer,
            cancel_event=cancel_event,
        )
    )
    try:
        await asyncio.wait({work})
        return work.result()
    except asyncio.CancelledError:
        cancel_event.set()
        await _drain_cancelled_work(work)
        raise


async def _drain_cancelled_work(work: asyncio.Task[object]) -> None:
    """Consume repeated cancellation until the already-started thread has closed."""

    while not work.done():
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        try:
            await asyncio.wait({work})
        except asyncio.CancelledError:
            continue
    try:
        work.result()
    except Exception:
        pass


def _retryable_http_status(status: int) -> bool:
    return status in {408, 409, 429} or 500 <= status <= 599


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    fallback = min(30.0, 0.25 * (2 ** (attempt - 1)))
    if retry_after is None:
        return fallback
    try:
        seconds = float(retry_after.strip())
    except ValueError:
        try:
            parsed = parsedate_to_datetime(retry_after)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
    if not math.isfinite(seconds) or seconds < 0 or seconds > 30:
        return fallback
    return seconds


def _wait_before_retry(seconds: float, cancel_event: threading.Event | None) -> None:
    if cancel_event is None:
        time.sleep(seconds)
    elif cancel_event.wait(seconds):
        raise DciJudgeError("DCI judge request was cancelled")


def _normalize_api(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"response", "responses"}:
        return "responses"
    if normalized in {"chat", "chat-completion", "chat-completions", "completions"}:
        return "chat-completions"
    raise ValueError("Judge API must be responses or chat-completions")


def _judge_env(name: str, default: str) -> str:
    return os.environ.get(
        f"DCI_EVAL_JUDGE_{name}",
        os.environ.get(f"ASTERION_DCI_JUDGE_{name}", default),
    )


def _judge_env_int(name: str, default: int) -> int:
    try:
        return int(_judge_env(name, str(default)))
    except ValueError as error:
        raise ValueError(f"DCI_EVAL_JUDGE_{name} must be an integer") from error


def _judge_env_float(name: str, default: float) -> float:
    try:
        value = float(_judge_env(name, str(default)))
    except ValueError as error:
        raise ValueError(f"DCI_EVAL_JUDGE_{name} must be a number") from error
    if not math.isfinite(value):
        raise ValueError(f"DCI_EVAL_JUDGE_{name} must be a finite number")
    return value


def _judge_env_bool(name: str, default: bool) -> bool:
    value = _judge_env(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"DCI_EVAL_JUDGE_{name} must be a boolean")


def _fingerprint(config: JudgeConfig, request_payload: dict[str, object]) -> str:
    public_identity = judge_public_identity(config)
    public_identity.pop("judge_api_key_env", None)
    canonical = json.dumps(
        {
            "configuration": public_identity,
            "request_sha256": _canonical_json_sha256(request_payload),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _open_judge_request(
    request: urllib.request.Request, *, timeout_seconds: int
) -> Any:
    opener = urllib.request.build_opener(_RejectRedirect())
    return opener.open(request, timeout=timeout_seconds)


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, request: urllib.request.Request, *_: object
    ) -> urllib.request.Request:
        raise urllib.error.HTTPError(
            request.full_url, 302, "Judge redirects are not permitted", None, None
        )


def _parse_verdict(
    response_payload: dict[str, object], api: str
) -> dict[str, object] | None:
    text = (
        _responses_content(response_payload)
        if api == "responses"
        else _chat_content(response_payload)
    )
    if not isinstance(text, str):
        return None
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match is None:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"is_correct", "normalized_prediction", "reason"}
        or not isinstance(value.get("is_correct"), bool)
        or not isinstance(value.get("normalized_prediction"), str)
        or not isinstance(value.get("reason"), str)
    ):
        return None
    return value


def _responses_content(response_payload: dict[str, object]) -> object:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = response_payload.get("output")
    if not isinstance(output, list):
        return None
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get("content"), list):
            continue
        for block in item["content"]:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(block["text"])
    return "\n".join(texts)


def _chat_content(response_payload: dict[str, object]) -> object:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    return "\n".join(
        block if isinstance(block, str) else block.get("text", "")
        for block in content
        if isinstance(block, (str, dict))
    )


def _normalize_usage(value: object) -> dict[str, object] | None:
    raw = value if isinstance(value, dict) else {}
    input_tokens = raw.get("input_tokens", raw.get("prompt_tokens", 0)) or 0
    output_tokens = raw.get("output_tokens", raw.get("completion_tokens", 0)) or 0
    details = raw.get("input_tokens_details", raw.get("prompt_tokens_details", {}))
    numeric_values = (
        input_tokens,
        output_tokens,
        raw.get("total_tokens", input_tokens + output_tokens) or 0,
    )
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        or item < 0
        for item in numeric_values
    ):
        return None
    result: dict[str, object] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": numeric_values[2],
    }
    if isinstance(details, dict):
        cached = details.get("cached_tokens", 0) or 0
        if (
            isinstance(cached, bool)
            or not isinstance(cached, (int, float))
            or not math.isfinite(cached)
            or cached < 0
            or cached > input_tokens
        ):
            return None
        result["input_tokens_details"] = {"cached_tokens": cached}
    return result


def estimate_judge_cost(
    usage: dict[str, object], config: JudgeConfig
) -> dict[str, float]:
    details = usage.get("input_tokens_details")
    cached_tokens = (
        float(details.get("cached_tokens", 0) or 0)
        if isinstance(details, dict)
        else 0.0
    )
    input_tokens = float(usage["input_tokens"])
    input_cost = (
        max(0.0, input_tokens - cached_tokens) / 1_000_000 * config.input_price_per_1m
    )
    cached_input_cost = cached_tokens / 1_000_000 * config.cached_input_price_per_1m
    output_cost = float(usage["output_tokens"]) / 1_000_000 * config.output_price_per_1m
    return {
        "input_cost": input_cost,
        "cached_input_cost": cached_input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + cached_input_cost + output_cost,
    }
