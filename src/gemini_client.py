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

MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "6"))
BASE_BACKOFF_SECONDS = float(os.environ.get("LLM_BACKOFF_BASE_SECONDS", "2"))


def _merge_system_prompt(system: str, prompt: str) -> str:
    s = (system or "").strip()
    if not s:
        return prompt
    return f"{s}\n\n---\n\n{prompt}"


def _retry_after_seconds(resp: requests.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _wait_before_retry(provider: str, attempt: int, retry_after: float | None) -> None:
    if retry_after is not None and retry_after > 0:
        wait_s = retry_after
    else:
        # Exponential backoff + jitter to avoid synchronized retries
        wait_s = BASE_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))
        wait_s += random.uniform(0, 0.75)
    print(f"  [{provider}] rate limited (429). waiting {wait_s:.1f}s before retry {attempt}/{MAX_RETRIES}...")
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
    for attempt in range(1, MAX_RETRIES + 1):
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
            _wait_before_retry("gemini", attempt, _retry_after_seconds(response))
            continue

        response.raise_for_status()
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as exc:
            raise RuntimeError(f"Gemini returned unexpected payload: {data}") from exc

    raise RuntimeError("Gemini retries exhausted due to repeated 429 responses")


def groq_generate(
    system: str,
    prompt: str,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> str:
    """OpenAI-compatible call to Groq."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")

    for attempt in range(1, MAX_RETRIES + 1):
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
            _wait_before_retry("groq", attempt, _retry_after_seconds(response))
            continue

        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    raise RuntimeError("Groq retries exhausted due to repeated 429 responses")


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
    except Exception as gemini_error:
        if GROQ_API_KEY:
            print(f"  [gemini] failed, switching to Groq fallback: {gemini_error}")
            return groq_generate(system, prompt, temperature=temperature, max_tokens=max_tokens)
        raise
