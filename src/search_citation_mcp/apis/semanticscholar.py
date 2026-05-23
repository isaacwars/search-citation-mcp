"""Semantic Scholar API wrapper."""

import os
import time

import requests

BASE_URL = "https://api.semanticscholar.org/graph/v1"

SEARCH_FIELDS = [
    "title", "authors", "year", "abstract", "externalIds",
    "url", "openAccessPdf", "citationCount", "journal",
    "publicationTypes", "publicationVenue", "isOpenAccess",
    "fieldsOfStudy",
]

PAPER_FIELDS = SEARCH_FIELDS + ["publicationDate", "venue"]


def _headers():
    h = {}
    key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    if key:
        h["x-api-key"] = key
    return h


def search(query: str, count: int = 10, year_from: int = None, year_to: int = None) -> list:
    """Busca papers en Semantic Scholar."""
    params = {
        "query": query,
        "limit": min(count, 100),
        "fields": ",".join(SEARCH_FIELDS),
    }
    if year_from and year_to:
        params["year"] = f"{year_from}-{year_to}"
    elif year_from:
        params["year"] = f"{year_from}-"
    elif year_to:
        params["year"] = f"-{year_to}"

    resp = requests.get(
        f"{BASE_URL}/paper/search",
        params=params,
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        return []

    data = resp.json().get("data", [])
    out = []
    for r in data:
        ext = r.get("externalIds", {}) or {}
        oa = r.get("openAccessPdf") or {}
        authors = [a.get("name", "") for a in (r.get("authors") or [])]

        pub_types = r.get("publicationTypes") or []
        is_preprint = "Preprint" in pub_types

        venue = r.get("publicationVenue") or {}
        journal = venue.get("name", "")

        out.append({
            "title": r.get("title", ""),
            "doi": ext.get("DOI", ""),
            "arxiv_id": ext.get("ArXiv", ""),
            "corpus_id": r.get("paperId", ""),
            "authors": authors,
            "year": r.get("year"),
            "journal": journal,
            "abstract": r.get("abstract", ""),
            "cited_by": r.get("citationCount", 0),
            "is_oa": r.get("isOpenAccess", False),
            "oa_url": oa.get("url", ""),
            "url": r.get("url", ""),
            "publication_types": pub_types,
            "fields_of_study": r.get("fieldsOfStudy") or [],
            "is_preprint": is_preprint,
            "raw": r,
        })

    time.sleep(0.15)
    return out


def fetch_by_doi(doi: str) -> dict:
    """Obtiene metadata completa de un paper por DOI desde S2."""
    resp = requests.get(
        f"{BASE_URL}/paper/DOI:{doi}",
        params={"fields": ",".join(PAPER_FIELDS)},
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        return {}

    r = resp.json()
    ext = r.get("externalIds", {}) or {}
    oa = r.get("openAccessPdf") or {}
    authors = [a.get("name", "") for a in (r.get("authors") or [])]

    pub_types = r.get("publicationTypes") or []
    is_preprint = "Preprint" in pub_types

    venue = r.get("publicationVenue") or {}
    journal = venue.get("name", "")

    return {
        "title": r.get("title", ""),
        "doi": ext.get("DOI", ""),
        "arxiv_id": ext.get("ArXiv", ""),
        "corpus_id": r.get("paperId", ""),
        "authors": authors,
        "year": r.get("year"),
        "journal": journal,
        "abstract": r.get("abstract", ""),
        "cited_by": r.get("citationCount", 0),
        "is_oa": r.get("isOpenAccess", False),
        "oa_url": oa.get("url", ""),
        "url": r.get("url", ""),
        "publication_types": pub_types,
        "fields_of_study": r.get("fieldsOfStudy") or [],
        "is_preprint": is_preprint,
        "publication_date": r.get("publicationDate", ""),
        "raw": r,
    }


def fetch_recommendations(paper_id: str, count: int = 5) -> list:
    """Obtiene papers recomendados relacionados por similitud semántica."""
    resp = requests.get(
        f"{BASE_URL}/paper/{paper_id}/recommendations",
        params={
            "limit": min(count, 20),
            "fields": ",".join(SEARCH_FIELDS),
        },
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        return []

    data = resp.json().get("recommendedPapers", [])
    out = []
    for r in data:
        ext = r.get("externalIds", {}) or {}
        authors = [a.get("name", "") for a in (r.get("authors") or [])]
        pub_types = r.get("publicationTypes") or []
        out.append({
            "title": r.get("title", ""),
            "doi": ext.get("DOI", ""),
            "corpus_id": r.get("paperId", ""),
            "authors": authors,
            "year": r.get("year"),
            "abstract": r.get("abstract", ""),
            "cited_by": r.get("citationCount", 0),
            "url": r.get("url", ""),
            "is_preprint": "Preprint" in pub_types,
            "raw": r,
        })
    return out
