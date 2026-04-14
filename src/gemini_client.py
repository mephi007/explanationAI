"""
gemini_client.py — Shared LLM client with automatic Groq fallback.

Primary:  Google Gemini  (AI Studio free tier — 1,500 req/day)
Fallback: Groq API       (free tier, no card — Llama 3.3 70B, 1,000 req/day)

Fallback triggers automatically on quota / rate-limit errors (HTTP 429).
Set GROQ_API_KEY as a GitHub secret to enable it.

Model benchmark comparison (MMLU / HumanEval):
  gemini-1.5-flash        — 78.9 / 74.4  (primary, free via AI Studio)
  llama-3.3-70b-versatile — 86.0 / 88.4  (Groq free, actually stronger)
  llama-3.1-8b-instant    — 73.0 / 72.6  (Groq free, high quota: 14,400/day)
  qwen/qwen3-32b          — 85.7 / 86.0  (Groq free, 60 RPM)
"""

import os
import requests
from google import genai
from google.genai import types  # re-exported for convenience

# ── Primary model (override via GEMINI_MODEL secret) ─────────────────────────
MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# ── Fallback model (override via FALLBACK_MODEL secret) ───────────────────────
# Options: llama-3.3-70b-versatile | llama-3.1-8b-instant | qwen/qwen3-32b
FALLBACK_MODEL   = os.environ.get("FALLBACK_MODEL", "llama-3.3-70b-versatile")
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY", "")
_GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1"},
        )
    return _client


def generate_content(
    system: str,
    prompt: str,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> str:
    """
    Generate text — Gemini first, Groq on quota/rate-limit errors.
    All generators should call this instead of get_client() directly.
    """
    try:
        contents = _merge_system_user(system, prompt)
        resp = get_client().models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return resp.text.strip()

    except Exception as e:
        err = str(e).lower()
        is_quota = "429" in str(e) or "quota" in err or "resource_exhausted" in err or "rate" in err
        if GROQ_API_KEY and is_quota:
            print(f"  [gemini] quota hit — falling back to Groq ({FALLBACK_MODEL})")
            return _groq_generate(system, prompt, temperature, max_tokens)
        raise


def _groq_generate(system: str, prompt: str, temperature: float, max_tokens: int) -> str:
    """OpenAI-compatible call to Groq's free inference API."""
    resp = requests.post(
        _GROQ_URL,
        json={
            "model": FALLBACK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
