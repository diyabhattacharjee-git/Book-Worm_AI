"""Optional LLM provider layer: Groq -> Hugging Face -> Ollama -> none.

* Only providers the user configured are tried; nothing paid is ever added
  automatically. Hugging Face uses Inference Providers (HF_PROVIDER, default
  "auto"), which a free account can only use within its monthly free credits.
* A rate limit pauses that provider for as long as it asks (Retry-After), transient
  errors are retried once, and requests the provider rejected don't pause it at all.
  If no provider can answer, LLMUnavailable tells the caller when to try again.
* LLM output is treated as untrusted: callers validate it before use.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.http import cache_get, cache_put

logger = logging.getLogger("bookworm.llm")

COOLDOWN_SECONDS = 30
RATE_LIMIT_COOLDOWN_SECONDS = 60
# Errors that won't fix themselves quickly (bad key, no credits): skip the provider for an hour.
LONG_COOLDOWN_SECONDS = 3600
PERSISTENT_STATUSES = (401, 402, 403)
BAD_REQUEST_STATUSES = (400, 404, 413, 422)
# Reasoning models spend completion tokens thinking before they answer.
REASONING_HEADROOM = 512
TRANSIENT_RETRY_DELAY_SECONDS = 0.5
# Per-minute token limits clear within seconds, so a short wait beats failing the reader's message.
SHORT_RATE_LIMIT_WAIT_SECONDS = 8
RESPONSE_CACHE_TTL = timedelta(hours=6)


def _is_reasoning(model: str) -> bool:
    return "gpt-oss" in model.lower()


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


class LLMUnavailable(Exception):
    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_cooldown: dict[str, float] = {}
_last_error: dict[str, str] = {}
_lock = threading.Lock()


def _configured() -> list[str]:
    s = get_settings()
    order = [p.strip() for p in s.llm_provider_order.split(",") if p.strip()]
    available = {
        "groq": bool(s.groq_api_key and s.groq_model),
        "huggingface": bool(s.hf_token and s.hf_model),
        "ollama": bool(s.ollama_base_url and s.ollama_model),
    }
    return [p for p in order if available.get(p)]


def status() -> dict:
    s = get_settings()
    now = time.time()
    providers = {}
    for name, model, configured in (
        ("groq", s.groq_model, bool(s.groq_api_key)),
        ("huggingface", s.hf_model, bool(s.hf_token and s.hf_model)),
        ("ollama", s.ollama_model, bool(s.ollama_base_url and s.ollama_model)),
    ):
        providers[name] = {
            "configured": configured,
            "model": model if configured else None,
            "cooling_down": _cooldown.get(name, 0) > now,
            "last_error": _last_error.get(name),
        }
    active = [p for p in _configured() if _cooldown.get(p, 0) <= now]
    return {"providers": providers, "active_order": active, "mode": f"llm:{active[0]}" if active else "deterministic"}


def is_available() -> bool:
    now = time.time()
    return any(_cooldown.get(p, 0) <= now for p in _configured())


def _http_details(exc: Exception) -> tuple[int | None, int | None]:
    """(status code, Retry-After seconds) from an SDK or httpx exception."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    raw = response.headers.get("retry-after") if response is not None else None
    try:
        retry_after = max(1, int(float(raw))) if raw else None
    except ValueError:
        retry_after = None
    return status, retry_after


def _mark_failure(provider: str, exc: Exception) -> None:
    """Pause a provider only when calling it again soon would be wasted."""
    status, retry_after = _http_details(exc)
    message = f"{type(exc).__name__}: {exc}"
    if status in BAD_REQUEST_STATUSES:  # this request was the problem, not the provider
        wait = 0
    elif status in PERSISTENT_STATUSES or any(k in message for k in ("Invalid API Key", "no remaining credits")):
        wait = LONG_COOLDOWN_SECONDS
    elif status == 429:
        wait = min(retry_after or RATE_LIMIT_COOLDOWN_SECONDS, LONG_COOLDOWN_SECONDS)
    else:
        wait = COOLDOWN_SECONDS
    with _lock:
        if wait:
            _cooldown[provider] = time.time() + wait
        _last_error[provider] = message[:200]
    logger.warning("llm provider failed", extra={"data": {"provider": provider, "status": status, "cooldown": wait}})


def retry_after_seconds() -> int:
    """How long until the soonest configured provider can be tried again (0 = now)."""
    now = time.time()
    waits = [_cooldown.get(p, 0) - now for p in _configured()]
    return max(0, int(min(waits, default=0)) + 1) if waits and min(waits) > 0 else 0


def is_configured() -> bool:
    return bool(_configured())


def reset_state() -> None:
    with _lock:
        _cooldown.clear()
        _last_error.clear()


