#!/usr/bin/env python3
"""CLI del Search & Citation Engine.

Uso:
  search-citation search "armónicos SFVI México" -n 5
  search-citation search "armónicos" --year 2020-2025 --no-preprints
  search-citation add --doi 10.1016/j.rser.2015.08.042
  search-citation add --type manual --title "PQ3100" --author "{Hioki}" --year 2024
  search-citation cite --doi 10.1016/j.rser.2015.08.042
  search-citation related 10.1016/j.rser.2015.08.042
  search-citation detect "10.1016/j.rser.2015.08.042"
  search-citation validate bibliografia.bib
  search-citation fix-bib bibliografia.bib
  search-citation fix-bib bibliografia.bib --dry-run
  search-citation cache
"""

import argparse
import json
import sys

from dotenv import load_dotenv

load_dotenv()

from . import search as search_module
from .generate import from_doi, from_crossref_data, from_fields
from .bibliography import append_entry
from .apis import openalex, semanticscholar


def cmd_search(args: argparse.Namespace):
    try:
        yf, yt = None, None
        if args.year:
            parts = args.year.split("-")
            if len(parts) == 2:
                if parts[0]:
                    try:
                        yf = int(parts[0])
                    except ValueError:
                        pass
                if parts[1]:
                    try:
                        yt = int(parts[1])
                    except ValueError:
                        pass
        results = search_module.search_papers(
            args.query, count=args.n,
            year_from=yf, year_to=yt,
            exclude_preprints=args.no_preprints,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_add(args: argparse.Namespace):
    if args.doi:
        result = search_module.add_from_doi(args.doi)
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)
        print(f"✔ Cita agregada. Usa \\cite{{{result['key']}}} en tu texto.")
        print(f"  Fuente: {result['source']} (confianza: {result['confidence']})")
        if result.get("corrected_doi"):
            print(f"  DOI corregido: {result['original_doi']} → {result['corrected_doi']}")
        if result.get("warning"):
            print(f"  ⚠ {result['warning']}")
        if result.get("validation", {}).get("warnings"):
            for w in result["validation"]["warnings"]:
                print(f"  - {w}")
    elif args.type:
        raw = {k: v for k, v in vars(args).items()
               if v is not None and k not in ("func", "type", "doi", "command", "fields")}
        entry = from_fields(args.type, raw)
        try:
            key = append_entry(entry)
            print(f"✔ Agregado a bibliografia.bib")
            print(f"  Usa \\cite{{{key}}} en tu texto.")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        print("Usa --doi o --type + campos")
        sys.exit(1)


def cmd_cite(args: argparse.Namespace):
    if args.doi:
        enriched = search_module.enrich_paper(args.doi)
        if not enriched:
            print(f"Error: No se encontró el DOI {args.doi}")
            sys.exit(1)
        source = enriched.get("_source", "unknown")
        if source == "crossref":
            entry = from_crossref_data(enriched)
        elif source in ("openalex", "semanticscholar"):
            if source == "semanticscholar":
                entry = from_fields("article", {
                    "author": " and ".join(
                        f"{parts[-1]}, {parts[0][0]}."
                        if " " in a else a
                        for a in enriched.get("authors", [])
                        if a and a.strip()
                        for parts in [a.split()]
                    ),
                    "title": enriched.get("title", "").strip().rstrip("."),
                    "journal": enriched.get("journal", ""),
                    "year": str(enriched.get("year", "")),
                    "doi": enriched.get("doi", ""),
                    "url": enriched.get("url", ""),
                })
            else:
                entry = from_doi(args.doi, enriched["raw_oa"] if "raw_oa" in enriched else enriched.get("raw", {}))
        else:
            print(f"Error: fuente no reconocida: {source}")
            sys.exit(1)
        print(entry)
        if enriched.get("_warning"):
            print(f"# ⚠ {enriched['_warning']}")
    elif args.type:
        raw = {k: v for k, v in vars(args).items()
               if v is not None and k not in ("func", "type", "doi", "command")}
        entry = from_fields(args.type, raw)
        print(entry)
    else:
        print("Usa --doi o --type + campos")
        sys.exit(1)


