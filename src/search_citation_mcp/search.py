"""Pipeline de búsqueda académica: OpenAlex descubre, cache read-first."""

import json
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime

log = logging.getLogger("search-citation")
from pathlib import Path

from .apis import openalex, crossref, semanticscholar, scielo
from .apis.outcomes import SourceOutcome
from .access import ezproxy
from ._doi import normalize_doi
from .detect import detect_input
from rapidfuzz import fuzz as rf

CACHE_DIR = Path(
    os.getenv("SEARCH_CACHE_DIR", "/tmp/search_cache")
)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_EZPROXY_ENABLED = os.getenv("EZPROXY_HOST", "").strip() != ""


@contextmanager
def _cache_lock():
    """Advisory lock para evitar race conditions entre cleanup y lectura de cache."""
    lock_file = CACHE_DIR / ".lock"
    fd = -1
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    except (OSError, ImportError):
        yield
    finally:
        if fd >= 0:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def _unwrap(outcome, errors: dict | None = None):
    """Desenvuelve SourceOutcome a dict/list, None si fallo.

    Si errors es un dict, registra el error de fuente en el para que
    el caller pueda exponerlo al agente."""
    if isinstance(outcome, SourceOutcome):
        if errors is not None and not outcome.is_success:
            errors[outcome.source] = {
                "type": outcome.error_type or "unknown",
                "message": outcome.error or "",
            }
        return outcome.data if outcome.is_success else None
    return outcome


# ── search ─────────────────────────────────────────────────────────────────


def search_papers(query: str, count: int = 10, year_from: int = None,
                  year_to: int = None, exclude_preprints: bool = False) -> list:
    """Busca papers. Retorna solo la lista de resultados (backward-compatible)."""
    results, _ = search_papers_with_errors(query, count, year_from, year_to, exclude_preprints)
    return results


def search_papers_with_errors(query: str, count: int = 10, year_from: int = None,
                              year_to: int = None, exclude_preprints: bool = False):
    """Busca papers combinando fuentes en paralelo con orden determinista.

    Retorna (results, source_errors)."""
    cached = find_cached(query=query, count=count, year_from=year_from,
                         year_to=year_to, exclude_preprints=exclude_preprints)
    if cached:
        return cached, {}

    results = []
    seen_dois = set()

    detected = detect_input(query)
    if detected["type"] == "doi" and detected["confidence"] == "high":
        doi = detected["value"]
        exact = _fetch_exact_doi(doi)
        if exact:
            is_preprint = exact.get("is_preprint", False)
            if not (exclude_preprints and is_preprint):
                exact["source"] = "openalex"
                results.append(exact)
                seen_dois.add(exact.get("doi", "").lower())
                if not exact.get("doi"):
                    title = exact.get("title", "").lower()
                    if title:
                        seen_dois.add(title)

    s2_enabled = bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY"))
    n_sources = 4 if s2_enabled else 3

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n_sources) as executor:
        futures = {
            "openalex": executor.submit(openalex.search, query, count, year_from, year_to),
            "crossref": executor.submit(crossref.search, query, count, year_from, year_to),
            "scielo": executor.submit(scielo.search, query, count, year_from, year_to),
        }
        if s2_enabled:
            futures["s2"] = executor.submit(semanticscholar.search, query, count, year_from, year_to)

        raw_results = {}
        source_errors = {}
        for source, future in futures.items():
            try:
                outcome = future.result(timeout=30)
                if isinstance(outcome, SourceOutcome):
                    if outcome.is_success and outcome.data:
                        raw_results[source] = outcome.data
                    else:
                        if outcome.error:
                            source_errors[source] = {
                                "type": outcome.error_type or "unknown",
                                "message": outcome.error,
                            }
                            log.warning(f"Error from {source}: {outcome.error_type} — {outcome.error}")
                        raw_results[source] = []
                else:
                    raw_results[source] = outcome
            except Exception as e:
                source_errors[source] = {"type": "executor_error", "message": str(e)}
                log.warning(f"Error fetching from {source}: {e}")
                raw_results[source] = []

    for source in sorted(raw_results.keys()):
        _merge_results(raw_results[source], source, seen_dois,
                       exclude_preprints, results)

    results = results[:count]

    if results:
        _save_cache(query, results, count=count, year_from=year_from,
                    year_to=year_to, exclude_preprints=exclude_preprints)
    return results, source_errors


