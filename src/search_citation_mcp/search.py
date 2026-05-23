"""Pipeline de búsqueda académica: OpenAlex descubre, cache read-first."""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from .apis import openalex, crossref, semanticscholar
from .access import ezproxy

CACHE_DIR = Path(
    os.getenv("SEARCH_CACHE_DIR", "/tmp/search_cache")
)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_EZPROXY_ENABLED = os.getenv("EZPROXY_HOST", "").strip() != ""


# ── search ─────────────────────────────────────────────────────────────────


def search_papers(query: str, count: int = 10, year_from: int = None,
                  year_to: int = None, exclude_preprints: bool = False) -> list:
    """Busca papers combinando OpenAlex + Semantic Scholar en paralelo.

    Pipeline:
    1. Cache read-first (evita repetir llamadas)
    2. OpenAlex + S2 en paralelo (si hay SEMANTIC_SCHOLAR_API_KEY)
    3. Dedup por DOI
    4. Enriquecer con EZProxy URL (si EZPROXY_HOST está configurado)
    5. Cache write
    """
    cached = find_cached(query=query)
    if cached:
        return cached

    results = []
    seen_dois = set()

    s2_enabled = bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY"))

    if s2_enabled:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(
                    openalex.search, query, count, year_from, year_to,
                ): "openalex",
                executor.submit(
                    semanticscholar.search, query, count, year_from, year_to,
                ): "s2",
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    api_results = future.result()
                except Exception:
                    continue
                _merge_results(api_results, source, seen_dois,
                               exclude_preprints, results)
    else:
        try:
            api_results = openalex.search(query, count, year_from, year_to)
        except Exception:
            api_results = []
        _merge_results(api_results, "openalex", seen_dois,
                       exclude_preprints, results)

    _save_cache(query, results)
    return results


def _merge_results(api_results: list, source: str, seen_dois: set,
                   exclude_preprints: bool, results: list):
    """Dedup y enriquecer resultados de una API."""
    for r in api_results:
        doi = r.get("doi", "").lower()

        if exclude_preprints and r.get("is_preprint"):
            continue
        if doi and doi in seen_dois:
            continue
        if doi:
            seen_dois.add(doi)

        r["source"] = source

        if _EZPROXY_ENABLED:
            url = r.get("url", "")
            proxy_url = ezproxy.to_ezproxy(doi=doi, url=url)
            r["url_ezproxy"] = proxy_url

        results.append(r)


# ── enrich / add_from_doi ────────────────────────────────────────────────


def enrich_paper(doi: str) -> dict:
    """Enriquece metadata de un paper consultando múltiples fuentes.

    Prioridad de fuente: Crossref → Semantic Scholar → OpenAlex
    Retorna metadata de la mejor fuente disponible, sin mezclar.
    """
    cr_data = crossref.fetch_by_doi(doi)
    if cr_data:
        cr_data["_source"] = "crossref"
        cr_data["_confidence"] = "high"
        return cr_data

    s2_data = semanticscholar.fetch_by_doi(doi)
    if s2_data and s2_data.get("doi"):
        s2_data["_source"] = "semanticscholar"
        s2_data["_confidence"] = "medium"
        return s2_data

    oa_data = openalex.fetch_by_doi(doi)
    if oa_data:
        oa_data["_source"] = "openalex"
        oa_data["_confidence"] = "low"
        oa_data["_warning"] = (
            "Solo OpenAlex tiene este paper. Verificar metadata manualmente."
        )
        return oa_data

    return {}


def add_from_doi(doi: str, bib_path: str = "") -> dict:
    """Pipeline completo de citación por DOI.

    1. Crossref (fuente autoritativa)
    2. OpenAlex + re-búsqueda en Crossref por título
    3. Semantic Scholar
    4. OpenAlex (último recurso, con advertencia)
    5. Generar .bib con fuente única
    6. Escribir a bibliografia.bib
    """
    from .generate import from_crossref_data, from_doi, from_fields, SCHEMA
    from .bibliography import append_entry as _append

    cr_data = crossref.fetch_by_doi(doi)
    if cr_data:
        entry = from_crossref_data(cr_data)
        key = _append(entry, bib_path)
        return _result(key, "crossref", "high", entry)

    oa_data = openalex.fetch_by_doi(doi)
    if oa_data:
        title = oa_data.get("title", "")
        author_list = oa_data.get("authors", [])
        first_author = author_list[0].split()[-1] if author_list else ""

        cr_search = crossref.search(f"{title} {first_author}", per_page=3)
        for cr_result in cr_search:
            cr_doi = cr_result.get("doi", "")
            cr_title = (cr_result.get("title") or "").lower()
            oa_title = (title or "").lower()
            if cr_doi and cr_doi.lower() != doi.lower():
                from rapidfuzz import fuzz as rf
                title_score = rf.token_sort_ratio(oa_title, cr_title)
                if title_score >= 80:
                    cr_full = crossref.fetch_by_doi(cr_doi)
                    if cr_full:
                        entry = from_crossref_data(cr_full)
                        key = _append(entry, bib_path)
                        r = _result(key, "crossref", "high", entry)
                        r["corrected_doi"] = cr_doi
                        r["original_doi"] = doi
                        return r

        s2_data = semanticscholar.fetch_by_doi(doi)
        if s2_data and s2_data.get("doi"):
            authors_raw = s2_data.get("raw", {}).get("authors", [])
            author_str = " and ".join(
                f"{a['name'].split()[-1]}, {a['name'].split()[0][0]}."
                if a.get("name") and " " in a.get("name", "")
                else a.get("name", "")
                for a in authors_raw
            )
            entry = from_fields("article", {
                "author": author_str,
                "title": s2_data.get("title", "").strip().rstrip("."),
                "journal": s2_data.get("journal", ""),
                "year": str(s2_data.get("year", "")),
                "doi": s2_data.get("doi", ""),
                "url": s2_data.get("url", ""),
            })
            key = _append(entry, bib_path)
            return _result(key, "semanticscholar", "medium", entry)

        entry = from_doi(doi, oa_data["raw"])
        key = _append(entry, bib_path)
        r = _result(key, "openalex", "low", entry)
        r["warning"] = (
            "Solo OpenAlex tiene este paper. Verificar metadata manualmente."
        )
        return r

    return {"error": f"No se encontró el DOI {doi} en ninguna fuente."}


