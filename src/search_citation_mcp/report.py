"""Generación de reportes Markdown para validación de archivos .bib."""

from pathlib import Path

from .validate import Status, check_bib_entry
from .bibliography import _split_entries


def generate_validation_report(bib_path: str) -> str:
    """Valida un archivo .bib completo y genera reporte Markdown.

    Returns: ruta al archivo .report.md generado.
    """
    path = Path(bib_path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró: {bib_path}")

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")
    entries = _split_entries(content)

    results = []
    for i, entry in enumerate(entries):
        status, issues = check_bib_entry(entry)
        key = ""
        import re
        key_match = re.match(r'@\w+\{(\w+),', entry)
        if key_match:
            key = key_match.group(1)
        results.append({"index": i + 1, "key": key, "status": status, "issues": issues, "entry": entry})

    ok_count = sum(1 for r in results if r["status"] == Status.OK)
    warn_count = sum(1 for r in results if r["status"] == Status.WARNING)
    err_count = sum(1 for r in results if r["status"] == Status.ERROR)
    nf_count = sum(1 for r in results if r["status"] == Status.NOT_FOUND)

    lines = [
        f"# Reporte de Validación de Referencias",
        f"",
        f"> Archivo: `{path.name}`  —  {len(results)} entradas",
        f"",
        f"## Resumen",
        f"",
        f"| Estado | Cantidad |",
        f"|---|---|",
        f"| ✅ OK | {ok_count} |",
        f"| ⚠️ WARNING | {warn_count} |",
        f"| ❌ ERROR | {err_count} |",
        f"| 🔍 NOT_FOUND | {nf_count} |",
        f"",
    ]

    if err_count:
        lines.append("## ❌ ERRORES")
        lines.append("")
        for r in results:
            if r["status"] == Status.ERROR:
                label = r['key'] or f"Entrada {r['index']}"
                lines.append(f"### {label}")
                for issue in r["issues"]:
                    lines.append(f"- {issue}")
                lines.append("")

    if warn_count:
        lines.append("## ⚠️ ADVERTENCIAS")
        lines.append("")
        for r in results:
            if r["status"] == Status.WARNING:
                label = r['key'] or f"Entrada {r['index']}"
                lines.append(f"### {label}")
                for issue in r["issues"]:
                    lines.append(f"- {issue}")
                lines.append("")

    report_text = "\n".join(lines)
    report_path = path.with_suffix(".report.md")
    try:
        report_path.write_text(report_text, encoding="utf-8")
    except OSError as e:
        raise OSError(f"No se pudo escribir el reporte: {e}")
    return str(report_path)
