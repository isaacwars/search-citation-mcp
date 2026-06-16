"""Search & Citation MCP Server — herramientas para búsqueda y citación."""

import json
import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("search-citation")

from mcp.server.fastmcp import FastMCP

from . import search as search_module
from .generate import from_fields
from .bibliography import append_entry
from .validate import validate_after_append
from .detect import detect_input as _detect
from .fixer import fix_bib_file
from .apis import openalex, semanticscholar, crossref
from .apis.outcomes import SourceOutcome
from .access.download import download_paper as _download

mcp = FastMCP(
    "search-citation",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8000")),
)

_SEARCH_FIELDS = (
    "title", "doi", "authors", "year", "abstract", "journal",
    "url", "oa_url", "is_oa", "is_preprint", "source",
)
_SOURCES = ("openalex", "crossref", "scielo", "s2")


def _ok(**fields) -> str:
    """Envolvente de respuesta exitosa."""
    return json.dumps({"ok": True, **fields}, ensure_ascii=False, indent=2)


def _error(message: str, error_type: str = "internal_error", **extra) -> str:
    """Envolvente de error unificada."""
    return json.dumps({
        "ok": False,
        "error": message,
        "error_type": error_type,
        **extra,
    }, ensure_ascii=False)


def _safe_path(arg: str, must_exist: bool = False) -> Path:
    """Valida que una ruta no escape del workspace actual."""
    cwd = Path.cwd().resolve()
    resolved = (cwd / arg).resolve()
    try:
        resolved.relative_to(cwd)
    except ValueError:
        raise ValueError(f"Ruta '{arg}' escapa del workspace (resuelta a '{resolved}')")
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"No existe: {resolved}")
    return resolved


# ── tools ──────────────────────────────────────────────────────────────────


