"""Validación de entradas .bib con niveles de severidad y fuzzy matching."""

import re
from collections import Counter
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


def check_doi_resolves(doi: str) -> dict:
    """Verifica si un DOI resuelve en al menos una fuente académica.

    Prueba Crossref → OpenAlex → Semantic Scholar.
    Retorna dict con resolved (bool) y warnings.
    """
    from .apis import crossref, openalex, semanticscholar, scielo
    from .apis.outcomes import SourceOutcome

    sources = []
    warnings = []

    def _ok(outcome):
        if isinstance(outcome, SourceOutcome):
            return outcome.is_success and outcome.data and outcome.data.get("title")
        return bool(outcome and outcome.get("title"))

    if _ok(crossref.fetch_by_doi(doi)):
        sources.append("crossref")
    if _ok(openalex.fetch_by_doi(doi)):
        sources.append("openalex")
    if _ok(semanticscholar.fetch_by_doi(doi)):
        sources.append("semanticscholar")
    if _ok(scielo.fetch_by_doi(doi)):
        sources.append("scielo")

    if not sources:
        warnings.append(
            f"DOI huérfano: {doi} no resuelve en Crossref, OpenAlex, Semantic Scholar ni SciELO"
        )

    return {
        "doi": doi,
        "resolved": bool(sources),
        "sources": sources,
        "warnings": warnings,
    }


def cross_verify_doi(doi: str) -> dict:
    """Verificación cruzada entre 3 fuentes con majority voting.

    Pipeline:
    1. Fetch metadata de Crossref, OpenAlex, Semantic Scholar, SciELO en paralelo
    2. Comparar author + title + year entre las fuentes
    3. Majority voting: si 2 coinciden, usa mayoría
    4. Si empate o todas difieren → warning
    5. Si solo 1 fuente disponible → sin warning (no hay con qué comparar)

    Returns dict con best_data, warnings, source_used.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .apis import crossref, openalex, semanticscholar, scielo
    from .apis.outcomes import SourceOutcome

    api_funcs = {
        "crossref": crossref.fetch_by_doi,
        "openalex": openalex.fetch_by_doi,
        "semanticscholar": semanticscholar.fetch_by_doi,
        "scielo": scielo.fetch_by_doi,
    }

    raw_data = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(func, doi): name for name, func in api_funcs.items()}
        for future in as_completed(futures, timeout=20):
            name = futures[future]
            try:
                outcome = future.result()
                if isinstance(outcome, SourceOutcome):
                    raw_data[name] = outcome.data if outcome.is_success and outcome.data else {}
                else:
                    raw_data[name] = outcome or {}
            except Exception:
                raw_data[name] = {}

    sources = []
    for name in ("crossref", "openalex", "semanticscholar", "scielo"):
        d = raw_data.get(name, {})
        if d and d.get("title"):
            sources.append((name, _extract_comparable(d)))

    if not sources:
        return {"best_source": "", "best_data": {}, "warnings": ["DOI sin resolver en ninguna fuente"], "compared": 0, "raw_data": raw_data}

    if len(sources) < 2:
        src = sources[0][0]
        return {
            "best_source": src,
            "best_data": raw_data.get(src, {}),
            "warnings": [],
            "compared": 1,
            "raw_data": raw_data,
        }

    sigs = [_make_sig(s[1]) for s in sources]

    if len(set(sigs)) == 1:
        return {
            "best_source": sources[0][0],
            "best_data": raw_data.get(sources[0][0], {}),
            "warnings": [],
            "compared": len(sources),
            "raw_data": raw_data,
        }

    counts = Counter(sigs)
    most_common_sig, count = counts.most_common(1)[0]

    warnings = []
    if count >= 2:
        best_idx = sigs.index(most_common_sig)
        best_source = sources[best_idx][0]
        for i, src in enumerate(sources):
            if sigs[i] != most_common_sig:
                warnings.append(
                    f"Discrepancia: {src[0]} difiere de mayoría "
                    f"({best_source}, {count}/{len(sources)} votos)"
                )
        return {
            "best_source": best_source,
            "best_data": raw_data.get(best_source, {}),
            "warnings": warnings,
            "compared": len(sources),
            "raw_data": raw_data,
        }

    warnings.append(
        "Verificación cruzada: todas las fuentes difieren. Revisar manualmente."
    )
    return {
        "best_source": sources[0][0],
        "best_data": raw_data.get(sources[0][0], {}),
        "warnings": warnings,
        "compared": len(sources),
        "raw_data": raw_data,
    }


def _extract_comparable(data: dict) -> dict:
    """Extrae campos comparables de metadata de una fuente."""
    authors = data.get("authors", [])
    first_author = authors[0] if authors else ""
    if isinstance(first_author, str):
        if "," in first_author:
            first_author = first_author.split(",")[0].strip()
        elif " " in first_author:
            first_author = first_author.rsplit(" ", 1)[-1].strip()

    return {
        "first_author": first_author.lower(),
        "title": (data.get("title") or "").lower().strip().rstrip("."),
        "year": str(data.get("year") or ""),
    }


def _make_sig(comparable: dict) -> str:
    """Crea una firma comparable: autor|título|año."""
    return f"{comparable['first_author']}|{comparable['title']}|{comparable['year']}"
