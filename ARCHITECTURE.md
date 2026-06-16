# search-citation-mcp

Búsqueda académica y citación IEEE como servidor MCP.

## Pipeline

```
User Query / DOI
    │
    ├── detect_input() ──── ¿DOI? arXiv? PMID? ISBN? URL? title?
    │
    └── search_papers()
         │
         ├─ 1. cache read-first (query + count + year_from + year_to + exclude_preprints)
         │
         ├─ 2. fetch_by_doi() ── si el query es DOI, resultado exacto desde OpenAlex
         │
         ├─ 3. parallel search ── OpenAlex + Crossref + SciELO (+ Semantic Scholar si API key)
         │        con timeout 30s por fuente, orden determinista alfabético
         │
         ├─ 4. dedup by DOI + merge determinista
         │
         ├─ 5. truncar a count
         │
         └─ 6. cache write atómico (tempfile + os.replace)

add_from_doi(doi)
    │
    ├── cross_verify_doi() ── 4 fuentes en paralelo (timeout 20s), majority voting
    │                           devuelve raw_data para reusar
    │
    ├── Crossref fetch → bibtex entry → bibliografia.bib
    ├── OpenAlex + Crossref re-search (title fuzzy match + author/year multi-campo)
    ├── Semantic Scholar (si API key)
    └── OpenAlex fallback
```

## Fuentes

| Fuente | API | Rate limit | Requiere API key |
|--------|-----|------------|-----------------|
| OpenAlex | api.openalex.org | ~10 req/s | No (recomendada) |
| Crossref | api.crossref.org | ~50 req/s | No (mailto recomendado) |
| Semantic Scholar | api.semanticscholar.org | ~100/s (con key) | Sí |
| SciELO | search.scielo.org | Sin doc | No |

## Fusión

- **search_papers**: deduplicación por DOI + título. Prevalece primer fuente en llegar.
- **cross_verify_doi**: 4 fuentes en paralelo. Majority voting sobre autor+título+año. Si 2+ coinciden, usa mayoría con warning a la minoría. Si 1 sola fuente, sin warning.
- **add_from_doi**: prioridad Crossref → Semantic Scholar → OpenAlex. DOI correction con validación multi-campo (autor + año).

## MCP Tools

9 herramientas expuestas via FastMCP (stdio/sse/http):

1. `search_papers` — búsqueda multi-fuente
2. `add_from_doi` — citar por DOI + escribir a .bib
3. `cite_paper` — generar .bib sin escribir
4. `add_to_bibliography` — entrada manual (sin DOI)
5. `find_related_papers` — Semantic Scholar + OpenAlex
6. `detect_input` — detectar tipo de identificador
7. `list_cached` — listar caché
8. `fix_bib` — corregir .bib (Title Case, siglas, datasheets, URLs)
9. `download_paper` — PDF open access

## Caché

Directorio: `/tmp/search_cache` (configurable via `SEARCH_CACHE_DIR`).
Clave: `{query[:40]}_c{count}_yf{year_from}_yt{year_to}_ep{exclude_preprints}_{timestamp}.json`.
Escritura atómica: tempfile + `os.replace`. Limpieza: >1h antigüedad o >1000 archivos.