def _call_groq(messages: list[dict], json_mode: bool, max_tokens: int, temperature: float) -> LLMResult:
    from groq import Groq

    s = get_settings()
    client = Groq(api_key=s.groq_api_key, timeout=s.llm_timeout_seconds, max_retries=0)
    kwargs: dict = {"model": s.groq_model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if _is_reasoning(s.groq_model):
        kwargs.update(max_tokens=max_tokens + REASONING_HEADROOM, reasoning_effort="low", include_reasoning=False)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return LLMResult(resp.choices[0].message.content or "", "groq", s.groq_model)


def _call_hf(messages: list[dict], json_mode: bool, max_tokens: int, temperature: float) -> LLMResult:
    from huggingface_hub import InferenceClient

    s = get_settings()
    client = InferenceClient(provider=s.hf_provider, model=s.hf_model, token=s.hf_token, timeout=s.llm_timeout_seconds)
    kwargs: dict = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if _is_reasoning(s.hf_model):
        kwargs.update(max_tokens=max_tokens + REASONING_HEADROOM, extra_body={"reasoning_effort": "low"})
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat_completion(**kwargs)
    except Exception as exc:
        if not json_mode or _http_details(exc)[0] in PERSISTENT_STATUSES + (429,):
            raise
        kwargs.pop("response_format")  # not every hosted model supports JSON mode
        resp = client.chat_completion(**kwargs)
    return LLMResult(resp.choices[0].message.content or "", "huggingface", s.hf_model)


def _call_ollama(messages: list[dict], json_mode: bool, max_tokens: int, temperature: float) -> LLMResult:
    s = get_settings()
    payload: dict = {"model": s.ollama_model, "messages": messages, "stream": False,
                     "options": {"temperature": temperature, "num_predict": max_tokens}}
    if json_mode:
        payload["format"] = "json"
    resp = httpx.post(f"{s.ollama_base_url.rstrip('/')}/api/chat", json=payload, timeout=s.llm_timeout_seconds)
    resp.raise_for_status()
    return LLMResult(resp.json().get("message", {}).get("content", ""), "ollama", s.ollama_model)


def _is_transient(exc: Exception) -> bool:
    status, _ = _http_details(exc)
    return status is None or status >= 500


def _cache_key(messages: list[dict], json_mode: bool, max_tokens: int) -> str:
    raw = json.dumps([messages, json_mode, max_tokens, get_settings().groq_model], sort_keys=True)
    return f"llm:{hashlib.sha256(raw.encode()).hexdigest()}"


def complete(system: str, user: str, *, json_mode: bool = False, max_tokens: int = 500, history: list[dict] | None = None,
             temperature: float = 0.1, cache_db: Session | None = None) -> LLMResult:
    """Run the first working configured provider. Raises LLMUnavailable.

    `history` is the recent conversation, oldest first. With `cache_db`, an identical
    request is answered from the cache without spending any of the provider's quota."""
    messages = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": user}]
    key = _cache_key(messages, json_mode, max_tokens) if cache_db is not None else None
    if key:
        cached = cache_get(cache_db, key)
        if isinstance(cached, dict) and cached.get("text"):
            return LLMResult(cached["text"], cached["provider"], cached["model"])
    now = time.time()
    tried = []
    for provider in _configured():
        if _cooldown.get(provider, 0) > now:
            continue
        tried.append(provider)
        for attempt in range(2):
            try:
                result = _CALLERS[provider](messages, json_mode, max_tokens, temperature)
            except Exception as exc:  # any provider failure -> maybe retry once, then the next provider
                status, retry_after = _http_details(exc)
                if attempt == 0 and status == 429 and retry_after and retry_after <= SHORT_RATE_LIMIT_WAIT_SECONDS:
                    time.sleep(retry_after)
                    continue
                if attempt == 0 and _is_transient(exc):
                    time.sleep(TRANSIENT_RETRY_DELAY_SECONDS)
                    continue
                _mark_failure(provider, exc)
                break
            if not result.text.strip():  # the model ran out of tokens; not a reason to distrust the provider
                logger.warning("llm returned no text", extra={"data": {"provider": provider}})
                break
            with _lock:
                _last_error.pop(provider, None)
            if key:
                cache_put(cache_db, key, "llm", {"text": result.text, "provider": result.provider, "model": result.model}, RESPONSE_CACHE_TTL)
            return result
    raise LLMUnavailable("no LLM provider available" + (f" (tried {', '.join(tried)})" if tried else ""),
                         retry_after=retry_after_seconds() or None)


_CALLERS = {"groq": _call_groq, "huggingface": _call_hf, "ollama": _call_ollama}


def parse_json_object(text: str) -> dict:
    """The JSON object in a model reply, tolerating code fences. Raises LLMUnavailable."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMUnavailable("model did not return JSON")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("model returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise LLMUnavailable("model returned non-object JSON")
    return data


def complete_json(system: str, user: str, *, max_tokens: int = 400) -> tuple[dict, LLMResult]:
    result = complete(system, user, json_mode=True, max_tokens=max_tokens)
    return parse_json_object(result.text), result