def cmd_related(args: argparse.Namespace):
    try:
        results = search_module.find_related_papers(
            args.doi, count=args.n, exclude_preprints=args.no_preprints,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_detect(args: argparse.Namespace):
    try:
        from .detect import detect_input
        result = detect_input(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_validate(args: argparse.Namespace):
    from .report import generate_validation_report
    try:
        report_path = generate_validation_report(args.bib_path)
        print(f"✔ Reporte generado: {report_path}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_fix_bib(args: argparse.Namespace):
    from .fixer import fix_bib_file
    try:
        result = fix_bib_file(args.bib_path, dry_run=args.dry_run)
        print(f"✔ Corregido: {result['fixed']} modificadas, {result['unchanged']} sin cambios.")
        if result["errors"]:
            print(f"  Errores: {len(result['errors'])}")
        if result["backup"]:
            print(f"  Backup: {result['backup']}")
        if args.dry_run:
            print("\n--dry-run: no se escribió el archivo.")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_cache(args: argparse.Namespace):
    try:
        results = search_module.list_cached()
        if not results:
            print("No hay búsquedas en caché.")
            return
        for c in results:
            print(f"  \"{c['query']}\" — {c['count']} papers")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_download(args: argparse.Namespace):
    try:
        from .access.download import download_paper as _download

        oa_url = ""
        s2_pdf_url = ""
        arxiv_id = ""

        oa = openalex.fetch_by_doi(args.doi)
        if oa:
            oa_url = oa.get("oa_url", "")
            arxiv_id = oa.get("raw", {}).get("ids", {}).get("arxiv", "")

        s2 = semanticscholar.fetch_by_doi(args.doi)
        if s2:
            s2_pdf_url = s2.get("oa_url", "")
            if not arxiv_id:
                arxiv_id = s2.get("arxiv_id", "")

        result = _download(args.doi, output_dir=args.output_dir,
                           oa_url=oa_url, s2_pdf_url=s2_pdf_url, arxiv_id=arxiv_id)
        if result["success"]:
            size_mb = result.get("size", 0) / (1024 * 1024)
            print(f"PDF descargado: {result['path']} ({size_mb:.1f} MB, fuente: {result['source']})")
        else:
            print(f"Error: {result.get('error', 'No se encontró PDF gratuito.')}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Search & Citation Engine CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  search-citation search "armónicos SFVI" -n 5
  search-citation search "SFVI" --year 2020-2025 --no-preprints
  search-citation add --doi 10.1016/j.rser.2015.08.042
  search-citation cite --doi 10.1016/j.rser.2015.08.042
  search-citation related 10.1016/j.rser.2015.08.042 -n 5
  search-citation detect "10.1016/j.rser.2015.08.042"
  search-citation validate bibliografia.bib
  search-citation fix-bib bibliografia.bib
  search-citation download 10.1016/j.rser.2015.08.042
  search-citation download 10.1016/j.rser.2015.08.042 -o ./pdfs
  search-citation cache
""",
    )
    sub = parser.add_subparsers(dest="command")

    p_search = sub.add_parser("search", help="Buscar papers")
    p_search.add_argument("query", help="Términos de búsqueda")
    p_search.add_argument("-n", type=int, default=10, help="Número de resultados")
    p_search.add_argument("--year", help="Filtro de año: 2020-2025, 2020-, -2020")
    p_search.add_argument("--no-preprints", action="store_true", help="Excluir preprints")

    p_add = sub.add_parser("add", help="Agregar cita a bibliografia.bib")
    p_add.add_argument("--doi", help="DOI del paper")
    p_add.add_argument("--type", help="Entry type: article, techreport, manual, etc.")
    p_add.add_argument("--key", help="Citation key personalizada")
    p_add.add_argument("--author", help="Autor(es)")
    p_add.add_argument("--title", help="Título")
    p_add.add_argument("--journal", help="Journal (article)")
    p_add.add_argument("--booktitle", help="Conferencia/libro (inproceedings)")
    p_add.add_argument("--year", help="Año")
    p_add.add_argument("--volume", help="Volumen")
    p_add.add_argument("--number", help="Número")
    p_add.add_argument("--pages", help="Páginas")
    p_add.add_argument("--month", help="Mes (1-12)")
    p_add.add_argument("--doi_field", dest="doi", help="DOI")
    p_add.add_argument("--url", help="URL")
    p_add.add_argument("--institution", help="Institución (techreport)")
    p_add.add_argument("--school", help="Escuela (thesis)")
    p_add.add_argument("--publisher", help="Editorial (book)")
    p_add.add_argument("--address", help="Ciudad/Lugar")
    p_add.add_argument("--edition", help="Edición")
    p_add.add_argument("--isbn", help="ISBN")
    p_add.add_argument("--howpublished", help="Medio (misc)")
    p_add.add_argument("--note", help="Nota adicional")
    p_add.add_argument("--organization", help="Organización")

    p_cite = sub.add_parser("cite", help="Generar .bib sin escribir")
    p_cite.add_argument("--doi", help="DOI del paper")
    p_cite.add_argument("--type", help="Entry type")
    p_cite.add_argument("--key", help="Citation key")
    p_cite.add_argument("--author")
    p_cite.add_argument("--title")
    p_cite.add_argument("--journal")
    p_cite.add_argument("--booktitle")
    p_cite.add_argument("--year")
    p_cite.add_argument("--volume")
    p_cite.add_argument("--number")
    p_cite.add_argument("--pages")
    p_cite.add_argument("--month")
    p_cite.add_argument("--url")
    p_cite.add_argument("--doi_field", dest="doi")
    p_cite.add_argument("--institution")
    p_cite.add_argument("--school")
    p_cite.add_argument("--publisher")
    p_cite.add_argument("--address")
    p_cite.add_argument("--edition")
    p_cite.add_argument("--isbn")
    p_cite.add_argument("--howpublished")
    p_cite.add_argument("--note")
    p_cite.add_argument("--organization")

    p_related = sub.add_parser("related", help="Buscar papers relacionados")
    p_related.add_argument("doi", help="DOI del paper de referencia")
    p_related.add_argument("-n", type=int, default=5, help="Número de resultados")
    p_related.add_argument("--no-preprints", action="store_true")

    p_detect = sub.add_parser("detect", help="Detectar tipo de entrada")
    p_detect.add_argument("text", help="Texto a analizar")

    p_validate = sub.add_parser("validate", help="Validar archivo .bib")
    p_validate.add_argument("bib_path", help="Ruta al .bib")

    p_fix = sub.add_parser("fix-bib", help="Corregir .bib (Title Case, siglas, datasheets)")
    p_fix.add_argument("bib_path", help="Ruta al .bib")
    p_fix.add_argument("--dry-run", action="store_true", help="Solo mostrar cambios")

    p_cache = sub.add_parser("cache", help="Listar búsquedas en caché")

    p_download = sub.add_parser("download", help="Descargar PDF de un paper")
    p_download.add_argument("doi", help="DOI del paper")
    p_download.add_argument("-o", "--output-dir", default="./papers", help="Directorio de descarga")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "search": cmd_search,
        "add": cmd_add,
        "cite": cmd_cite,
        "related": cmd_related,
        "detect": cmd_detect,
        "validate": cmd_validate,
        "fix-bib": cmd_fix_bib,
        "download": cmd_download,
        "cache": cmd_cache,
    }
    try:
        cmd_map[args.command](args)
    except KeyError:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
