"""Shared web-fetch helpers — free, no API keys.

Used by the past-paper importer and the import-from-link feature to turn
any online text (articles, notes pages, question listings) into usable
study material.
"""
import html as html_module
import ipaddress
import re
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MAX_FETCH_BYTES = 15 * 1024 * 1024


def validate_url(url: str) -> urllib.parse.ParseResult:
    """Allow only public http(s) URLs."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError("Only http(s) links can be imported.")
    host = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback:
            raise RuntimeError("That address is not allowed.")
    except ValueError:
        pass  # a normal hostname, not an IP literal
    if host in ("localhost",):
        raise RuntimeError("That address is not allowed.")
    return parsed


def download(url: str) -> tuple[bytes, str]:
    """Fetch a URL into memory. Returns (data, content_type)."""
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=45, stream=True)
        resp.raise_for_status()
        data = b""
        for chunk in resp.iter_content(65536):
            data += chunk
            if len(data) > MAX_FETCH_BYTES:
                raise RuntimeError("File too large to import (max 15 MB).")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not download: {exc}") from exc
    return data, (resp.headers.get("Content-Type") or "").lower()


# ---------------------------------------------------------------------------
# HTML → readable text (no external parser needed)
# ---------------------------------------------------------------------------

_DROP_RE = re.compile(
    r"<(script|style|noscript|svg|nav|footer|header|form)[^>]*>.*?</\1>",
    re.S | re.I,
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_BLOCK_RE = re.compile(
    r"</?(p|div|br|li|ul|ol|tr|td|th|table|h[1-6]|section|article|blockquote)[^>]*>",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_BOILER_RE = re.compile(
    r"^(jump to|skip to|from wikipedia|sign in|log ?in|sign up|register|"
    r"subscribe|menu|search|share|follow us|advertisement|sponsored|"
    r"accept cookies|cookie|privacy policy|terms of|©|all rights reserved|"
    r"download (our )?app|related articles|you may also like)",
    re.I,
)


def html_to_text(html: str) -> str:
    """Strip an HTML page down to its readable text content."""
    html = _COMMENT_RE.sub(" ", html)
    html = _DROP_RE.sub(" ", html)
    html = _BLOCK_RE.sub("\n", html)
    html = _TAG_RE.sub(" ", html)
    html = html_module.unescape(html)

    lines = []
    for line in html.split("\n"):
        line = re.sub(r"[ \t\u00a0]+", " ", line).strip()
        # Skip navigation crumbs, boilerplate and single-word menu items
        if len(line) < 3 or _BOILER_RE.match(line):
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def page_title(html: str, fallback: str = "web-page") -> str:
    m = _TITLE_RE.search(html)
    if not m:
        return fallback
    title = html_module.unescape(_TAG_RE.sub("", m.group(1))).strip()
    title = re.sub(r"[\\/:*?\"<>|]+", " ", title)  # filename-safe
    title = re.sub(r"\s{2,}", " ", title)
    return title[:80] or fallback
