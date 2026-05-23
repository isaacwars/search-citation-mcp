"""Search & Citation MCP Server — 9 tools para búsqueda y citación IEEE."""

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
from .apis import openalex, semanticscholar
from .access.download import download_paper as _download

mcp = FastMCP("search-citation")

# Campos que se incluyen en los resultados de búsqueda (eficiencia de tokens)
_SEARCH_FIELDS = (
    "title", "doi", "authors", "year", "abstract", "journal",
    "url", "oa_url", "is_oa", "is_preprint", "source",
)


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
def search_papers(query: str, n: int = 10, year_from: int = 0,
                  year_to: int = 0, exclude_preprints: bool = False) -> str:
    """Busca papers académicos por palabras clave.

    Usa OpenAlex como buscador principal y Semantic Scholar (si hay API key)
    para búsqueda semántica en paralelo.

    Args:
        query: términos de búsqueda (ej: "armónicos SFVI México")
        n: número máximo de resultados (default 10)
        year_from: año inicio del filtro (0 = sin filtro)
        year_to: año fin del filtro (0 = sin filtro)
        exclude_preprints: excluir preprints de los resultados
    """
    yf = year_from if year_from > 0 else None
    yt = year_to if year_to > 0 else None
    results = search_module.search_papers(
        query, count=n, year_from=yf, year_to=yt,
        exclude_preprints=exclude_preprints,
    )
    clean = [
        {k: v for k, v in r.items() if k in _SEARCH_FIELDS and v}
        for r in results[:n]
    ]
    return json.dumps(clean, ensure_ascii=False, indent=2)


@mcp.tool()
def add_from_doi(doi: str) -> str:
    """Cita un paper por DOI con fuente autoritativa y lo agrega a la bibliografía.

    Pipeline: Crossref → Semantic Scholar → OpenAlex.
    Usa una sola fuente por cita, sin mezclar datos.
    Si OpenAlex tiene un DOI incorrecto, busca el correcto en Crossref.
    Si el paper es preprint, intenta encontrar la versión publicada.

    Args:
        doi: DOI del paper (ej: 10.1016/j.rser.2015.08.042)
    """
    result = search_module.add_from_doi(doi)
    if "error" in result:
        return json.dumps({"error": result["error"]}, ensure_ascii=False)
    out = {
        "key": result["key"],
        "source": result["source"],
        "confidence": result["confidence"],
    }
    if result.get("corrected_doi"):
        out["corrected_doi"] = result["corrected_doi"]
        out["original_doi"] = result["original_doi"]
    if result.get("warning"):
        out["warning"] = result["warning"]
    if result.get("validation", {}).get("warnings"):
        out["validation"] = result["validation"]
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
def cite_paper(type: str, **campos) -> str:
    """Genera una entrada .bib validada sin escribirla al archivo.

    Usar para fuentes SIN DOI: CFE, NOM, IEC, leyes, tesis, datasheets.

    Args:
        type: article | inproceedings | book | techreport | mastersthesis |
              phdthesis | manual | misc | online | incollection
        **campos: author, title, journal/booktitle, year, doi, url, etc.
    """
    try:
        entry = from_fields(type, campos)
        return json.dumps({"entry": entry}, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def add_to_bibliography(type: str, **campos) -> str:
    """Genera entrada .bib validada y la agrega a bibliografia.bib.

    Para fuentes SIN DOI: CFE, NOM, IEC, leyes, tesis, datasheets.

    Args:
        type: entry type BibTeX
        **campos: author, title, journal/booktitle, year, etc.
    """
    try:
        entry = from_fields(type, campos)
        key = append_entry(entry)
        val = validate_after_append(key, entry)
        out = {"key": key}
        if val["warnings"]:
            out["validation"] = val
        return json.dumps(out, ensure_ascii=False, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


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
    results = search_module.find_related_papers(
        doi, count=n, exclude_preprints=exclude_preprints,
    )
    return json.dumps(results, ensure_ascii=False, indent=2)


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
        return json.dumps({"cached": []}, ensure_ascii=False)
    return json.dumps({"cached": results}, ensure_ascii=False, indent=2)


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
        return json.dumps({
            "fixed": result["fixed"],
            "unchanged": result["unchanged"],
            "errors": result.get("errors", []),
            "backup": result.get("backup", ""),
            "dry_run": dry_run,
        }, ensure_ascii=False, indent=2)
    except (ValueError, FileNotFoundError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


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
    oa_url = ""
    s2_pdf_url = ""
    arxiv_id = ""

    oa = openalex.fetch_by_doi(doi)
    if oa:
        oa_url = oa.get("oa_url", "")
        raw = oa.get("raw", {})
        arxiv_id = raw.get("ids", {}).get("arxiv", "")

    s2 = semanticscholar.fetch_by_doi(doi)
    if s2:
        s2_pdf_url = s2.get("oa_url", "")
        if not arxiv_id:
            arxiv_id = s2.get("arxiv_id", "")

    result = _download(doi, output_dir=output_dir, oa_url=oa_url,
                       s2_pdf_url=s2_pdf_url, arxiv_id=arxiv_id)
    if result["success"]:
        size_mb = result.get("size", 0) / (1024 * 1024)
        return json.dumps({
            "success": True,
            "path": result["path"],
            "size_mb": round(size_mb, 1),
            "source": result["source"],
        }, ensure_ascii=False, indent=2)
    return json.dumps({
        "success": False,
        "error": result.get("error", "No se encontró PDF gratuito."),
    }, ensure_ascii=False)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