def _extract_author_surnames(author_list: list) -> set:
    """Extrae apellidos de una lista de autores para comparacion."""
    surnames = set()
    for a in author_list:
        if isinstance(a, str):
            name = a.split(",")[0].strip().lower()
            surnames.add(name)
        elif isinstance(a, dict):
            name = a.get("display_name", "") or a.get("name", "")
            if " " in name:
                surnames.add(name.rsplit(" ", 1)[-1].strip().lower())
            else:
                surnames.add(name.lower())
    return surnames


def _merge_results(api_results: list, source: str, seen_dois: set,
                   exclude_preprints: bool, results: list):
    """Dedup y enriquecer resultados de una API."""
    for r in api_results:
        doi = (r.get("doi") or "").lower()
        title = (r.get("title") or "").lower().strip(".")

        if exclude_preprints and r.get("is_preprint"):
            continue
        if doi and doi in seen_dois:
            continue
        if not doi:
            if title and title in seen_dois:
                continue
        if doi:
            seen_dois.add(doi)
        if not doi and title:
            seen_dois.add(title)

        r["source"] = source

        if _EZPROXY_ENABLED:
            url = r.get("url", "")
            proxy_url = ezproxy.to_ezproxy(doi=doi, url=url)
            r["url_ezproxy"] = proxy_url

        results.append(r)


def _fetch_exact_doi(doi: str) -> dict | None:
    """Intenta obtener un paper exacto por DOI desde OpenAlex."""
    try:
        data = _unwrap(openalex.fetch_by_doi(doi))
        if not data or not data.get("title"):
            return None
        return data
    except Exception:
        return None


# ── enrich / add_from_doi ────────────────────────────────────────────────


def _confidence_from_evidence(source: str, fields_present: int,
                              sources_agreeing: int = 0,
                              has_doi_match: bool = False) -> str:
    """Asigna confianza basada en evidencia, no solo en proveedor."""
    score = fields_present * 2
    if sources_agreeing > 1:
        score += 15
    if has_doi_match:
        score += 20
    # Provider baseline
    provider_base = {"crossref": 10, "semanticscholar": 5, "openalex": 0}
    score += provider_base.get(source, 0)
    if score >= 30:
        return "high"
    elif score >= 15:
        return "medium"
    return "low"


def enrich_paper(doi: str) -> dict:
    """Enriquece metadata de un paper consultando multiples fuentes.

    Prioridad de fuente: Crossref -> Semantic Scholar -> OpenAlex
    Si OpenAlex tiene el paper pero Crossref no lo encontro por DOI,
    re-busca Crossref por titulo para encontrar metadatos de mayor calidad.
    Retorna metadata de la mejor fuente disponible, sin mezclar.
    Incluye _source_errors con los fallos de fuentes consultadas.
    """
    source_errors = {}

    cr_data = _unwrap(crossref.fetch_by_doi(doi), source_errors)
    if cr_data:
        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                     if cr_data.get(k))
        cr_data["_source"] = "crossref"
        cr_data["_confidence"] = _confidence_from_evidence("crossref", fields)
        cr_data["_source_errors"] = source_errors
        return cr_data

    s2_data = _unwrap(semanticscholar.fetch_by_doi(doi), source_errors)
    if s2_data and s2_data.get("doi"):
        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                     if s2_data.get(k))
        s2_data["_source"] = "semanticscholar"
        s2_data["_confidence"] = _confidence_from_evidence("semanticscholar", fields)
        s2_data["_source_errors"] = source_errors
        return s2_data

    oa_data = _unwrap(openalex.fetch_by_doi(doi), source_errors)
    if oa_data:
        title = oa_data.get("title", "")
        author_list = oa_data.get("authors", [])
        first_author = author_list[0].split()[-1] if author_list else ""
        cr_search = _unwrap(crossref.search(f"{title} {first_author}", per_page=3), source_errors)
        for cr_result in (cr_search if isinstance(cr_search, list) else []):
            cr_doi = cr_result.get("doi", "")
            cr_title = (cr_result.get("title") or "").lower()
            oa_title = (title or "").lower()
            if cr_doi and cr_doi.lower() != doi.lower():
                title_score = rf.token_sort_ratio(oa_title, cr_title)
                if title_score >= 80:
                    cr_full = _unwrap(crossref.fetch_by_doi(cr_doi), source_errors)
                    if cr_full and _validate_doi_correction(doi, cr_full, oa_data):
                        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                                     if cr_full.get(k))
                        cr_full["_source"] = "crossref"
                        cr_full["_confidence"] = _confidence_from_evidence(
                            "crossref", fields, has_doi_match=True)
                        cr_full["_corrected_doi"] = cr_doi
                        cr_full["_original_doi"] = doi
                        cr_full["_source_errors"] = source_errors
                        return cr_full

        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                     if oa_data.get(k))
        oa_data["_source"] = "openalex"
        oa_data["_confidence"] = _confidence_from_evidence("openalex", fields)
        oa_data["_warning"] = (
            "Solo OpenAlex tiene este paper. Verificar metadata manualmente."
        )
        oa_data["_source_errors"] = source_errors
        return oa_data

    return {"_source_errors": source_errors}


