"""LLM providers for the AI service.

Order of preference:

1. ``OPENAI_API_KEY``     -> api.openai.com/v1/chat/completions
2. ``GEMINI_API_KEY``     -> generativelanguage.googleapis.com
3. OpenRouter (``OPENROUTER_API_KEY``)
4. Pollinations.ai        -> free, key-less, no signup (default)
5. Offline extractive fallback (implemented in the service)

Every provider returns a plain string. The service decides what to do when
*all* providers fail: for summarisation it degrades to the extractive
fallback so the user still gets a real file.
"""
from __future__ import annotations

import os
from typing import List, Tuple
from urllib.parse import quote

from services._http import HttpError, get_text, post_json

SYSTEM_PROMPT = (
    "You are a precise research assistant writing for a busy student. "
    "Use ONLY the supplied source material; never invent facts. "
    "Be concrete and factual. Output GitHub-flavoured Markdown with a short "
    "intro paragraph followed by a bullet list of the key points."
)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent?key={key}")
POLLINATIONS_TEXT = "https://text.pollinations.ai/{prompt}"


class ProviderError(RuntimeError):
    """Raised when a provider is unavailable or returns nothing usable."""


def build_prompt(topic: str, length: str, sources: List[dict]) -> str:
    """Compose the user prompt (topic + numbered source extracts)."""
    words = {"brief": "120-160", "medium": "200-300", "detailed": "350-500"}.get(
        length, "150-250"
    )
    blocks = []
    for i, src in enumerate(sources):
        body = src.get("text") or src.get("extract") or ""
        if body:
            blocks.append(f"SOURCE {i + 1} ({src.get('title') or 'untitled'}):\n{body}")
    return (
        f"Write a {length} summary ({words} words) of: {topic}\n\n"
        + ("\n\n".join(blocks) or "No external sources available.")
        + "\n\nInclude: one overview paragraph, 4-7 bullet key points, then a short "
        "'Why it matters' line. Cite sources as [S1], [S2] where relevant."
    )


def first_sentences(text: str, n: int = 3) -> str:
    """Take the first n sentences of a block of text."""
    import re
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return " ".join(parts[:n]).strip()


class OpenAICompatibleProvider:
    """Chat-completions provider (OpenAI, OpenRouter, or a compatible host)."""

    def __init__(self, api_key: str, url: str = OPENAI_URL, model: str = "gpt-4o-mini",
                 label: str = "openai"):
        self.api_key = api_key
        self.url = url
        self.model = model
        self.name = label

    def complete(self, prompt: str, timeout: float = 90.0) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        try:
            data = post_json(self.url, payload, timeout=timeout,
                             headers={"Authorization": f"Bearer {self.api_key}"})
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected response shape from {self.name}") from exc
        if not (text or "").strip():
            raise ProviderError(f"{self.name} returned an empty completion")
        return text.strip()


class GeminiProvider:
    """Google Gemini generateContent provider."""

    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str, timeout: float = 90.0) -> str:
        url = GEMINI_URL.format(model=self.model, key=self.api_key)
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        }
        try:
            data = post_json(url, payload, timeout=timeout)
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("unexpected response shape from gemini") from exc
        if not text.strip():
            raise ProviderError("gemini returned an empty completion")
        return text.strip()


class PollinationsProvider:
    """Free, key-less text generation endpoint (no signup required)."""

    name = "pollinations"

    def __init__(self, model: str = "openai"):
        self.model = model

    def complete(self, prompt: str, timeout: float = 90.0) -> str:
        url = POLLINATIONS_TEXT.format(prompt=quote(f"{SYSTEM_PROMPT}\n\n{prompt}"[:6000]))
        try:
            text = get_text(url, timeout=timeout)
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        text = (text or "").strip()
        if len(text) < 20:
            raise ProviderError("pollinations returned too little text")
        return text


def build_providers(env=None) -> List[Tuple[str, object]]:
    """Return the ordered provider chain available in this environment."""
    env = env if env is not None else os.environ
    chain: List[Tuple[str, object]] = []
    if env.get("OPENAI_API_KEY"):
        chain.append(("openai", OpenAICompatibleProvider(
            env["OPENAI_API_KEY"], model=env.get("OPENAI_MODEL", "gpt-4o-mini"))))
    key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    if key:
        chain.append(("gemini", GeminiProvider(key)))
    if env.get("OPENROUTER_API_KEY"):
        chain.append(("openrouter", OpenAICompatibleProvider(
            env["OPENROUTER_API_KEY"], OPENROUTER_URL,
            env.get("OPENROUTER_MODEL", "openrouter/auto"), label="openrouter")))
    if str(env.get("INTENTOS_NO_FREE_LLM", "")).lower() not in ("1", "true", "yes"):
        chain.append(("pollinations", PollinationsProvider(
            env.get("POLLINATIONS_MODEL", "openai"))))
    return chain
