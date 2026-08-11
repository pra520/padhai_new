"""Multi-provider LLM manager with automatic failover and recovery.

Every AI feature calls `generate(messages, max_tokens)`. Behind that one
function sits a rotation of FREE providers, tried in priority order:

    1. OpenRouter free models            OPENROUTER_API_KEY
    2. Google Gemini (free tier)         GEMINI_API_KEY
    3. Groq free tier                    GROQ_API_KEY
    4. Hugging Face Inference (free)     HF_TOKEN

Each provider carries a health record. A failure (429, timeout, 5xx, bad
payload) puts it into a cooldown that doubles on every consecutive failure
(30 s → 15 min cap); one success clears the record, which is what puts a
recovered provider straight back into the rotation. Nothing is permanent
and no user action is ever needed.

Only providers whose key is configured take part — with no keys at all,
`generate` returns None and callers fall back to local extractive mode.
"""
import logging
import os
import re
import threading
import time

import requests

from config import Config

log = logging.getLogger("padhai.providers")

TIMEOUT = 60
COOLDOWN_BASE = 30          # seconds after the first failure
COOLDOWN_CAP = 15 * 60      # never bench a provider longer than this
RETRY_STATUSES = {500, 502, 503, 504}


class _Health:
    """Failure tracking for one provider (or one model within a provider)."""

    def __init__(self):
        self.failures = 0
        self.benched_until = 0.0
        self.last_error = ""

    def ok_now(self) -> bool:
        return time.time() >= self.benched_until

    def succeed(self):
        if self.failures:
            log.info("Provider recovered after %d failure(s)", self.failures)
        self.failures = 0
        self.benched_until = 0.0
        self.last_error = ""

    def fail(self, reason: str):
        self.failures += 1
        wait = min(COOLDOWN_CAP, COOLDOWN_BASE * (2 ** (self.failures - 1)))
        self.benched_until = time.time() + wait
        self.last_error = reason[:200]
        log.warning("Provider benched %ds after failure #%d: %s",
                    wait, self.failures, reason)