def _validate_doi_correction(doi: str, cr_data: dict, oa_data: dict) -> bool:
    """Valida que una correccion de DOI tenga suficiente evidencia multi-campo."""
    oa_authors = _extract_author_surnames(
        oa_data.get("authorships") or oa_data.get("authors") or [])
    cr_authors_list = cr_data.get("author") or cr_data.get("authors") or []
    cr_authors = _extract_author_surnames(cr_authors_list)
    author_match = len(oa_authors & cr_authors) > 0 if oa_authors and cr_authors else False

    cr_pub = (cr_data.get("published-print", {}) or
              cr_data.get("published-online", {}) or
              cr_data.get("issued", {}))
    cr_date_parts = (cr_pub.get("date-parts") or [[None]])[0]
    cr_year = cr_date_parts[0] if len(cr_date_parts) > 0 else None
    oa_year = oa_data.get("publication_year") or oa_data.get("year")
    year_match = (cr_year is not None and oa_year is not None
                  and abs(int(cr_year) - int(oa_year)) <= 1)

    return author_match and year_match


def add_from_doi(doi: str, bib_path: str = "") -> dict:
    """Pipeline completo de citacion por DOI.

    1. Crossref (fuente autoritativa)
    2. OpenAlex + re-busqueda en Crossref por titulo
    3. Semantic Scholar
    4. OpenAlex (ultimo recurso, con advertencia)
    5. Generar .bib con fuente unica
    6. Escribir a bibliografia.bib
    """
    from .generate import from_crossref_data, from_doi, from_fields, SCHEMA
    from .bibliography import append_entry as _append
    from .validate import cross_verify_doi

    source_errors = {}
    xv = cross_verify_doi(doi)
    pre = xv.get("raw_data", {})

    cr_data = _unwrap(crossref.fetch_by_doi(doi), source_errors)
    if not cr_data:
        pre_cr = pre.get("crossref")
        if isinstance(pre_cr, dict) and pre_cr.get("title"):
            cr_data = pre_cr
    if cr_data:
        entry = from_crossref_data(cr_data)
        key = _append(entry, bib_path)
        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                     if cr_data.get(k))
        return _result(key, "crossref",
                       _confidence_from_evidence("crossref", fields), entry,
                       cross_verify=xv, source_errors=source_errors,
                       title=cr_data.get("title", ""),
                       authors=cr_data.get("authors", []),
                       year=cr_data.get("year"),
                       doi=doi,
                       type=cr_data.get("type", ""),
                       journal=cr_data.get("journal", ""),
                       url=cr_data.get("url", ""))

    oa_data = _unwrap(openalex.fetch_by_doi(doi), source_errors)
    if not oa_data:
        pre_oa = pre.get("openalex")
        if isinstance(pre_oa, dict) and pre_oa.get("title"):
            oa_data = pre_oa
    if oa_data:
        title = oa_data.get("title", "")
        author_list = oa_data.get("authors", [])
        first_author = author_list[0].split()[-1] if author_list else ""

        cr_search = _unwrap(crossref.search(f"{title} {first_author}", per_page=3), source_errors)
        for cr_result in (cr_search if isinstance(cr_search, list) else []):
            cr_doi = cr_result.get("doi", "")
            cr_title = (cr_result.get("title") or "").lower()
            oa_title = (title or "").lower()
            if cr_doi and cr_doi.lower() != doi.lower():
                title_score = rf.token_sort_ratio(oa_title, cr_title)
                if title_score >= 80:
                    cr_full = _unwrap(crossref.fetch_by_doi(cr_doi), source_errors)
                    if cr_full and _validate_doi_correction(doi, cr_full, oa_data):
                        entry = from_crossref_data(cr_full)
                        key = _append(entry, bib_path)
                        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                                     if cr_full.get(k))
                        r = _result(key, "crossref",
                                    _confidence_from_evidence("crossref", fields, has_doi_match=True),
                                    entry, cross_verify=xv, source_errors=source_errors,
                                    title=cr_full.get("title", ""),
                                    authors=cr_full.get("authors", []),
                                    year=cr_full.get("year"),
                                    doi=cr_doi,
                                    type=cr_full.get("type", ""),
                                    journal=cr_full.get("journal", ""),
                                    url=cr_full.get("url", ""))
                        r["corrected_doi"] = cr_doi
                        r["original_doi"] = doi
                        return r

        s2_data = _unwrap(semanticscholar.fetch_by_doi(doi), source_errors)
        if s2_data and s2_data.get("doi"):
            authors_raw = s2_data.get("raw", {}).get("authors", [])
            author_str = " and ".join(
                f"{name_parts[-1]}, {name_parts[0][0]}."
                if " " in (a.get("name") or "")
                else a.get("name", "")
                for a in authors_raw
                if a.get("name", "").strip()
                for name_parts in [a.get("name", "").split()]
            )
            s2_pub_types = s2_data.get("publication_types") or s2_data.get("raw", {}).get("publicationTypes") or []
            entry_type = "article"
            if s2_pub_types:
                if any("Conference" in t for t in s2_pub_types):
                    entry_type = "inproceedings"
                elif any("Book" in t for t in s2_pub_types):
                    entry_type = "book"
                elif any("Thesis" in t for t in s2_pub_types):
                    entry_type = "phdthesis"

            entry_data = {
                "author": author_str,
                "title": s2_data.get("title", "").strip().rstrip("."),
                "year": str(s2_data.get("year", "")),
                "doi": s2_data.get("doi", ""),
                "url": s2_data.get("url", ""),
            }
            if entry_type == "inproceedings":
                entry_data["booktitle"] = s2_data.get("journal", "")
            else:
                entry_data["journal"] = s2_data.get("journal", "")
            entry = from_fields(entry_type, entry_data)
            key = _append(entry, bib_path)
            fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                         if s2_data.get(k))
            return _result(key, "semanticscholar",
                           _confidence_from_evidence("semanticscholar", fields), entry,
                           cross_verify=xv, source_errors=source_errors,
                           title=s2_data.get("title", ""),
                           authors=author_str,
                           year=str(s2_data.get("year", "")),
                           doi=doi,
                           type=entry_type,
                           journal=entry_data.get("journal") or entry_data.get("booktitle", ""),
                           url=s2_data.get("url", ""))

        entry = from_doi(doi, oa_data.get("raw", {}))
        try:
            key = _append(entry, bib_path)
        except ValueError:
            return {"error": f"No se pudo generar cita para {doi}. Metadatos insuficientes."}
        fields = sum(1 for k in ("title", "authors", "year", "journal", "doi")
                     if oa_data.get(k))
        r = _result(key, "openalex",
                    _confidence_from_evidence("openalex", fields), entry,
                    cross_verify=xv, source_errors=source_errors,
                    title=oa_data.get("title", ""),
                    authors=oa_data.get("authors", []),
                    year=oa_data.get("year"),
                    doi=doi,
                    type=oa_data.get("type", ""),
                    journal=oa_data.get("journal", ""),
                    url=oa_data.get("url", ""))
        r["warning"] = (
            "Solo OpenAlex tiene este paper. Verificar metadata manualmente."
        )
        return r

    return {"error": f"No se encontro el DOI {doi} en ninguna fuente."}


