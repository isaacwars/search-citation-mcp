"""Validación de entradas .bib con niveles de severidad y fuzzy matching."""

import re
from enum import Enum

from rapidfuzz import fuzz

from .protect import ACRONYMS, ACRONYM_RE

SIGLA_CON_LLAVES = re.compile(
    r'\{(' + '|'.join(re.escape(a) for a in sorted(ACRONYMS, key=len, reverse=True)) + r')\}'
)


class Status(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    NOT_FOUND = "not_found"


REQUIRED_FIELDS = {
    "article": ["author", "title", "journal", "year"],
    "inproceedings": ["author", "title", "booktitle", "year"],
    "book": ["author", "title", "publisher", "year"],
    "techreport": ["author", "title", "institution", "year"],
    "mastersthesis": ["author", "title", "school", "year"],
    "phdthesis": ["author", "title", "school", "year"],
    "manual": ["title"],
    "misc": [],
    "online": [],
    "incollection": ["author", "title", "booktitle", "publisher", "year"],
}


def _extract_bibtex_field(entry: str, field: str) -> str | None:
    """Extrae el valor de un campo BibTeX manejando llaves anidadas."""
    m = re.search(rf'\b{re.escape(field)}\s*=\s*', entry)
    if not m:
        return None
    start = m.end()
    while start < len(entry) and entry[start] in (' ', '\t'):
        start += 1
    if start >= len(entry) or entry[start] != '{':
        return None
    depth = 0
    i = start
    chars = []
    while i < len(entry):
        c = entry[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                break
        chars.append(c)
        i += 1
    return ''.join(chars[1:])


def strip_braces(text: str) -> str:
    """Elimina todas las llaves de protección BibTeX."""
    return text.replace("{", "").replace("}", "")


def check_bib_entry(entry_text: str) -> tuple:
    """Valida una entrada .bib. Retorna (Status, lista de issues)."""
    if len(entry_text) > 10_000:
        return Status.ERROR, ["La entrada excede el límite máximo de 10KB (posible error de input)."]

    issues = []

    if not entry_text.strip().startswith("@"):
        return Status.ERROR, ["La entrada debe empezar con @"]

    has_type = re.match(r'@([a-zA-Z]\w*)', entry_text.strip())
    if not has_type:
        return Status.ERROR, ["No se pudo detectar el entry type"]

    entry_type = has_type.group(1)
    worst = Status.OK

    if entry_type == "article" and not re.search(r'\bdoi\s*=', entry_text):
        issues.append("article con DOI debería incluir campo doi")
        worst = Status.WARNING

    title = _extract_bibtex_field(entry_text, "title")
    if title:
        cleaned = strip_braces(title)
        has_brace = SIGLA_CON_LLAVES.findall(title)
        siglas_protegidas = set(has_brace)
        all_siglas = set(ACRONYM_RE.findall(cleaned))
        for acro in all_siglas:
            if acro not in siglas_protegidas:
                issues.append(f"Sigla sin proteger: {acro} → debe ser {{{{{acro}}}}}")
                worst = Status.WARNING

        words = re.findall(r'\b[A-Z]{3,}\b', cleaned)
        for w in words:
            if w not in ACRONYMS:
                issues.append(f"Palabra en MAYÚSCULAS no reconocida como sigla: {w}")
                worst = Status.WARNING

        if any(kw in title.lower() for kw in ["datasheet", "ficha técnica", "analizador", "manual"]):
            if entry_type not in ["manual", "techreport"]:
                issues.append(f"La fuente parece ser técnica ({entry_type}), considera usar @manual o @techreport")
                worst = Status.WARNING

    needed = REQUIRED_FIELDS.get(entry_type, [])
    for field in needed:
        if not re.search(rf'\b{re.escape(field)}\s*=', entry_text):
            issues.append(f"Falta campo requerido para {entry_type}: {field}")
            worst = Status.ERROR

    return (worst if worst != Status.OK else Status.OK), issues


def fuzzy_verify(title: str, author: str, year, api_title: str, api_author: str = "", api_year=None) -> dict:
    """Compara título y autor contra fuente externa usando fuzzy matching.

    Returns dict con score, match y discrepancies.
    """
    title_score = fuzz.token_sort_ratio(
        title.lower().replace("{", "").replace("}", ""),
        (api_title or "").lower(),
    ) if api_title else 0

    author_score = 0
    author_last = author.split(",")[0].strip().lower().replace("{", "").replace("}", "") if author else ""
    api_last = api_author.split(",")[0].strip().lower() if api_author else ""
    if author_last and api_last:
        author_score = fuzz.ratio(author_last, api_last) if api_last else 0

    year_match = True
    if year and api_year:
        try:
            year_match = abs(int(year) - int(api_year)) <= 1
        except (ValueError, TypeError):
            year_match = True

    overall = (title_score * 0.6 + author_score * 0.3 + (100 if year_match else 0) * 0.1)

    status = Status.OK if overall >= 85 else (Status.WARNING if overall >= 60 else Status.ERROR)

    discrepancies = []
    if title_score < 85:
        discrepancies.append(f"Título difiere ({title_score}%)")
    if author_score < 70:
        discrepancies.append(f"Primer autor difiere ({author_score}%)")
    if not year_match:
        discrepancies.append(f"Año difiere: bib={year}, api={api_year}")

    return {
        "status": status.value,
        "confidence": round(overall, 1),
        "title_score": title_score,
        "author_score": author_score,
        "year_match": year_match,
        "discrepancies": discrepancies,
    }


def validate_after_append(result_key: str, entry_text: str) -> dict:
    """Valida una entrada después de agregarla."""
    status, issues = check_bib_entry(entry_text)
    return {
        "status": status.value,
        "key": result_key,
        "warnings": issues,
    }
