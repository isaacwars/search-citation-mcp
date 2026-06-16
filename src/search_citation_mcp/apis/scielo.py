"""SciELO REST API wrapper — bibliographic database for Latin America/Iberia."""

import time
import urllib.parse

import requests

from .._doi import normalize_doi
from .outcomes import (
    with_circuit,

    SourceOutcome, success, empty, timeout, http_error, network_error,
    rate_limited,
)

SEARCH_URL = "https://search.scielo.org/"
ARTICLE_URL = "https://articlemeta.scielo.org/api/v1/"


def search(query: str, per_page: int = 10, year_from: int = None, year_to: int = None) -> SourceOutcome:
    return with_circuit("scielo", _search_impl, query, per_page, year_from, year_to)


def _search_impl(query: str, per_page: int = 10, year_from: int = None,
           year_to: int = None) -> SourceOutcome:
    """Busca artículos en SciELO."""
    params = {
        "q": query,
        "output": "json",
        "format": "json",
        "from": 0,
        "count": min(per_page, 50),
    }
    if year_from:
        params["from_year"] = str(year_from)
    if year_to:
        params["to_year"] = str(year_to)

    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=15)
    except requests.exceptions.Timeout:
        return timeout("scielo")
    except requests.exceptions.ConnectionError as e:
        return network_error("scielo", str(e))
    except requests.RequestException as e:
        return network_error("scielo", str(e))

    if resp.status_code == 429:
        return rate_limited("scielo")
    if resp.status_code != 200:
        return http_error("scielo", resp.status_code)

    try:
        data = resp.json()
    except Exception:
        return malformed("scielo")

    results = data.get("results", [])
    out = []
    for r in results:
        coll = r.get("collection", {}) or {}
        authors = []
        for a in r.get("author_list", []):
            surname = a.get("surname", "")
            given = a.get("given_names", "")
            if surname:
                if given:
                    initials = " ".join(
                        f"{c}." if not c.endswith(".") else c
                        for c in given.split() if c
                    )
                    authors.append(f"{surname}, {initials}")
                else:
                    authors.append(surname)

        doi = normalize_doi(r.get("doi", "") or coll.get("doi", ""))

        pub_year = r.get("publication_year", "")
        journal = ""
        journal_data = r.get("journal", {}) or {}
        if journal_data:
            journal = journal_data.get("title", "")

        abstract = ""
        for text_elem in r.get("abstracts", []):
            if text_elem.get("language") in ("en", "es", "pt", None):
                abstract = text_elem.get("_", "")
                if abstract:
                    break

        out.append({
            "title": r.get("title", ""),
            "doi": doi,
            "scielo_id": r.get("id", ""),
            "authors": authors,
            "year": int(pub_year) if pub_year else None,
            "journal": journal,
            "abstract": abstract,
            "volume": r.get("volume", ""),
            "issue": r.get("number", ""),
            "url": r.get("html_url", ""),
            "type": "article",
            "is_preprint": False,
            "is_oa": True,
            "oa_url": "",
            "cited_by": 0,
            "raw": r,
        })

    time.sleep(0.1)
    return success("scielo", out) if out else empty("scielo")


def fetch_by_doi(doi: str) -> SourceOutcome:
    """Obtiene metadata de un artículo por DOI desde SciELO."""
    url = f"{ARTICLE_URL}article/?code={urllib.parse.quote(doi)}"
    try:
        resp = requests.get(url, timeout=15)
    except requests.exceptions.Timeout:
        return timeout("scielo")
    except requests.exceptions.ConnectionError as e:
        return network_error("scielo", str(e))
    except requests.RequestException as e:
        return network_error("scielo", str(e))

    if resp.status_code == 429:
        return rate_limited("scielo")
    if resp.status_code != 200:
        return http_error("scielo", resp.status_code)

    try:
        data = resp.json()
    except Exception:
        return malformed("scielo")

    if not data or not isinstance(data, dict):
        return empty("scielo")

    results = data.get("objects", [])
    if not results:
        return empty("scielo")

    normalized = _normalize_article(results[0])
    return success("scielo", normalized) if normalized else empty("scielo")


def _normalize_article(r: dict) -> dict:
    """Convierte un artículo de SciELO al formato estandarizado."""
    authors = []
    for a in r.get("author", []):
        surname = a.get("surname", "")
        given = a.get("given_names", "")
        if surname:
            if given:
                initials = " ".join(
                    f"{c}." if not c.endswith(".") else c
                    for c in given.split() if c
                )
                authors.append(f"{surname}, {initials}")
            else:
                authors.append(surname)

    doi = normalize_doi(r.get("doi", ""))

    journal = ""
    journal_title = r.get("journal_title", "")
    if isinstance(journal_title, list):
        journal = journal_title[0] if journal_title else ""
    else:
        journal = journal_title or ""

    pub_year = r.get("publication_year", "")

    volume = r.get("volume", "")
    issue = r.get("number", "")

    page_info = ""
    start_page = r.get("start_page", "")
    end_page = r.get("end_page", "")
    elocation = r.get("elocation", "")
    if start_page and end_page:
        page_info = f"{start_page}--{end_page}"
    elif elocation:
        page_info = elocation

    abstract = ""
    for text_elem in r.get("abstracts", []):
        if text_elem.get("language") in ("en", "es", "pt", None):
            abstract = text_elem.get("_", "")
            if abstract:
                break

    return {
        "title": r.get("title", ""),
        "doi": doi,
        "authors": authors,
        "year": int(pub_year) if pub_year else None,
        "journal": journal,
        "abstract": abstract,
        "volume": volume,
        "issue": issue,
        "pages": page_info,
        "cited_by": 0,
        "is_oa": True,
        "oa_status": "gold",
        "oa_url": "",
        "url": r.get("html_url", ""),
        "publication_date": str(pub_year or ""),
        "type": "article",
        "publisher": r.get("publisher_name", ""),
        "issn": r.get("issn", ""),
        "raw": r,
    }