def _result(key: str, source: str, confidence: str, entry: str,
            cross_verify: dict = None, **extra) -> dict:
    from .validate import validate_after_append
    validation = validate_after_append(key, entry)
    result = {
        "key": key,
        "source": source,
        "confidence": confidence,
        "entry": entry,
        "validation": validation,
        **extra,
    }
    if cross_verify and cross_verify.get("warnings"):
        result["cross_verify"] = {
            "warnings": cross_verify["warnings"],
            "compared": cross_verify.get("compared", 0),
        }
    return result


# ── related papers ────────────────────────────────────────────────────────


def find_related_papers(doi: str, count: int = 5,
                        exclude_preprints: bool = False) -> list:
    """Encuentra papers relacionados. Retorna solo la lista (backward-compatible)."""
    results, _ = find_related_papers_with_errors(doi, count, exclude_preprints)
    return results


def find_related_papers_with_errors(doi: str, count: int = 5,
                                    exclude_preprints: bool = False):
    """Encuentra papers relacionados por similitud semantica y grafo de citas.
    Retorna (results, source_errors)."""
    source_errors = {}
    s2 = _unwrap(semanticscholar.fetch_by_doi(doi), source_errors)
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
        oa = _unwrap(openalex.fetch_by_doi(doi), source_errors)
        if oa:
            oa_raw = oa.get("raw", {}) if isinstance(oa.get("raw"), dict) else {}
            oa_id = oa_raw.get("id", "")
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
                    extra_data = _unwrap(extra, source_errors)
                    if isinstance(extra_data, dict):
                        for r in extra_data.get("results", []):
                            paper_doi = normalize_doi(r.get("doi") or "")
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
                except Exception as e:
                    log.warning(f"Error fetching extra citations from OpenAlex: {e}")

    return related[:count], source_errors


