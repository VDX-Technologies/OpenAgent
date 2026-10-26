"""
Tool · Web
==========
Read web pages and search the web, stdlib only (urllib + html.parser).
Used both as agent tools and to inline pages attached to a chat message.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) VDX-OpenAgent"
MAX_CHARS = 12_000


class _Text(HTMLParser):
    """Collect readable text, skipping scripts, styles and page chrome."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = (re.sub(r"[ \t\xa0]+", " ", l).strip() for l in raw.splitlines())
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _get(url: str, timeout: int = 15) -> tuple[str, str]:
    """GET *url*; returns (content-type, decoded body). Only http(s) is allowed."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are supported")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en,*;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        body = r.read(3_000_000)
        charset = r.headers.get_content_charset() or "utf-8"
    return ctype, body.decode(charset, errors="replace")


def fetch_url(url: str, max_chars: int = MAX_CHARS) -> str:
    """Return the title and readable text of a web page (truncated to *max_chars*)."""
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    try:
        ctype, body = _get(url)
    except Exception as exc:
        logger.info("fetch_url failed for %s: %s", url, exc)
        return f"Error fetching {url}: {exc}"
    if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        p = _Text()
        p.feed(body)
        title, text = p.title.strip(), p.text()
    else:
        title, text = "", body.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(truncated)"
    return f"URL: {url}\nTitle: {title or '-'}\n\n{text or '(no readable text)'}"


def web_search(query: str, max_results: int = 6) -> str:
    """Search the web (DuckDuckGo HTML) and return titles, links and snippets."""
    try:
        _, body = _get("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}))
    except Exception as exc:
        return f"Search failed: {exc}"
    out = []
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()
    for i, (href, title) in enumerate(links[:max_results]):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        href = q.get("uddg", [href])[0]  # DuckDuckGo wraps results in a redirect
        snip = strip(snippets[i]) if i < len(snippets) else ""
        out.append(f"{i + 1}. {strip(title)}\n   {href}\n   {snip}")
    return "\n".join(out) or f"No results for: {query}"


TOOL_DESCRIPTORS = [
    {
        "name": "fetch_url",
        "description": "Open a web page and read its text. Use it whenever the user shares a link or you need a page's content.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full http(s) URL"}},
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the internet for up-to-date information; returns links you can open with fetch_url.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]

TOOLS = {
    "fetch_url": lambda url: fetch_url(url),
    "web_search": lambda query: web_search(query),
}
