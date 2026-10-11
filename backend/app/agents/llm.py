"""Optional LLM provider layer: Groq -> Hugging Face -> Ollama -> none.

* Only providers the user configured are tried; nothing paid is ever added
  automatically. Hugging Face uses Inference Providers (HF_PROVIDER, default
  "auto"), which a free account can only use within its monthly free credits.
* Failures (timeouts, rate limits, quota exhaustion) put that provider on a short
  cooldown and the next configured one is tried. If none work, callers fall back
  to deterministic logic and report `mode="deterministic"`.
* LLM output is treated as untrusted: callers validate it before use.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger("bookworm.llm")

COOLDOWN_SECONDS = 90
# Errors that won't fix themselves quickly (bad key, no credits): skip the provider for an hour.
LONG_COOLDOWN_SECONDS = 3600
_PERSISTENT = ("401", "402", "403", "Invalid API Key", "no remaining credits", "AuthenticationError", "PermissionDenied")
# Reasoning models spend completion tokens thinking before they answer.
REASONING_HEADROOM = 512


def _is_reasoning(model: str) -> bool:
    return "gpt-oss" in model.lower()


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


class LLMUnavailable(Exception):
    pass


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


def _mark_failure(provider: str, message: str) -> None:
    with _lock:
        wait = LONG_COOLDOWN_SECONDS if any(k in message for k in _PERSISTENT) else COOLDOWN_SECONDS
        _cooldown[provider] = time.time() + wait
        _last_error[provider] = message[:200]
    logger.warning("llm provider failed", extra={"data": {"provider": provider, "error": message[:200]}})


def _call_groq(messages: list[dict], json_mode: bool, max_tokens: int) -> LLMResult:
    from groq import Groq

    s = get_settings()
    client = Groq(api_key=s.groq_api_key, timeout=s.llm_timeout_seconds, max_retries=0)
    kwargs: dict = {"model": s.groq_model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
    if _is_reasoning(s.groq_model):
        kwargs.update(max_tokens=max_tokens + REASONING_HEADROOM, reasoning_effort="low", include_reasoning=False)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return LLMResult(resp.choices[0].message.content or "", "groq", s.groq_model)


def _call_hf(messages: list[dict], json_mode: bool, max_tokens: int) -> LLMResult:
    from huggingface_hub import InferenceClient

    s = get_settings()
    client = InferenceClient(provider=s.hf_provider, model=s.hf_model, token=s.hf_token, timeout=s.llm_timeout_seconds)
    kwargs: dict = {"messages": messages, "max_tokens": max_tokens, "temperature": 0.1}
    if _is_reasoning(s.hf_model):
        kwargs.update(max_tokens=max_tokens + REASONING_HEADROOM, extra_body={"reasoning_effort": "low"})
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat_completion(**kwargs)
    except Exception as exc:
        if not json_mode or any(k in str(exc) for k in _PERSISTENT):
            raise
        kwargs.pop("response_format")  # not every hosted model supports JSON mode
        resp = client.chat_completion(**kwargs)
    return LLMResult(resp.choices[0].message.content or "", "huggingface", s.hf_model)


def _call_ollama(messages: list[dict], json_mode: bool, max_tokens: int) -> LLMResult:
    s = get_settings()
    payload: dict = {"model": s.ollama_model, "messages": messages, "stream": False,
                     "options": {"temperature": 0.1, "num_predict": max_tokens}}
    if json_mode:
        payload["format"] = "json"
    resp = httpx.post(f"{s.ollama_base_url.rstrip('/')}/api/chat", json=payload, timeout=s.llm_timeout_seconds)
    resp.raise_for_status()
    return LLMResult(resp.json().get("message", {}).get("content", ""), "ollama", s.ollama_model)


_CALLERS = {"groq": _call_groq, "huggingface": _call_hf, "ollama": _call_ollama}


def complete(system: str, user: str, *, json_mode: bool = False, max_tokens: int = 500,
             history: list[dict] | None = None) -> LLMResult:
    """Run the first working configured provider. Raises LLMUnavailable."""
    messages = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": user}]
    now = time.time()
    tried = []
    for provider in _configured():
        if _cooldown.get(provider, 0) > now:
            continue
        tried.append(provider)
        try:
            result = _CALLERS[provider](messages, json_mode, max_tokens)
            if result.text.strip():
                with _lock:
                    _last_error.pop(provider, None)
                return result
            _mark_failure(provider, "empty response")
        except Exception as exc:  # any provider failure -> try the next one
            _mark_failure(provider, f"{type(exc).__name__}: {exc}")
    raise LLMUnavailable("no LLM provider available" + (f" (tried {', '.join(tried)})" if tried else ""))


def complete_json(system: str, user: str, *, max_tokens: int = 400) -> tuple[dict, LLMResult]:
    result = complete(system, user, json_mode=True, max_tokens=max_tokens)
    text = result.text.strip()
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
    return data, result