@mcp.tool()
def search_papers(query: str, n: int = 10, offset: int = 0,
                  year_from: int = 0, year_to: int = 0,
                  exclude_preprints: bool = False) -> str:
    """Busca papers académicos por palabras clave.

    Usa OpenAlex como buscador principal y Semantic Scholar (si hay API key)
    para búsqueda semántica en paralelo.

    Args:
        query: términos de búsqueda (ej: "armónicos SFVI México")
        n: número máximo de resultados (default 10)
        offset: número de resultados a saltar para paginación (default 0)
        year_from: año inicio del filtro (0 = sin filtro)
        year_to: año fin del filtro (0 = sin filtro)
        exclude_preprints: excluir preprints de los resultados
    """
    try:
        yf = year_from if year_from > 0 else None
        yt = year_to if year_to > 0 else None
        results, source_errors = search_module.search_papers_with_errors(
            query, count=n + offset, year_from=yf, year_to=yt,
            exclude_preprints=exclude_preprints,
        )
        total = len(results)
        page = results[offset:offset + n]
        clean = [
            {k: v for k, v in r.items() if k in _SEARCH_FIELDS and v}
            for r in page
        ]
        sources_ok = [s for s in _SOURCES if s not in source_errors]
        return _ok(
            results=clean,
            total=total,
            offset=offset,
            count=len(clean),
            has_more=total > offset + n,
            sources={"ok": sources_ok, "errors": source_errors},
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def verify_identifier(identifier: str) -> str:
    """Verifica un DOI, arXiv ID o PMID sin escribir archivos.

    Consulta múltiples fuentes y retorna los metadatos resueltos,
    la fuente usada, nivel de confianza, y si hubo corrección de DOI.
    No modifica archivos. Usar antes de add_from_doi para previsualizar.

    Args:
        identifier: DOI, arXiv ID, o PMID a verificar (ej: 10.1016/j.rser.2015.08.042)
    """
    try:
        result = search_module.enrich_paper(identifier)
        if not result or not result.get("title"):
            return _ok(
                found=False,
                identifier=identifier,
                detail="No se encontró en ninguna fuente.",
                source_errors=result.get("_source_errors", {}),
            )
        return _ok(
            found=True,
            identifier=identifier,
            title=result.get("title", ""),
            authors=result.get("authors", []),
            year=result.get("year"),
            journal=result.get("journal", ""),
            doi=result.get("doi", ""),
            source=result.get("_source", ""),
            confidence=result.get("_confidence", ""),
            type=result.get("type", ""),
            is_preprint=result.get("is_preprint", False),
            url=result.get("url", ""),
            source_errors=result.get("_source_errors", {}),
            **({"corrected_doi": result["_corrected_doi"],
                "original_doi": identifier}
               if result.get("_corrected_doi") else {}),
            **({"warning": result["_warning"]}
               if result.get("_warning") else {}),
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def compare_sources(identifier: str) -> str:
    """Compara metadatos de Crossref, OpenAlex y Semantic Scholar para un DOI.

    Muestra campo por campo qué reporta cada fuente y marca desacuerdos.
    Útil cuando se sospecha que los metadatos son inconsistentes entre fuentes
    o cuando verify_identifier muestra confianza baja.

    Args:
        identifier: DOI del paper a comparar (ej: 10.1016/j.rser.2015.08.042)
    """
    _fields = {
        "crossref": ["title", "authors", "year", "journal", "volume", "issue",
                     "pages", "publisher", "type", "doi", "url"],
        "openalex": ["title", "authors", "year", "journal", "volume", "issue",
                     "pages", "publisher", "type", "doi", "url"],
        "s2":       ["title", "authors", "year", "journal", "volume", "issue",
                     "pages", "publisher", "type", "doi", "url"],
    }

    def _simplify_authors(authors):
        """Reduce lista de autores a formato comparable."""
        if isinstance(authors, list):
            return [a.strip().lower().rstrip(".") for a in authors if isinstance(a, str) and a.strip()]
        return []

    def _extract(data, field):
        if not isinstance(data, dict) or not data:
            return None
        if field == "authors":
            return _simplify_authors(data.get("authors", []))
        return data.get(field)

    try:
        from .apis.outcomes import SourceOutcome as SO
        sources = {}
        errors = {}

        for name, fetcher in [("crossref", crossref.fetch_by_doi),
                               ("openalex", openalex.fetch_by_doi),
                               ("s2", semanticscholar.fetch_by_doi)]:
            outcome = fetcher(identifier)
            if isinstance(outcome, SO):
                if outcome.is_success and outcome.data:
                    sources[name] = outcome.data
                else:
                    errors[name] = {
                        "type": outcome.error_type or "unknown",
                        "message": outcome.error or "No data",
                    }
            elif isinstance(outcome, dict) and outcome:
                sources[name] = outcome
            else:
                errors[name] = {"type": "unknown", "message": "No response"}

        if not sources:
            return _ok(identifier=identifier, sources={}, errors=errors,
                       fields_compared=[],
                       note="Ninguna fuente retornó datos para este identificador.")

        # Determinar campos comunes: unión de los que tienen datos
        all_fields = set()
        for src_data in sources.values():
            for field in _fields.get("crossref", []):
                val = _extract(src_data, field)
                if val is not None and val != "" and val != []:
                    all_fields.add(field)

        fields_compared = sorted(all_fields)
        by_field = {}
        for field in fields_compared:
            values = {}
            for name in sorted(sources.keys()):
                val = _extract(sources[name], field)
                values[name] = val
            # Determinar si hay desacuerdo
            non_null = [v for v in values.values() if v is not None and v != "" and v != []]
            agreements = len(set(
                json.dumps(v, sort_keys=True, default=str)
                if isinstance(v, (list, dict)) else str(v)
                for v in non_null
            ))
            by_field[field] = {
                "values": values,
                "agreement": "full" if len(non_null) <= 1 else (
                    "partial" if agreements == 1 else "conflict"
                ),
            }

        conflicts = [f for f, d in by_field.items() if d["agreement"] == "conflict"]
        return _ok(
            identifier=identifier,
            sources_available=sorted(sources.keys()),
            sources_unavailable=errors,
            by_field=by_field,
            conflicts=conflicts,
            sources_agree=len(conflicts) == 0,
        )
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def add_from_doi(doi: str) -> str:
    """Cita un paper por DOI y lo agrega a la bibliografía.

    Pipeline: Crossref → Semantic Scholar → OpenAlex.
    Usa una sola fuente por cita, sin mezclar datos.
    Si OpenAlex tiene un DOI incorrecto, busca el correcto en Crossref.
    Si el paper es preprint, intenta encontrar la versión publicada.

    Usar verify_identifier primero si solo se quiere previsualizar sin escribir.

    Args:
        doi: DOI del paper (ej: 10.1016/j.rser.2015.08.042)
    """
    try:
        result = search_module.add_from_doi(doi)
        if "error" in result:
            return _error(result["error"], error_type="not_found")
        xv = result.get("cross_verify", {})
        out = {
            "key": result["key"],
            "source": result["source"],
            "confidence": result["confidence"],
            "title": result.get("title", ""),
            "authors": result.get("authors", ""),
            "year": result.get("year"),
            "doi_resolved": result.get("doi", doi),
            "type": result.get("type", ""),
            "journal": result.get("journal", ""),
            "url": result.get("url", ""),
            "entry_preview": result.get("entry", ""),
            "source_errors": result.get("source_errors", {}),
        }
        if result.get("corrected_doi"):
            out["corrected_doi"] = result["corrected_doi"]
            out["original_doi"] = result["original_doi"]
        if result.get("warning"):
            out["warning"] = result["warning"]
        if result.get("validation", {}).get("warnings"):
            out["validation"] = result["validation"]
        if xv.get("warnings"):
            out["cross_verify"] = {"warnings": xv["warnings"],
                                   "compared": xv.get("compared", 0)}
        return _ok(**out)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def cite_paper(type: str, campos: dict, write: bool = False) -> str:
    """Genera entrada .bib validada. Opcionalmente la escribe a bibliografia.bib.

    Usar para fuentes SIN DOI: CFE, NOM, IEC, leyes, tesis, datasheets.

    Args:
        type: article | inproceedings | book | techreport | mastersthesis |
              phdthesis | manual | misc | online | incollection
        campos: dict con author, title, journal/booktitle, year, doi, url, etc.
        write: si True, escribe a bibliografia.bib (default False)
    """
    try:
        entry = from_fields(type, campos)
        out = {"entry": entry}
        if write:
            key = append_entry(entry)
            val = validate_after_append(key, entry)
            out["key"] = key
            out["written"] = True
            if val["warnings"]:
                out["validation"] = val
        else:
            out["written"] = False
        return _ok(**out)
    except ValueError as e:
        return _error(str(e), error_type="validation_error")


@mcp.tool()
def add_to_bibliography(type: str, campos: dict) -> str:
    """Genera entrada .bib validada y la agrega a bibliografia.bib.

    Para fuentes SIN DOI: CFE, NOM, IEC, leyes, tesis, datasheets.

    Args:
        type: entry type BibTeX
        campos: dict con author, title, journal/booktitle, year, etc.
    """
    return cite_paper(type=type, campos=campos, write=True)


@mcp.tool()
def find_related_papers(doi: str, n: int = 5,
                        exclude_preprints: bool = False) -> str:
    """Encuentra papers relacionados por similitud semántica y grafo de citas.

    Usa Semantic Scholar recommendations + OpenAlex citation graph.

    Args:
        doi: DOI del paper de referencia
        n: número de resultados (default 5)
        exclude_preprints: excluir preprints
    """
    try:
        results, source_errors = search_module.find_related_papers_with_errors(
            doi, count=n, exclude_preprints=exclude_preprints,
        )
        return _ok(results=results, source_errors=source_errors)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def detect_input(text: str) -> str:
    """Detecta si un texto es DOI, arXiv ID, PMID, ISBN, URL o título.

    Útil cuando el usuario pega un identificador sin especificar el tipo.

    Args:
        text: texto a analizar
    """
    result = _detect(text)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def list_cached() -> str:
    """Lista las últimas búsquedas guardadas en caché."""
    results = search_module.list_cached()
    if not results:
        return _ok(cached=[])
    return _ok(cached=results)


@mcp.tool()
def fix_bib(bib_path: str, dry_run: bool = False) -> str:
    """Corrige un archivo .bib: Title Case, protección de siglas, datasheets.

    Args:
        bib_path: ruta al archivo .bib
        dry_run: si True, solo muestra cambios sin escribir
    """
    try:
        safe = _safe_path(bib_path, must_exist=True)
        result = fix_bib_file(str(safe), dry_run=dry_run)
        return _ok(
            fixed=result["fixed"],
            unchanged=result["unchanged"],
            errors=result.get("errors", []),
            backup=result.get("backup", ""),
            url_warnings=result.get("url_warnings", []),
            dry_run=dry_run,
        )
    except (ValueError, FileNotFoundError) as e:
        return _error(str(e), error_type="invalid_path")


@mcp.tool()
def download_paper(doi: str, output_dir: str = "./papers") -> str:
    """Descarga el PDF de un paper desde repositorios gratuitos de acceso abierto.

    Cadena de descarga (legal, free-first):
    1. OpenAlex: URL de acceso abierto
    2. Semantic Scholar: PDF de acceso abierto
    3. Unpaywall: API gratuita que rastrea 56M+ PDFs OA
    4. arXiv: repositorio de preprints

    Args:
        doi: DOI del paper
        output_dir: directorio donde guardar el PDF (default ./papers)
    """
    try:
        oa_url = ""
        s2_pdf_url = ""
        arxiv_id = ""
        sources_tried = []

        oa_outcome = openalex.fetch_by_doi(doi)
        if isinstance(oa_outcome, SourceOutcome):
            if oa_outcome.is_success:
                oa = oa_outcome.data
                if isinstance(oa, dict):
                    oa_url = oa.get("oa_url", "")
                    raw = oa.get("raw", {}) if isinstance(oa.get("raw"), dict) else {}
                    arxiv_id = raw.get("ids", {}).get("arxiv", "") if isinstance(raw, dict) else ""
                sources_tried.append({"source": "openalex", "status": "ok"})
            else:
                sources_tried.append({
                    "source": "openalex",
                    "status": oa_outcome.error_type or "error",
                    "reason": oa_outcome.error or "",
                })

        s2_outcome = semanticscholar.fetch_by_doi(doi)
        if isinstance(s2_outcome, SourceOutcome):
            if s2_outcome.is_success:
                s2 = s2_outcome.data
                if isinstance(s2, dict):
                    s2_pdf_url = s2.get("oa_url", "")
                    if not arxiv_id:
                        arxiv_id = s2.get("arxiv_id", "")
                sources_tried.append({"source": "semanticscholar", "status": "ok"})
            else:
                sources_tried.append({
                    "source": "semanticscholar",
                    "status": s2_outcome.error_type or "error",
                    "reason": s2_outcome.error or "",
                })

        result = _download(doi, output_dir=output_dir, oa_url=oa_url,
                           s2_pdf_url=s2_pdf_url, arxiv_id=arxiv_id)
        if result["success"]:
            size_mb = result.get("size", 0) / (1024 * 1024)
            return _ok(
                success=True,
                path=result["path"],
                size_mb=round(size_mb, 1),
                source=result["source"],
                sources_tried=sources_tried,
            )
        return _ok(
            success=False,
            error=result.get("error", "No se encontró PDF gratuito."),
            sources_tried=sources_tried,
        )
    except Exception as e:
        return _error(str(e))


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Search & Citation MCP Server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio for IDE integration)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host for HTTP/SSE transport (default: 127.0.0.1)",
    )
    args, _ = parser.parse_known_args()
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
