"""Web research service: live search and page extracts.

Backed by two free, key-less public APIs:

    * Wikipedia  -- search (action=query&list=search) and REST page summaries
    * DuckDuckGo -- Instant Answer API (abstracts and related topics)

The kernel treats this like any other service: it declares capabilities,
the permission manager decides whether an intent may call them, and every
call is checkpointed. Network failures raise ServiceError so the intent
enters RECOVERY instead of silently returning fake data.
"""
from __future__ import annotations

import html
import re
from typing import Any, Callable, Dict, List
from urllib.parse import quote

from intent_kernel.ipc.service_bus import ServiceError
from services._http import HttpError, get_json
from services.base_service import BaseService

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
DDG_API = "https://api.duckduckgo.com/"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Strip HTML markup/entities and collapse whitespace."""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub("", text or ""))).strip()


class WebService(BaseService):
    """Live research: search providers and fetch article extracts."""

    name = "web"
    description = "Live web research: Wikipedia + DuckDuckGo search and article extracts"

    def __init__(self, http_get: Callable = None, timeout: float = 20.0,
                 cache_ttl: float = 600.0, **kw):
        super().__init__(**kw)
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._http_get = http_get          # injectable for offline tests
        self._cache: Dict[str, Any] = {}
        self._cache_at: Dict[str, float] = {}

    # ------------------------------------------------------------------
    def _get(self, url: str):
        if self._http_get is not None:
            return self._http_get(url)
        return get_json(url, timeout=self.timeout)

    def _cached(self, key: str, factory: Callable):
        import time
        now = time.time()
        if key in self._cache and now - self._cache_at.get(key, 0.0) < self.cache_ttl:
            return self._cache[key]
        value = factory()
        self._cache[key] = value
        self._cache_at[key] = now
        return value

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------
    def cap_search(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Search Wikipedia and DuckDuckGo for a query (READ)."""
        query = (params.get("query") or params.get("topic") or "").strip()
        limit = int(params.get("limit") or 5)
        if not query:
            raise ServiceError("no search query provided")

        results: List[Dict[str, Any]] = []
        errors: List[str] = []
        providers: List[str] = []

        try:
            results.extend(self._wiki_search(query, limit))
            providers.append("wikipedia")
        except HttpError as exc:
            errors.append(f"wikipedia: {exc}")

        abstract = ""
        heading = ""
        try:
            answer = self._ddg_answer(query)
            abstract = answer.get("abstract", "")
            heading = answer.get("heading", "")
            results.extend(answer.get("related", []))
            providers.append("duckduckgo")
        except HttpError as exc:
            errors.append(f"duckduckgo: {exc}")

        # De-duplicate by title, keeping Wikipedia hits first.
        seen, unique = set(), []
        for item in results:
            title = item["title"].lower()
            if title in seen:
                continue
            seen.add(title)
            unique.append(item)

        if not unique and abstract:
            unique.append({
                "title": heading or query,
                "snippet": abstract,
                "url": "",
                "source": "duckduckgo",
            })

        if not unique:
            raise ServiceError(
                "web research failed for '" + query + "': " + ("; ".join(errors) or "no results")
            )

        return {
            "query": query,
            "results": unique[: max(limit, 1)],
            "count": len(unique),
            "top_title": unique[0]["title"],
            "abstract": abstract,
            "providers": providers,
            "errors": errors,
            "status": "research complete",
        }

    def cap_fetch(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Fetch the full intro extract of an article (READ)."""
        title = (params.get("title") or params.get("query") or "").strip()
        if not title:
            raise ServiceError("no article title provided")
        return self._wiki_summary(title)

    def cap_fetch_many(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Fetch intro extracts for several articles (READ).

        Accepts either a list of titles or the raw search-result list, so the
        planner can pipe ``web.search`` straight into this capability.
        """
        raw = params.get("titles") or params.get("results") or []
        if isinstance(raw, (str, dict)):
            raw = [raw]
        titles = []
        for item in raw:
            if isinstance(item, dict):
                candidate = item.get("title") or ""
                # Drop citation-style DuckDuckGo titles (they are not articles).
                if item.get("source") == "duckduckgo" and len(candidate) > 60:
                    continue
                titles.append(candidate)
            elif item:
                titles.append(str(item))
        errors: List[str] = []
        pages: List[Dict[str, Any]] = []
        for title in [t for t in titles if t][: int(params.get("limit") or 3)]:
            try:
                page = self._wiki_summary(title)
                if page.get("extract"):
                    pages.append(page)
            except (HttpError, ServiceError) as exc:
                errors.append(f"{title}: {exc}")
        if not pages:
            raise ServiceError("could not fetch any article extract: " + ("; ".join(errors) or "?"))
        return {
            "pages": pages,
            "count": len(pages),
            "errors": errors,
            "status": f"{len(pages)} source(s) fetched",
        }

    # ------------------------------------------------------------------
    # Provider adapters
    # ------------------------------------------------------------------
    def _wiki_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        url = (
            f"{WIKI_API}?action=query&list=search&format=json&srlimit={max(limit, 1)}"
            f"&srprop=snippet&srsearch={quote(query)}"
        )
        data = self._cached(f"search:{query}:{limit}", lambda: self._get(url))
        hits = ((data.get("query") or {}).get("search")) or []
        out = []
        for hit in hits:
            title = hit.get("title", "")
            out.append({
                "title": title,
                "snippet": _clean(hit.get("snippet", "")),
                "url": "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                "source": "wikipedia",
            })
        return out

    def _wiki_summary(self, title: str) -> Dict[str, Any]:
        url = WIKI_SUMMARY.format(title=quote(title.replace(" ", "_")))
        try:
            data = self._cached(f"summary:{title}", lambda: self._get(url))
        except HttpError as exc:
            raise ServiceError(f"could not fetch '{title}': {exc}") from exc
        extract = _clean(data.get("extract", ""))
        if not extract:
            raise ServiceError(f"no extract available for '{title}'")
        return {
            "title": data.get("title") or title,
            "extract": extract,
            "url": (data.get("content_urls") or {}).get("desktop", {}).get("page", ""),
            "source": "wikipedia",
            "chars": len(extract),
            "words": len(extract.split()),
        }

    def _ddg_answer(self, query: str) -> Dict[str, Any]:
        url = f"{DDG_API}?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        data = self._cached(f"ddg:{query}", lambda: self._get(url))
        related = []
        for topic in (data.get("RelatedTopics") or [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                text = _clean(topic.get("Text", ""))
                related.append({
                    "title": text[:80],
                    "snippet": text,
                    "url": topic.get("FirstURL", ""),
                    "source": "duckduckgo",
                })
        return {
            "abstract": _clean(data.get("AbstractText", "")),
            "heading": _clean(data.get("Heading", "")),
            "url": data.get("AbstractURL", ""),
            "related": related,
        }
