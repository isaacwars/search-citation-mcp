"""Crossref REST API wrapper."""

import os
import re
import urllib.parse
import time

import requests

BASE_URL = "https://api.crossref.org"

EXCLUDED_TYPES = {
    "peer-review", "reference-entry", "journal-issue", "journal",
    "component",
}


def _get_mailto():
    return os.getenv("CROSSREF_MAILTO", "")


def search(query: str, per_page: int = 10, year_from: int = None, year_to: int = None) -> list:
    """Busca works en Crossref con filtro de fecha opcional."""
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
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    data = resp.json()
    items = data.get("message", {}).get("items", [])
    out = []
    for r in items:
        cr_type = r.get("type", "")
        if cr_type in EXCLUDED_TYPES:
            continue
        out.append(_normalize_work(r))

    time.sleep(0.1)
    return out


def fetch_by_doi(doi: str) -> dict:
    """Obtiene metadata completa de un work por DOI desde Crossref."""
    url = f"{BASE_URL}/works/{urllib.parse.quote(doi)}"
    params = {"mailto": _get_mailto()}
    headers = {"User-Agent": f"CitationEngine/1.0 (mailto:{_get_mailto()})"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.RequestException:
        return {}
    if resp.status_code != 200:
        return {}

    r = resp.json().get("message", {})
    return _normalize_work(r)


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

    doi = r.get("DOI", "")

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
        "monograph": "book",
        "reference-book": "book",
        "report": "techreport",
        "dissertation": "phdthesis",
        "standard": "manual",
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
