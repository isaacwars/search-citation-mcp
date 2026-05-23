"""DuckDuckGo Lite search — web scraping, no API key required."""

import re
import time
from urllib.parse import unquote

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

_SEARCH_DELAY = 3.0
_last_search_time = 0.0


def search(query: str, count: int = 5) -> list:
    """Busca en DuckDuckGo Lite. Para búsquedas web generales, no papers."""
    global _last_search_time

    elapsed = time.time() - _last_search_time
    if elapsed < _SEARCH_DELAY:
        time.sleep(_SEARCH_DELAY - elapsed)

    _last_search_time = time.time()

    try:
        resp = curl_requests.post(
            "https://lite.duckduckgo.com/lite/",
            data={"q": query, "kl": "wt-wt"},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            timeout=12,
            impersonate="chrome131",
        )
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for tr in soup.select("table.result-table tr"):
        links = tr.select("a.result-link")
        snippets = tr.select("td.result-snippet")
        if not links:
            continue
        title = links[0].get_text(strip=True)
        url = _extract_url(links[0].get("href", ""))
        snippet = snippets[0].get_text(strip=True) if snippets else ""
        if url:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= count:
            break
    return results


def _extract_url(raw: str) -> str:
    if "uddg=" in raw:
        m = re.search(r"uddg=([^&]+)", raw)
        if m:
            return unquote(m.group(1))
    return raw