# ── cache ─────────────────────────────────────────────────────────────────


def _save_cache(query: str, results: list, count: int = 10,
                year_from: int = None, year_to: int = None,
                exclude_preprints: bool = False):
    try:
        ts = int(datetime.now().timestamp() * 1000)
        safe_query = "".join(c if c.isalnum() else "_" for c in query[:40])
        params = f"c{count}_yf{year_from or 0}_yt{year_to or 0}_ep{int(exclude_preprints)}"
        cache_file = CACHE_DIR / f"{safe_query}_{params}_{ts}.json"
        entry = {
            "timestamp": ts,
            "query": query,
            "count": count,
            "year_from": year_from,
            "year_to": year_to,
            "exclude_preprints": exclude_preprints,
            "results": [
                {k: v for k, v in r.items() if k not in ("raw", "raw_oa")}
                for r in results
            ],
        }
        tmp_fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR, suffix=".json")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, cache_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _clean_old_caches()
    except Exception as e:
        log.error(f"Cache write failed for query '{query[:50]}': {e}")


def _clean_old_caches(max_age_seconds: int = 3600, max_entries: int = 1000):
    with _cache_lock():
        now = datetime.now().timestamp()
        files = sorted(CACHE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime)
        for f in files:
            if f.suffix == ".json":
                try:
                    parts = f.stem.rsplit("_", 1)
                    ts = int(parts[-1]) / 1000
                    if now - ts > max_age_seconds:
                        f.unlink(missing_ok=True)
                except (ValueError, IndexError):
                    log.debug(f"Skipping cache file with unexpected name format: {f.name}")
                except OSError as e:
                    log.warning(f"Failed to remove expired cache file {f.name}: {e}")
        remaining = sorted(CACHE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime)
        for f in remaining[:-max_entries]:
            try:
                f.unlink(missing_ok=True)
            except OSError as e:
                log.warning(f"Failed to remove excess cache file {f.name}: {e}")


def find_cached(query: str = "", doi: str = "", author: str = "",
                title: str = "", count: int = 10,
                year_from: int = None, year_to: int = None,
                exclude_preprints: bool = False) -> list | None:
    """Busca en cache por query exacta y parametros, retorna resultados completos."""
    with _cache_lock():
        for f in sorted(CACHE_DIR.glob("*.json"), reverse=True):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as e:
                log.warning(f"Corrupt cache file {f}: {e}")
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            if query and data.get("query", "").lower() == query.lower():
                if (data.get("count") == count and
                    data.get("year_from") == year_from and
                    data.get("year_to") == year_to and
                    data.get("exclude_preprints") == exclude_preprints):
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
    """Lista las ultimas busquedas guardadas en cache."""
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
        except Exception as e:
            log.debug(f"Error reading cache file {f}: {e}")
            continue
    return result