def _strip_reasoning(text: str) -> str:
    """Reasoning models wrap chain-of-thought in <think> tags — remove it."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


class Provider:
    name = "base"

    def __init__(self):
        self.health = _Health()

    def configured(self) -> bool:
        raise NotImplementedError

    def _call(self, messages, max_tokens) -> str | None:
        raise NotImplementedError

    def generate(self, messages, max_tokens) -> str | None:
        try:
            text = self._call(messages, max_tokens)
        except requests.Timeout:
            self.health.fail("timeout")
            return None
        except Exception as exc:
            self.health.fail(str(exc))
            return None
        if text:
            self.health.succeed()
            return text
        self.health.fail("empty response")
        return None


class _OpenAICompatible(Provider):
    """Groq, Hugging Face router and OpenRouter all speak the OpenAI schema."""

    url = ""
    models: list[str] = []

    def _key(self) -> str:
        raise NotImplementedError

    def configured(self) -> bool:
        return bool(self._key())

    def _call(self, messages, max_tokens) -> str | None:
        headers = {"Authorization": f"Bearer {self._key()}",
                   "Content-Type": "application/json"}
        last_reason = "no models"
        for model in self.models:
            resp = requests.post(
                self.url, headers=headers, timeout=TIMEOUT,
                json={"model": model, "messages": messages,
                      "max_tokens": max_tokens, "temperature": 0.3},
            )
            if resp.status_code == 429 or resp.status_code in RETRY_STATUSES:
                last_reason = f"{model}: HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            text = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""
            text = _strip_reasoning(text)
            if text:
                return text
            last_reason = f"{model}: empty"
        raise RuntimeError(last_reason)


class Gemini(Provider):
    """Google AI Studio free tier — generous limits, fast, good quality.

    The "-latest" aliases are used deliberately: Google retires dated model
    ids (gemini-1.5-flash, gemini-2.5-flash) and a hard-coded id silently
    becomes a 404. The aliases always resolve to a current model.
    Overridable with GEMINI_MODELS in .env.
    """
    name = "gemini"
    MODELS = [m.strip() for m in os.getenv(
        "GEMINI_MODELS",
        "gemini-flash-latest,gemini-flash-lite-latest,gemini-2.0-flash"
    ).split(",") if m.strip()]

    def configured(self) -> bool:
        return bool(Config.GEMINI_API_KEY)

    def _call(self, messages, max_tokens) -> str | None:
        # Gemini separates the system prompt from the turn contents.
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in messages if m["role"] != "system"
        ]
        body = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        last_reason = "no models"
        for model in self.MODELS:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={Config.GEMINI_API_KEY}",
                json=body, timeout=TIMEOUT,
            )
            if resp.status_code == 429 or resp.status_code in RETRY_STATUSES:
                last_reason = f"{model}: HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            cands = resp.json().get("candidates") or []
            first = cands[0] if cands else {}
            parts = (first.get("content", {}) or {}).get("parts") or []
            # Gemini flags internal reasoning with thought=true. It is normally
            # withheld, but must never be concatenated into the answer if sent.
            text = _strip_reasoning(
                "".join(p.get("text", "") for p in parts if not p.get("thought"))
            )
            if text:
                return text
            # Newer Gemini models spend tokens on internal reasoning and can
            # return no text at all when the budget runs out. That is this
            # request's problem, not the provider's — move to the next model
            # rather than benching a perfectly healthy provider.
            reason = first.get("finishReason") or "empty"
            last_reason = f"{model}: {reason}"
        raise RuntimeError(last_reason)


class OpenRouter(_OpenAICompatible):
    name = "openrouter"
    url = "https://openrouter.ai/api/v1/chat/completions"

    @property
    def models(self):
        return Config.OPENROUTER_MODELS

    def _key(self):
        return Config.OPENROUTER_API_KEY


class Groq(_OpenAICompatible):
    name = "groq"
    url = "https://api.groq.com/openai/v1/chat/completions"
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    def _key(self):
        return Config.GROQ_API_KEY


class HuggingFace(_OpenAICompatible):
    name = "huggingface"
    url = "https://router.huggingface.co/v1/chat/completions"
    models = ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"]

    def _key(self):
        return Config.HF_TOKEN


# Priority order. OpenRouter first: its free roster is the widest, so it is
# the least likely to be the provider that runs out. Gemini backs it up.
_PROVIDERS: list[Provider] = [OpenRouter(), Gemini(), Groq(), HuggingFace()]
_lock = threading.Lock()


def available() -> bool:
    """Is any provider configured at all?"""
    return any(p.configured() for p in _PROVIDERS)


def ready() -> bool:
    """Could a real model answer *right now*?

    Different from `available()`: a provider can be configured but benched
    after failures. Callers use this to decide whether a cached offline
    result is still the best they can do, or whether it is worth regenerating.
    """
    return any(p.configured() and p.health.ok_now() for p in _PROVIDERS)


def generate(messages: list[dict], max_tokens: int = 1500) -> str | None:
    """One LLM call, routed to the healthiest configured provider.

    Tries every configured provider that is not on cooldown, in priority
    order; benched providers are only used as a last resort (their cooldown
    may have been for a single model). Returns None only when everything
    configured has failed — the caller then uses local extractive mode.
    """
    with _lock:
        ready = [p for p in _PROVIDERS if p.configured() and p.health.ok_now()]
        benched = [p for p in _PROVIDERS if p.configured() and not p.health.ok_now()]

    for p in ready + benched:
        text = p.generate(messages, max_tokens)
        if text:
            return text
    return None


def status() -> list[dict]:
    """Health readout for /api/status and the settings panel."""
    out = []
    for p in _PROVIDERS:
        if not p.configured():
            out.append({"name": p.name, "state": "not configured"})
        elif p.health.ok_now():
            out.append({"name": p.name, "state": "ready"})
        else:
            out.append({
                "name": p.name, "state": "cooling down",
                "retry_in": max(0, round(p.health.benched_until - time.time())),
                "last_error": p.health.last_error,
            })
    return out
