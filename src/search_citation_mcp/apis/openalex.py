"""OpenAlex REST API wrapper."""

import os
import time
import urllib.parse

import requests

from .._doi import normalize_doi
from .outcomes import (
    SourceOutcome, success, empty, timeout, http_error, network_error,
    rate_limited, with_circuit,
)

BASE_URL = "https://api.openalex.org"


def _get_params(extra=None):
    params = {}
    key = os.getenv("OPENALEX_API_KEY", "")
    if key:
        params["api_key"] = key
    mailto = os.getenv("OPENALEX_MAILTO", "")
    if mailto:
        params["mailto"] = mailto
    if extra:
        params.update(extra)
    return params


def _get_json(path: str, params: dict = None) -> SourceOutcome:
    """GET request a la API de OpenAlex, retorna SourceOutcome."""
    return with_circuit("openalex", _get_json_impl, path, params)


def _get_json_impl(path: str, params: dict = None) -> SourceOutcome:
    try:
        resp = requests.get(
            f"{BASE_URL}{path}",
            params=params or {},
            timeout=15,
        )
        if resp.status_code == 429:
            return rate_limited("openalex")
        if resp.status_code != 200:
            return http_error("openalex", resp.status_code)
        return success("openalex", resp.json())
    except requests.exceptions.Timeout:
        return timeout("openalex")
    except requests.exceptions.ConnectionError as e:
        return network_error("openalex", str(e))
    except requests.RequestException as e:
        return network_error("openalex", str(e))


def search(query: str, per_page: int = 10, year_from: int = None,
           year_to: int = None) -> SourceOutcome:
    """Busca works en OpenAlex con filtro de ano opcional."""
    return with_circuit("openalex", _search_impl, query, per_page, year_from, year_to)


def _search_impl(query: str, per_page: int = 10, year_from: int = None,
                 year_to: int = None) -> SourceOutcome:
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/works?search={encoded}&per_page={per_page}&sort=relevance_score:desc"
    params = _get_params()

    filters = []
    if year_from:
        filters.append(f"publication_year:{year_from}-")
    if year_to:
        if year_from:
            filters[-1] = f"publication_year:{year_from}-{year_to}"
        else:
            filters.append(f"publication_year:-{year_to}")
    if filters:
        params["filter"] = ",".join(filters)

    result = _get_json(url, params)
    if not result.is_success:
        return result
    data = result.data
    items = data.get("results", [])
    if not items:
        return empty("openalex")
    out = []
    for r in items:
        loc = r.get("primary_location", {}) or {}
        src = loc.get("source", {}) or {}
        oa = r.get("open_access", {}) or {}

        authors = []
        for a in r.get("authorships", []):
            name = a.get("author", {}).get("display_name", "")
            if name:
                authors.append(name)

        oa_type = r.get("type", "").lower()
        is_preprint = oa_type == "preprint"

        out.append({
            "title": r.get("title", ""),
            "doi": normalize_doi(r.get("doi") or ""),
            "authors": authors,
            "year": r.get("publication_year"),
            "journal": src.get("display_name", ""),
            "abstract": _extract_abstract(r.get("abstract_inverted_index", {})),
            "cited_by": r.get("cited_by_count", 0),
            "is_oa": oa.get("is_oa", False),
            "oa_status": oa.get("oa_status", ""),
            "oa_url": oa.get("oa_url", ""),
            "url": loc.get("landing_page_url", ""),
            "type": oa_type,
            "is_preprint": is_preprint,
            "raw": r,
        })

    time.sleep(0.1)
    return success("openalex", out)


def fetch_by_doi(doi: str) -> SourceOutcome:
    """Obtiene metadata completa de un work por DOI."""
    return with_circuit("openalex", _fetch_by_doi_impl, doi)


def _fetch_by_doi_impl(doi: str) -> SourceOutcome:
    url = f"{BASE_URL}/works/doi:{doi}"
    params = _get_params()

    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.exceptions.Timeout:
        return timeout("openalex")
    except requests.RequestException as e:
        return network_error("openalex", str(e))
    if resp.status_code != 200:
        return http_error("openalex", resp.status_code)

    r = resp.json()
    loc = r.get("primary_location", {}) or {}
    src = loc.get("source", {}) or {}
    oa = r.get("open_access", {}) or {}

    authors = []
    for a in r.get("authorships", []):
        name = a.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)

    biblio = r.get("biblio") or {}
    pages = ""
    if biblio.get("first_page") and biblio.get("last_page"):
        pages = f"{biblio['first_page']}--{biblio['last_page']}"

    oa_type = r.get("type", "").lower()
    is_preprint = oa_type == "preprint"

    return success("openalex", {
        "title": r.get("title", ""),
        "doi": normalize_doi(r.get("doi") or ""),
        "authors": authors,
        "year": r.get("publication_year"),
        "journal": src.get("display_name", ""),
        "abstract": _extract_abstract(r.get("abstract_inverted_index", {})),
        "volume": biblio.get("volume", ""),
        "issue": biblio.get("issue", ""),
        "pages": pages,
        "cited_by": r.get("cited_by_count", 0),
        "is_oa": oa.get("is_oa", False),
        "oa_status": oa.get("oa_status", ""),
        "oa_url": oa.get("oa_url", ""),
        "url": loc.get("landing_page_url", ""),
        "publication_date": r.get("publication_date", ""),
        "type": oa_type,
        "is_preprint": is_preprint,
        "publisher": src.get("host_organization_name", ""),
        "raw": r,
    })


def _extract_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    max_pos = max((p for positions in inverted_index.values() for p in positions), default=-1)
    words = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            if 0 <= pos < len(words):
                words[pos] = word
    return " ".join(words)
