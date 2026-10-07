"""AI service: real text generation, summarisation and document composition.

Providers are tried in order and the first one that returns wins:

    1. ``pollinations``  -- free, key-less hosted LLM (OpenAI-compatible)
    2. ``openai``        -- used when OPENAI_API_KEY is set
    3. ``gemini``        -- used when GEMINI_API_KEY is set
    4. ``extractive``    -- offline fallback (TextRank-style sentences)

The offline fallback matters for an *operating-system* layer: an intent must
still produce a usable artefact when the network is unavailable, exactly the
way a filesystem still works when the network is down. The result reports
which provider was used so the UI can show it.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Tuple

from intent_kernel.ipc.service_bus import ServiceError
from services._http import HttpError, get_text, post_json
from services.base_service import BaseService

POLLINATIONS_TEXT = "https://text.pollinations.ai/{prompt}"
POLLINATIONS_OPENAI = "https://text.pollinations.ai/openai"
OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
GEMINI_CHAT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key={key}"
)

_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "is", "are", "was", "were", "be", "been", "being", "of",
    "to", "in", "on", "for", "with", "as", "by", "at", "from", "it", "its",
    "into", "about", "which", "who", "whom", "whose", "what", "when", "where",
    "why", "how", "can", "could", "should", "would", "may", "might", "must",
    "will", "shall", "not", "no", "nor", "so", "such", "also", "more", "most",
    "other", "some", "any", "all", "each", "both", "has", "have", "had", "do",
    "does", "did", "they", "them", "their", "there", "here", "he", "she", "his",
    "her", "you", "your", "we", "our", "us", "i", "one", "two", "very", "over",
    "under", "between", "through", "during", "before", "after", "while", "up",
    "out", "only", "own", "same", "too", "just", "because", "however",
}


class AIService(BaseService):
    """Generative capabilities: summaries, research briefs and documents."""

    name = "ai"
    description = "Text generation: summaries and composed documents (LLM or offline)"

    def __init__(self, provider: str = None, model: str = None, timeout: float = 120.0,
                 offline_only: bool = False, **kw):
        super().__init__(**kw)
        self.timeout = timeout
        self.offline_only = offline_only
        self.model = model or os.environ.get("INTENTOS_MODEL", "openai")
        self.provider_pref = provider or os.environ.get("INTENTOS_AI_PROVIDER", "auto")
        self.last_provider = "none"

    # ------------------------------------------------------------------
    # Provider plumbing
    # ------------------------------------------------------------------
    def _available(self) -> List[str]:
        chain = []
        if self.provider_pref != "extractive":
            chain.append("pollinations")
            if os.environ.get("OPENAI_API_KEY"):
                chain.append("openai")
            if os.environ.get("GEMINI_API_KEY"):
                chain.append("gemini")
        chain.append("extractive")
        if self.provider_pref in ("pollinations", "openai", "gemini"):
            chain = [p for p in chain if p == self.provider_pref or p == "extractive"]
        return chain

    def _generate(self, system: str, prompt: str, max_tokens: int = 900) -> Tuple[str, str]:
        """Return (text, provider). Raises ServiceError when nothing works."""
        self._last_errors = []
        if self.offline_only:
            self.last_provider = "extractive"
            return "", "extractive"
        errors = []
        self._last_errors = errors
        for provider in self._available():
            if provider == "extractive":
                continue
            try:
                if provider == "pollinations":
                    text = self._pollinations(system, prompt, max_tokens)
                elif provider == "openai":
                    text = self._openai(system, prompt, max_tokens)
                else:
                    text = self._gemini(system, prompt, max_tokens)
                if text and text.strip():
                    self.last_provider = provider
                    return text.strip(), provider
                errors.append(f"{provider}: empty response")
            except (HttpError, ServiceError) as exc:
                errors.append(f"{provider}: {exc}")
        self.last_provider = "extractive"
        return "", "extractive"

    # ------------------------------------------------------------------
    # Provider adapters
    # ------------------------------------------------------------------
    def _pollinations(self, system: str, prompt: str, max_tokens: int) -> str:
        """Free key-less hosted LLM, using its OpenAI-compatible endpoint."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        data = post_json(POLLINATIONS_OPENAI, payload, timeout=self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ServiceError(f"unexpected provider response: {exc}") from exc

    def _openai(self, system: str, prompt: str, max_tokens: int) -> str:
        key = os.environ["OPENAI_API_KEY"]
        payload = {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        data = post_json(
            OPENAI_CHAT, payload, timeout=self.timeout,
            headers={"Authorization": f"Bearer {key}"},
        )
        return data["choices"][0]["message"]["content"]

    def _gemini(self, system: str, prompt: str, max_tokens: int) -> str:
        key = os.environ["GEMINI_API_KEY"]
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        data = post_json(GEMINI_CHAT.format(key=key), payload, timeout=self.timeout)
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # ------------------------------------------------------------------
    # Offline extractive fallback
    # ------------------------------------------------------------------
    def _sentences(self, text: str) -> List[str]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return [s.strip() for s in _SENT_RE.split(cleaned) if len(s.strip()) > 30]

    def _keywords(self, text: str, limit: int = 12) -> List[str]:
        words = [w.lower() for w in _WORD_RE.findall(text or "")]
        counts = Counter(w for w in words if w not in _STOPWORDS and len(w) > 2)
        return [w for w, _ in counts.most_common(limit)]

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------
    def cap_summarize(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Summarise source text into a brief with bullet points (USE)."""
        topic = (params.get("topic") or "").strip()
        sources = self._normalise_sources(params)
        length = params.get("length") or "brief"
        budget = {"brief": 4, "short": 4, "medium": 6, "detailed": 16}.get(length, 4)

        supplied_text = str(params.get("text") or "")
        joined = supplied_text or "\n\n".join(s["extract"] for s in sources if s.get("extract"))
        if not joined and not topic:
            raise ServiceError("nothing to summarise: provide text or a topic")

        abstract = params.get("abstract") or ""
        if abstract and len(abstract) > 200:
            joined = f"{abstract}\n\n{joined}"

        system = (
            "You are a precise technical writer inside an operating system. "
            "Write factual, neutral prose. No markdown headings, no preamble."
        )
        prompt = (
            f"Write a {length} summary of the topic \"{topic or 'the provided text'}\" "
            f"in at most {budget * 40} words, based ONLY on the source material below. "
            "Then on a new line output the heading 'KEY POINTS' followed by "
            f"{budget} short bullet points, each starting with '- '.\n\n"
            f"SOURCE MATERIAL:\n{joined[:9000]}"
        )

        text, provider = self._generate(system, prompt, max_tokens=1600 if budget > 9 else 800)
        if not text:
            text = self._extractive_summary(joined, max_sentences=budget)
            key_sentences = self._sentences(self._extractive_summary(joined, budget * 2))[:budget]
            text += "\nKEY POINTS\n" + "\n".join(f"- {s}" for s in key_sentences)

        summary, bullets = self._split_summary(text)
        if not summary:
            summary = self._extractive_summary(joined, max_sentences=budget)
        if not bullets:
            bullets = self._sentences(summary)[:budget]
        if not bullets:
            bullets = [s["title"] for s in sources if s.get("title")][:budget]

        return {
            "topic": topic or (sources[0]["title"] if sources else "summary"),
            "summary": summary,
            "bullets": bullets,
            "provider": provider,
            "provider_errors": list(getattr(self, "_last_errors", [])),
            "words": len(summary.split()),
            "sources_used": len(sources),
            "status": f"summary generated by {provider}",
        }

    def cap_extract_keywords(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Rank the key terms of a text or topic set (USE)."""
        sources = self._normalise_sources(params)
        text = " ".join(s.get("extract", "") for s in sources)
        text = text or (params.get("title") or "")
        if not text.strip():
            raise ServiceError("no text available for keyword extraction")
        keywords = self._keywords(text, int(params.get("limit") or 12))
        return {
            "keywords": keywords,
            "count": len(keywords),
            "titles": [s.get("title") for s in sources if s.get("title")],
            "status": f"{len(keywords)} keyword(s) extracted",
        }

    def cap_compose_document(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Compose a complete Markdown document from research artefacts (USE)."""
        topic = (params.get("topic") or "").strip() or "Research Brief"
        summary = (params.get("summary") or "").strip()
        bullets = params.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [line.strip("- ").strip() for line in bullets.splitlines() if line.strip()]
        sources = self._normalise_sources(params)
        keywords = params.get("keywords") or []
        length = params.get("length") or "brief"

        if not summary and sources:
            summary = self._extractive_summary(
                " ".join(s["extract"] for s in sources), max_sentences=5
            )
        if not summary:
            raise ServiceError("nothing to compose: no summary or sources available")

        # Let the model expand a body section when we have grounding data.
        body = ""
        joined = "\n\n".join(s["extract"] for s in sources if s.get("extract"))
        if joined and not self.offline_only:
            body, _ = self._generate(
                "You are a technical writer producing a well-structured "
                "Markdown report. Use '## ' subsections and short paragraphs.",
                f"Write a {length} technical brief about \"{topic}\". Base it only on "
                f"the source material. Include 2-3 subsections.\n\n"
                f"SOURCE MATERIAL:\n{joined[:8000]}",
                max_tokens=1100,
            )

        doc = self._render_markdown(topic, summary, bullets, body, sources, keywords)
        return {
            "topic": topic,
            "filename": self._filename_for(topic, params, intent),
            "document": doc,
            "chars": len(doc),
            "words": len(doc.split()),
            "sections": doc.count("\n## "),
            "sources": [s.get("title") for s in sources if s.get("title")],
            "provider": self.last_provider,
            "status": f"document composed ({len(doc.split())} words)",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _filename_for(topic: str, params: Dict[str, Any], intent=None) -> str:
        """Derive a human-readable, collision-safe filename for the artefact.

        The file the user gets must be recognisable in their folder, so the
        name comes from the topic and the kind of document requested rather
        than a generic 'output.md'.
        """
        from services.filesystem.service import safe_filename

        kind = {
            "create_summary": "Summary",
            "research_topic": "Research",
            "write_document": "Document",
        }.get(getattr(intent, "intent_type", ""), "Report")
        extension = params.get("format") or ".md"
        if extension not in (".md", ".txt", ".html", ".csv", ".json"):
            extension = ".md"          # binary formats fall back to text
        return safe_filename(f"{topic} - {kind}", default_ext=extension)
    def _normalise_sources(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = params.get("sources") or params.get("pages") or []
        if isinstance(raw, dict):
            raw = [raw]
        out = []
        for item in raw:
            if isinstance(item, dict) and (item.get("extract") or item.get("snippet")):
                out.append({
                    "title": item.get("title") or "",
                    "extract": item.get("extract") or item.get("snippet") or "",
                    "url": item.get("url") or "",
                    "source": item.get("source") or "web",
                })
        text = params.get("text")
        if text:
            out.append({"title": params.get("title") or "provided text",
                        "extract": str(text), "url": "", "source": "local"})
        return out

    def _split_summary(self, text: str) -> Tuple[str, List[str]]:
        """Split generated text into (prose summary, bullet list)."""
        if not text:
            return "", []
        bullets: List[str] = []
        prose_lines: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("KEY POINTS"):
                continue
            if stripped.startswith(("-", "*", "\u2022", "1.", "2.", "3.", "4.", "5.")):
                bullets.append(re.sub(r"^([-*\u2022]|\d+\.)\s*", "", stripped).strip())
            elif stripped:
                prose_lines.append(stripped)
        return " ".join(prose_lines).strip(), [b for b in bullets if b]

    def _extractive_summary(self, text: str, max_sentences: int = 5) -> str:
        """Frequency-scored sentence selection (no network required)."""
        sentences = self._sentences(text)
        if not sentences:
            return (text or "").strip()
        if len(sentences) <= max_sentences:
            return " ".join(sentences)

        freq = Counter(self._keywords(text, 40))
        scored: List[Tuple[float, int, str]] = []
        for index, sentence in enumerate(sentences):
            words = [w.lower() for w in _WORD_RE.findall(sentence)]
            if not words:
                continue
            score = sum(freq.get(w, 0) for w in words) / math.sqrt(len(words))
            if index < 2:                     # lead sentences are informative
                score *= 1.25
            if index == 0:
                score *= 1.15
            scored.append((score, index, sentence))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = sorted(scored[:max_sentences], key=lambda item: item[1])
        return " ".join(sentence for _, _, sentence in chosen)

    def _render_markdown(self, topic: str, summary: str, bullets: List[str],
                         body: str, sources: List[Dict[str, Any]],
                         keywords: List[str]) -> str:
        from datetime import datetime
        lines = [
            f"# {topic}",
            "",
            f"*Generated by IntentOS on {datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"using the {self.last_provider} provider.*",
            "",
            "## Summary",
            "",
            summary,
            "",
        ]
        if bullets:
            lines += ["## Key Points", ""]
            lines += [f"- {b}" for b in bullets]
            lines.append("")
        if body:
            lines += ["## Detailed Briefing", "", body.strip(), ""]
        if keywords:
            lines += ["## Keywords", "", ", ".join(keywords), ""]
        if sources:
            lines += ["## Sources", ""]
            for index, source in enumerate(sources, 1):
                title = source.get("title") or f"Source {index}"
                url = source.get("url") or ""
                lines.append(f"{index}. {title}" + (f" \u2014 {url}" if url else ""))
            lines.append("")
        lines += ["---", "", "*Produced by the IntentOS intent kernel.*", ""]
        return "\n".join(lines)
