"""Web search providers used to discover real past question papers.

Two engines, tried in order:

1. **Google Programmable Search** (Custom Search JSON API) — real Google
   results, ranked properly, with `fileType=pdf` support so actual paper PDFs
   surface first. Needs a free API key + search-engine id (100 queries/day
   free tier). Configure `GOOGLE_API_KEY` and `GOOGLE_CSE_ID` in `.env`.
2. **DuckDuckGo** via the free `ddgs` package — no key at all. Used when
   Google isn't configured, or when it errors / runs out of daily quota.

`SEARCH_PROVIDER` in `.env` pins one engine (`google` / `ddg`) instead of the
default `auto` chain.
"""
import logging

import requests

from config import Config

log = logging.getLogger("padhai.search")

GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


class SearchError(RuntimeError):
    """No engine could answer the query."""


def google_configured() -> bool:
    return bool(Config.GOOGLE_API_KEY and Config.GOOGLE_CSE_ID)


def engine_chain() -> list[str]:
    """Which engines to try, in order, for the current configuration."""
    pref = Config.SEARCH_PROVIDER or "auto"
    if pref == "google":
        if not google_configured():
            raise SearchError(
                "SEARCH_PROVIDER=google, but GOOGLE_API_KEY / GOOGLE_CSE_ID are "
                "missing from .env."
            )
        return ["google"]
    if pref in ("ddg", "duckduckgo"):
        return ["duckduckgo"]
    return (["google"] if google_configured() else []) + ["duckduckgo"]


def provider_label() -> str:
    """Human-readable name of the engine that would be tried first."""
    try:
        return {"google": "Google", "duckduckgo": "DuckDuckGo"}[engine_chain()[0]]
    except (SearchError, IndexError):
        return "unavailable"


def search(query: str, limit: int = 8, file_type: str = "") -> tuple[list[dict], str]:
    """Run one query through the engine chain.

    Returns ``(results, engine_used)`` where each result is
    ``{"title", "url", "snippet"}``. Raises :class:`SearchError` only when
    every engine failed (an engine returning zero hits is not a failure).
    """
    errors = []
    for engine in engine_chain():
        runner = _google if engine == "google" else _duckduckgo
        try:
            return runner(query, limit, file_type), engine
        except SearchError as exc:
            log.warning("%s search failed: %s", engine, exc)
            errors.append(f"{engine}: {exc}")
    raise SearchError(" | ".join(errors) or "No search engine is available.")


# ---------------------------------------------------------------------------
# Google Programmable Search
# ---------------------------------------------------------------------------

def _google(query: str, limit: int, file_type: str = "") -> list[dict]:
    params = {
        "key": Config.GOOGLE_API_KEY,
        "cx": Config.GOOGLE_CSE_ID,
        "q": query,
        "num": max(1, min(limit, 10)),  # the API caps a page at 10
        "safe": "active",
    }
    if file_type:
        params["fileType"] = file_type

    try:
        resp = requests.get(GOOGLE_ENDPOINT, params=params, timeout=20)
    except Exception as exc:
        raise SearchError(f"could not reach Google ({exc})") from exc

    if resp.status_code in (403, 429):
        raise SearchError(
            f"daily quota or key problem — {_google_error(resp)}. "
            "The free tier allows 100 searches/day."
        )
    if resp.status_code >= 400:
        raise SearchError(f"HTTP {resp.status_code} — {_google_error(resp)}")

    try:
        items = (resp.json() or {}).get("items") or []
    except ValueError as exc:
        raise SearchError("Google returned a malformed response") from exc

    return [
        {
            "title": (item.get("title") or "").strip(),
            "url": (item.get("link") or "").strip(),
            "snippet": (item.get("snippet") or "").strip(),
        }
        for item in items
        if item.get("link")
    ]


def _google_error(resp: requests.Response) -> str:
    try:
        return str((resp.json().get("error") or {}).get("message") or "")[:200]
    except Exception:
        return resp.text[:200]


# ---------------------------------------------------------------------------
# DuckDuckGo (free, no key)
# ---------------------------------------------------------------------------

def _duckduckgo(query: str, limit: int, file_type: str = "") -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise SearchError(
            "the free 'ddgs' package is not installed (pip install ddgs)"
        ) from exc

    # DuckDuckGo has no fileType parameter — express it as a search operator.
    if file_type:
        query = f"{query} filetype:{file_type}"

    try:
        with DDGS() as ddgs:
            rows = ddgs.text(query, max_results=limit) or []
    except Exception as exc:
        raise SearchError(str(exc)) from exc

    return [
        {
            "title": (row.get("title") or "").strip(),
            "url": (row.get("href") or "").strip(),
            "snippet": (row.get("body") or "").strip(),
        }
        for row in rows
        if row.get("href")
    ]
