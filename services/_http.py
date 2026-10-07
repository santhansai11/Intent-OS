"""Minimal HTTP helpers for IntentOS network services (standard library only).

Kept deliberately small so the prototype runs on a bare Python install.
Every failure mode is normalised into `HttpError` so services can convert
it into a ServiceError and let the kernel's recovery path handle it.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "IntentOS/1.0 (intent-based OS layer prototype; educational)"


class HttpError(RuntimeError):
    """Raised when a network call fails (DNS, timeout, HTTP status, bad JSON)."""


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


def _open(url: str, timeout: float, headers: dict = None, data: bytes = None) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} from {_host(url)}") from exc
    except Exception as exc:  # URLError, socket timeout, ssl, ...
        raise HttpError(f"network error reaching {_host(url)}: {exc}") from exc


def _fix_c1(text: str) -> str:
    """Repair Windows-1252 C1 control characters decoded as latin-1.

    Some providers label responses ``charset=iso-8859-1`` while actually
    emitting cp1252 bytes, so punctuation such as the typographic
    apostrophe arrives as U+0092. Map those back to their real glyphs.
    """
    if not any("\u0080" <= ch <= "\u009f" for ch in text):
        return text
    table = {}
    for byte in range(0x80, 0xA0):
        try:
            table[chr(byte)] = bytes([byte]).decode("cp1252")
        except UnicodeDecodeError:
            continue
    return text.translate(str.maketrans(table))


def _decode(raw: bytes, url: str):
    try:
        return json.loads(_fix_c1(raw.decode("utf-8", errors="replace")))
    except json.JSONDecodeError as exc:
        raise HttpError(f"invalid JSON from {_host(url)}") from exc


def get_json(url: str, timeout: float = 20, headers: dict = None):
    """GET a URL and parse the body as JSON."""
    return _decode(_open(url, timeout, headers), url)


def post_json(url: str, payload, timeout: float = 90, headers: dict = None):
    """POST a JSON payload and parse the JSON response."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", **(headers or {})}
    return _decode(_open(url, timeout, headers, data), url)


def get_text(url: str, timeout: float = 90, headers: dict = None) -> str:
    """GET a URL and return the decoded body as text."""
    raw = _open(url, timeout, {"Accept": "text/plain", **(headers or {})})
    return _fix_c1(raw.decode("utf-8", errors="replace"))