def _result(key: str, source: str, confidence: str, entry: str) -> dict:
    from .validate import validate_after_append
    validation = validate_after_append(key, entry)
    return {
        "key": key,
        "source": source,
        "confidence": confidence,
        "entry": entry,
        "validation": validation,
    }


# ── related papers ────────────────────────────────────────────────────────


def find_related_papers(doi: str, count: int = 5,
                        exclude_preprints: bool = False) -> list:
    """Encuentra papers relacionados por similitud semántica y grafo de citas."""
    s2 = semanticscholar.fetch_by_doi(doi)
    paper_id = s2.get("corpus_id", "") if s2 else ""

    related = []
    seen = set()

    if paper_id:
        recs = semanticscholar.fetch_recommendations(paper_id, count)
        for r in recs:
            d = r.get("doi", "")
            if d and d.lower() not in seen:
                if exclude_preprints and r.get("is_preprint"):
                    continue
                seen.add(d.lower())
                related.append(r)

    if len(related) < count:
        oa = openalex.fetch_by_doi(doi)
        if oa:
            oa_id = oa.get("raw", {}).get("id", "")
            if oa_id:
                try:
                    extra = openalex._get_json(
                        "/works",
                        params={
                            "filter": f"cited_by:{oa_id}",
                            "per-page": count - len(related),
                            "sort": "cited_by_count:desc",
                        },
                    )
                    for r in extra.get("results", []):
                        loc = r.get("primary_location", {}) or {}
                        src = loc.get("source", {}) or {}
                        paper_doi = (r.get("doi") or "").replace(
                            "https://doi.org/", "",
                        )
                        if paper_doi and paper_doi.lower() not in seen:
                            seen.add(paper_doi.lower())
                            related.append({
                                "title": r.get("title", ""),
                                "doi": paper_doi,
                                "authors": [
                                    a.get("author", {}).get("display_name", "")
                                    for a in (r.get("authorships") or [])
                                ],
                                "year": r.get("publication_year"),
                                "cited_by": r.get("cited_by_count", 0),
                                "abstract": "",
                            })
                except Exception:
                    pass

    return related[:count]


# ── cache ─────────────────────────────────────────────────────────────────


def _save_cache(query: str, results: list):
    ts = int(datetime.now().timestamp() * 1000)
    safe_query = "".join(c if c.isalnum() else "_" for c in query[:40])
    cache_file = CACHE_DIR / f"{safe_query}_{ts}.json"
    entry = {
        "timestamp": ts,
        "query": query,
        "results": [
            {k: v for k, v in r.items() if k not in ("raw", "raw_oa")}
            for r in results
        ],
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    _clean_old_caches()


def _clean_old_caches(max_age_seconds: int = 3600):
    now = datetime.now().timestamp()
    for f in CACHE_DIR.iterdir():
        if f.suffix == ".json":
            try:
                parts = f.stem.rsplit("_", 1)
                ts = int(parts[-1]) / 1000
                if now - ts > max_age_seconds:
                    f.unlink()
            except (ValueError, IndexError):
                pass


def find_cached(query: str = "", doi: str = "", author: str = "",
                title: str = "") -> list | None:
    """Busca en caché por query exacta y retorna resultados completos."""
    for f in sorted(CACHE_DIR.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if query and data.get("query", "").lower() == query.lower():
            return data.get("results", [])
        if doi:
            for r in data.get("results", []):
                if r.get("doi", "").lower() == doi.lower():
                    return [r]
        if author:
            all_authors = " ".join(
                a for r in data.get("results", [])
                for a in (r.get("authors") or [])
            )
            if author.lower() in all_authors.lower():
                return [r for r in data.get("results", [])
                        if author.lower() in " ".join(r.get("authors") or [])]
        if title:
            for r in data.get("results", []):
                if title.lower() in r.get("title", "").lower():
                    return [r]
    return None


def list_cached(limit: int = 5) -> list:
    """Lista las últimas búsquedas en caché."""
    caches = sorted(CACHE_DIR.glob("*.json"), reverse=True)
    result = []
    for f in caches[:limit]:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            result.append({
                "query": data.get("query", ""),
                "count": len(data.get("results", [])),
                "timestamp": data.get("timestamp", 0),
            })
        except Exception:
            continue
    return result
