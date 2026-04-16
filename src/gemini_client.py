"""
gemini_client.py — Single shared Gemini client for the whole project.

The google.genai SDK defaults to the v1beta endpoint, where gemini-2.0-flash
is not available. Pinning to v1 fixes the 404 NOT_FOUND error.
"""

import os
from google import genai
from google.genai import types  # re-exported for convenience

# Override via GEMINI_MODEL env var (GitHub secret or workflow env)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

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
