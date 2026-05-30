"""Corrector de archivos .bib: Title Case, protección de siglas, datasheets."""

import re
import tempfile
from datetime import datetime
from pathlib import Path

from .protect import ACRONYMS as FIXED_ACRONYMS
from .bibliography import _split_entries
from .style import abbr_month

CORPORATE_NAMES = {
    "Comisión Federal de Electricidad", "Gobierno de México",
    "Secretaría de Energía", "Secretaría de Gobernación",
    "Comisión Reguladora de Energía", "Comisión Nacional de Energía",
    "International Electrotechnical Commission", "International Energy Agency",
    "Hioki E.E. Corporation", "MathWorks, Inc.", "PVsyst SA",
    "National Technology and Engineering Solutions of Sandia, LLC",
    "ENF Solar", "Presidencia de la República",
}

DATASHEET_KEYWORDS = [
    "analizador", "inversor", "panel solar", "módulo fotovoltaico",
    "datasheet", "ficha técnica", "specification", "application note",
    "manual de usuario", "manual de instalación",
]


def fix_bib_file(bib_path: str, dry_run: bool = False) -> dict:
    """Corrige un archivo .bib: Title Case, siglas, datasheets.

    Returns: {"fixed": N, "unchanged": N, "errors": [...], "output": str}
    """
    path = Path(bib_path)
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        try:
            content = path.read_text(encoding="latin-1")
        except (FileNotFoundError, UnicodeDecodeError):
            raise FileNotFoundError(f"No se encontró o encoding inválido: {bib_path}")
    entries = _split_entries(content)
    fixed = 0
    unchanged = 0
    errors = []
    output_entries = []

    for entry in entries:
        try:
            new_entry = _fix_entry(entry)
            if new_entry != entry:
                fixed += 1
            else:
                unchanged += 1
            output_entries.append(new_entry)
        except Exception as e:
            errors.append(str(e))
            output_entries.append(entry)

    output = "\n\n".join(output_entries) + "\n"

    if not dry_run:
        backup = path.with_suffix(f".bib.{datetime.now().strftime('%Y%m%d%H%M%S%f')}.bak")
        path.rename(backup)
        try:
            path.write_text(output, encoding="utf-8")
        except Exception:
            backup.rename(path)
            raise

    return {"fixed": fixed, "unchanged": unchanged, "errors": errors, "output": output, "backup": str(backup) if not dry_run else None}


def _fix_entry(entry: str) -> str:
    entry = _fix_month(entry)
    entry = _fix_title(entry)
    entry = _protect_acronyms(entry)
    entry = _fix_corporate_authors(entry)
    entry = _add_datasheet_note(entry)
    return entry


def _fix_month(entry: str) -> str:
    def _replace(m):
        month_val = m.group(1)
        return f"month = {{{abbr_month(month_val)}}}"
    return re.sub(r'month\s*=\s*\{([^}]+)\}', _replace, entry)


def _extract_braced_content(text: str, start: int) -> str:
    """Extrae el contenido entre llaves balanceadas desde start (justo después del '{')."""
    depth = 0
    chars = []
    for c in text[start:]:
        if c == '{':
            depth += 1
            chars.append(c)
        elif c == '}':
            if depth == 0:
                break
            depth -= 1
            chars.append(c)
        else:
            chars.append(c)
    return ''.join(chars)


def _fix_title(entry: str) -> str:
    for pattern in (r'title\s*=\s*\{', r'booktitle\s*=\s*\{', r'journal\s*=\s*\{'):
        m = re.search(pattern, entry)
        if not m:
            continue
        value = _extract_braced_content(entry, m.end())
        if not value:
            continue
        clean = _to_title_case(value)
        brace_open = m.end() - 1
        brace_close = m.end() + len(value)
        entry = entry[:brace_open] + f"{{{clean}}}" + entry[brace_close + 1:]
    return entry


def _to_title_case(text: str) -> str:
    small_words = {"a", "an", "the", "and", "but", "or", "for", "nor", "on",
                   "at", "to", "by", "in", "of", "with", "de", "la", "el", "los",
                   "las", "del", "en", "un", "una", "y", "e", "o", "que", "por",
                   "para", "con", "sin", "su", "al", "se", "no", "es"}
    words = re.findall(r'\S+', text)
    result = []
    for i, w in enumerate(words):
        stripped = w.strip('{}')
        if stripped.upper() in FIXED_ACRONYMS:
            result.append(w.replace(stripped, stripped.upper()))
        elif i == 0 or i == len(words) - 1 or w.lower().strip('{}') not in small_words:
            result.append(w[0].upper() + w[1:].lower() if len(w) > 1 else w.upper())
        else:
            result.append(w.lower())
    return " ".join(result)


def _protect_acronyms(entry: str) -> str:
    for field in ("title", "booktitle", "journal"):
        m = re.search(rf'{field}\s*=\s*\{{', entry)
        if not m:
            continue
        value = _extract_braced_content(entry, m.end())
        if not value:
            continue
        protected = value
        for acro in sorted(FIXED_ACRONYMS, key=len, reverse=True):
            pattern = r'(?<![{}\w])' + re.escape(acro) + r'(?![{}\w])'
            protected = re.sub(pattern, lambda m_: '{' + m_.group(0) + '}', protected)
        if protected != value:
            brace_open = m.end() - 1
            brace_close = m.end() + len(value)
            entry = entry[:brace_open + 1] + protected + entry[brace_close:]
    return entry


def _fix_corporate_authors(entry: str) -> str:
    for corp in CORPORATE_NAMES:
        if corp.lower() not in entry.lower():
            continue
        escaped = re.escape(corp)
        if f"{{{corp}}}" in entry:
            continue
        entry = re.sub(
            rf'author\s*=\s*\{{+{escaped}\}}+',
            f'author = {{{{{corp}}}}}',
            entry,
            count=1,
            flags=re.IGNORECASE,
        )
        if f"{{{corp}}}" not in entry:
            entry = re.sub(
                rf'(author\s*=\s*)\{{{{?{escaped}',
                rf'\1{{{{{corp}}}',
                entry,
                count=1,
                flags=re.IGNORECASE,
            )
    return entry


def _add_datasheet_note(entry: str) -> str:
    is_manual = re.match(r'@manual', entry.strip(), re.IGNORECASE)
    if not is_manual:
        return entry

    title_match = re.search(r'title\s*=\s*\{', entry)
    title_text = _extract_braced_content(entry, title_match.end()) if title_match else ""

    has_note = re.search(r'\bnote\s*=', entry)
    if has_note:
        return entry

    combined = (title_text + " " + entry).lower()
    if any(kw in combined for kw in DATASHEET_KEYWORDS):
        return re.sub(
            r'(}\s*)$',
            r'\n    note = {Datasheet},\1',
            entry,
            count=1,
        )

    return entry
