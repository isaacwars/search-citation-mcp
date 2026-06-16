"""Crossref REST API wrapper."""

import os
import re
import urllib.parse
import time

import requests

from .._doi import normalize_doi
from .outcomes import (
    SourceOutcome, success, empty, timeout, http_error, network_error,
    rate_limited, with_circuit,
)

BASE_URL = "https://api.crossref.org"

EXCLUDED_TYPES = {
    "peer-review", "reference-entry", "journal-issue", "journal",
    "component",
}


def _get_mailto():
    return os.getenv("CROSSREF_MAILTO", "")


def search(query: str, per_page: int = 10, year_from: int = None,
           year_to: int = None) -> SourceOutcome:
    """Busca works en Crossref con filtro de fecha opcional."""
    return with_circuit("crossref", _search_impl, query, per_page, year_from, year_to)


def _search_impl(query: str, per_page: int = 10, year_from: int = None,
                 year_to: int = None) -> SourceOutcome:
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/works?query={encoded}&rows={per_page}&sort=relevance"
    params = {"mailto": _get_mailto()}
    headers = {"User-Agent": f"CitationEngine/1.0 (mailto:{_get_mailto()})"}

    if year_from and year_to:
        params["filter"] = f"from-pub-date:{year_from},until-pub-date:{year_to}"
    elif year_from:
        params["filter"] = f"from-pub-date:{year_from}"
    elif year_to:
        params["filter"] = f"until-pub-date:{year_to}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.exceptions.Timeout:
        return timeout("crossref", "Request timed out after 15s")
    except requests.exceptions.ConnectionError as e:
        return network_error("crossref", str(e))
    except requests.RequestException as e:
        return network_error("crossref", str(e))
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "")
        return rate_limited("crossref", int(retry) if retry and retry.isdigit() else None)
    if resp.status_code != 200:
        return http_error("crossref", resp.status_code)

    data = resp.json()
    items = data.get("message", {}).get("items", [])
    if not items:
        return empty("crossref")
    out = []
    for r in items:
        cr_type = r.get("type", "")
        if cr_type in EXCLUDED_TYPES:
            continue
        out.append(_normalize_work(r))

    time.sleep(0.1)
    return success("crossref", out)


def fetch_by_doi(doi: str) -> SourceOutcome:
    """Obtiene metadata completa de un work por DOI desde Crossref."""
    return with_circuit("crossref", _fetch_by_doi_impl, doi)


def _fetch_by_doi_impl(doi: str) -> SourceOutcome:
    url = f"{BASE_URL}/works/{urllib.parse.quote(doi)}"
    params = {"mailto": _get_mailto()}
    headers = {"User-Agent": f"CitationEngine/1.0 (mailto:{_get_mailto()})"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.exceptions.Timeout:
        return timeout("crossref")
    except requests.RequestException:
        return network_error("crossref")
    if resp.status_code != 200:
        return http_error("crossref", resp.status_code)

    r = resp.json().get("message", {})
    return success("crossref", _normalize_work(r))


def _normalize_work(r: dict) -> dict:
    """Convierte un work de Crossref al formato estandarizado del engine."""
    authors = []
    author_list = r.get("author") or r.get("editor") or []
    for a in author_list:
        family = a.get("family", "")
        given = a.get("given", "")
        if family:
            if given:
                initials = " ".join(
                    f"{c}." if not c.endswith(".") else c
                    for c in given.split() if c
                )
                authors.append(f"{family}, {initials}")
            else:
                authors.append(family)

    title = ""
    title_list = r.get("title", [])
    if title_list:
        title = title_list[0]

    journal = ""
    container = r.get("container-title", [])
    if container:
        journal = container[0]

    doi = normalize_doi(r.get("DOI") or "")

    pub_raw = (
        r.get("published-print", {})
        or r.get("published-online", {})
        or r.get("issued", {})
        or {}
    ).get("date-parts")
    pub_date_parts = pub_raw[0] if pub_raw else [None]

    year = pub_date_parts[0] if len(pub_date_parts) > 0 else None
    month = pub_date_parts[1] if len(pub_date_parts) > 1 else None

    abstract_text = r.get("abstract", "")
    if abstract_text and abstract_text.startswith("<"):
        abstract_text = re.sub(r"<[^>]+>", "", abstract_text).strip()

    links = r.get("link", [])
    landing_url = ""
    for link in links:
        if link.get("content-type") in ("text/html", "unspecified", None):
            landing_url = link.get("URL", "")
            break
    if not landing_url:
        resource = r.get("resource", {}).get("primary", {})
        landing_url = resource.get("URL", "")
    if not landing_url and doi:
        landing_url = f"https://doi.org/{doi}"

    if "xplorestaging" in landing_url and doi:
        landing_url = f"https://doi.org/{doi}"

    return {
        "title": title,
        "doi": doi,
        "authors": authors,
        "year": year,
        "journal": journal,
        "abstract": abstract_text,
        "volume": r.get("volume", ""),
        "issue": r.get("issue", ""),
        "pages": r.get("page", ""),
        "cited_by": r.get("is-referenced-by-count", 0),
        "is_oa": _license_is_oa(r.get("license", [])),
        "oa_status": "",
        "oa_url": "",
        "url": landing_url,
        "publication_date": f"{year}-{month:02d}" if year is not None and month is not None else str(year or ""),
        "type": _map_type(r.get("type", "")),
        "publisher": r.get("publisher", ""),
        "issn": (r.get("ISSN") or [None])[0] if (r.get("ISSN") or [None])[0] else "",
        "raw": r,
    }


def _map_type(cr_type: str) -> str:
    mapping = {
        "journal-article": "article",
        "proceedings-article": "inproceedings",
        "book": "book",
        "book-chapter": "incollection",
        "book-part": "incollection",
        "book-section": "incollection",
        "edited-book": "book",
        "book-set": "book",
        "book-series": "book",
        "monograph": "book",
        "reference-book": "book",
        "report": "techreport",
        "report-series": "techreport",
        "dissertation": "phdthesis",
        "standard": "manual",
        "standard-series": "manual",
        "dataset": "misc",
        "posted-content": "misc",
        "proceedings": "inproceedings",
        "other": "misc",
    }
    return mapping.get(cr_type, "misc")


def _license_is_oa(licenses: list) -> bool:
    oa_patterns = ["creativecommons", "by/", "publicdomain"]
    for lic in licenses:
        url = lic.get("URL", "").lower()
        if any(p in url for p in oa_patterns):
            return True
    return False
