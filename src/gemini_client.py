"""
gemini_client.py — explicit Gemini + Groq methods with fallback.
"""

import os
import time
import random
import requests

# Primary model (GitHub secret override: GEMINI_MODEL)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Fallback model (GitHub secret override: FALLBACK_MODEL)
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "llama-3.3-70b-versatile")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

_GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SWAP_ON_GEMINI_429 = os.environ.get("SWAP_ON_GEMINI_429", "true").lower() == "true"

# Provider-specific retry config
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", os.environ.get("LLM_MAX_RETRIES", "4")))
GROQ_MAX_RETRIES = int(os.environ.get("GROQ_MAX_RETRIES", os.environ.get("LLM_MAX_RETRIES", "6")))
GEMINI_BACKOFF_BASE_SECONDS = float(
    os.environ.get("GEMINI_BACKOFF_BASE_SECONDS", os.environ.get("LLM_BACKOFF_BASE_SECONDS", "2"))
)
GROQ_BACKOFF_BASE_SECONDS = float(
    os.environ.get("GROQ_BACKOFF_BASE_SECONDS", os.environ.get("LLM_BACKOFF_BASE_SECONDS", "2"))
)
MAX_BACKOFF_SECONDS = float(os.environ.get("LLM_MAX_BACKOFF_SECONDS", "90"))


class RateLimitError(RuntimeError):
    """Raised when a provider returns repeated 429 responses."""


def _merge_system_prompt(system: str, prompt: str) -> str:
    s = (system or "").strip()
    if not s:
        return prompt
    return f"{s}\n\n---\n\n{prompt}"


def _parse_seconds(raw: str | None) -> float | None:
    """Parse seconds from headers like '12', '1.5', '2m30s', '45s'."""
    if not raw:
        return None
    v = raw.strip().lower()
    try:
        return float(v)
    except Exception:
        pass
    # Parse compact durations (e.g. 2m30s)
    total = 0.0
    num = ""
    saw_unit = False
    for ch in v:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in ("h", "m", "s") and num:
            n = float(num)
            if ch == "h":
                total += n * 3600
            elif ch == "m":
                total += n * 60
            else:
                total += n
            num = ""
            saw_unit = True
        else:
            # Unknown format char
            return None
    if num and saw_unit:
        # trailing number without unit after already parsed units -> invalid
        return None
    return total if saw_unit else None


def _retry_after_seconds(resp: requests.Response) -> float | None:
    # Standard header first
    ra = _parse_seconds(resp.headers.get("Retry-After"))
    if ra is not None and ra > 0:
        return ra
    # Groq commonly provides reset windows in these headers
    for key in (
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
    ):
        val = _parse_seconds(resp.headers.get(key))
        if val is not None and val > 0:
            return val
    return None


def _wait_before_retry(
    provider: str,
    attempt: int,
    retry_after: float | None,
    max_retries: int,
    base_backoff_seconds: float,
) -> None:
    if retry_after is not None and retry_after > 0:
        wait_s = retry_after
    else:
        # Exponential backoff + jitter to avoid synchronized retries
        wait_s = base_backoff_seconds * (2 ** max(0, attempt - 1))
        wait_s += random.uniform(0, 0.75)
    wait_s = min(wait_s, MAX_BACKOFF_SECONDS)
    print(f"  [{provider}] rate limited (429). waiting {wait_s:.1f}s before retry {attempt}/{max_retries}...")
    time.sleep(wait_s)


def gemini_generate(
    system: str,
    prompt: str,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> str:
    """
    Direct REST call to Gemini v1.
    Uses only fields that v1 accepts (no systemInstruction key).
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    merged_prompt = _merge_system_prompt(system, prompt)
    url = _GEMINI_URL_TMPL.format(model=MODEL)
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        response = requests.post(
            url,
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [
                    {"parts": [{"text": merged_prompt}]}
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=90,
        )

        if response.status_code == 429:
            if SWAP_ON_GEMINI_429:
                # Swap provider immediately instead of spending retries on Gemini.
                raise RateLimitError("Gemini returned 429; immediate fallback requested")
            _wait_before_retry(
                "gemini",
                attempt,
                _retry_after_seconds(response),
                GEMINI_MAX_RETRIES,
                GEMINI_BACKOFF_BASE_SECONDS,
            )
            continue

        response.raise_for_status()
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as exc:
            raise RuntimeError(f"Gemini returned unexpected payload: {data}") from exc

    raise RateLimitError("Gemini retries exhausted due to repeated 429 responses")


def groq_generate(
    system: str,
    prompt: str,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> str:
    """OpenAI-compatible call to Groq."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")

    for attempt in range(1, GROQ_MAX_RETRIES + 1):
        response = requests.post(
            _GROQ_URL,
            json={
                "model": FALLBACK_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            timeout=90,
        )

        if response.status_code == 429:
            _wait_before_retry(
                "groq",
                attempt,
                _retry_after_seconds(response),
                GROQ_MAX_RETRIES,
                GROQ_BACKOFF_BASE_SECONDS,
            )
            continue

        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    raise RateLimitError("Groq retries exhausted due to repeated 429 responses")


def generate_content(
    system: str,
    prompt: str,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> str:
    """
    Primary path: Gemini.
    Fallback path: Groq (if Gemini fails for any reason and GROQ_API_KEY exists).
    """
    try:
        return gemini_generate(system, prompt, temperature=temperature, max_tokens=max_tokens)
    except RateLimitError as gemini_error:
        if GROQ_API_KEY:
            print(f"  [gemini] rate-limited, switching to Groq fallback: {gemini_error}")
            return groq_generate(system, prompt, temperature=temperature, max_tokens=max_tokens)
        raise
    except Exception as gemini_error:
        # Non-rate-limit Gemini failures can still use Groq as a safety fallback.
        if GROQ_API_KEY:
            print(f"  [gemini] failed, switching to Groq fallback: {gemini_error}")
            return groq_generate(system, prompt, temperature=temperature, max_tokens=max_tokens)
        raise
