"""Corrector de archivos .bib: Title Case, protección de siglas, datasheets."""

import re
from pathlib import Path

from .protect import protect

FIXED_ACRONYMS = {
    "CFE", "IEC", "IEEE", "DOF", "NOM", "BUAP", "SFVI", "CRE", "SENER",
    "LTE", "CEC", "IEA", "PLADESE", "PLOS", "IET", "PVSyst", "PV",
    "DC", "AC", "MPPT", "THD", "PVC", "SCADA", "PLC", "DSP", "FPGA",
    "IGBT", "MOSFET", "MATLAB", "NASA", "SSE", "IPN", "UNAM",
}

CORPORATE_NAMES = {
    "Comisión Federal de Electricidad", "Gobierno de México",
    "Secretaría de Energía", "Secretaría de Gobernación",
    "Comisión Reguladora de Energía", "Comisión Nacional de Energía",
    "International Electrotechnical Commission", "International Energy Agency",
    "Hioki E.E. Corporation", "MathWorks, Inc.", "PVsyst SA",
    "National Technology and Engineering Solutions of Sandia, LLC",
    "ENF Solar", "Presidencia de la República",
}

MONTH_NAMES = {
    "jan": "1", "january": "1", "ene": "1", "enero": "1",
    "feb": "2", "february": "2", "febrero": "2",
    "mar": "3", "march": "3", "marzo": "3",
    "apr": "4", "april": "4", "abr": "4", "abril": "4",
    "may": "5", "mayo": "5",
    "jun": "6", "june": "6", "junio": "6",
    "jul": "7", "july": "7", "julio": "7",
    "aug": "8", "august": "8", "ago": "8", "agosto": "8",
    "sep": "9", "september": "9", "septiembre": "9",
    "oct": "10", "october": "10", "octubre": "10",
    "nov": "11", "november": "11", "noviembre": "11",
    "dec": "12", "december": "12", "dic": "12", "diciembre": "12",
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
    if not path.exists():
        raise FileNotFoundError(f"No se encontró: {bib_path}")

    content = path.read_text(encoding="utf-8")
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
        backup = path.with_suffix(".bib.bak")
        path.rename(backup)
        path.write_text(output, encoding="utf-8")

    return {"fixed": fixed, "unchanged": unchanged, "errors": errors, "output": output, "backup": str(path.with_suffix(".bib.bak")) if not dry_run else None}


def _split_entries(content: str) -> list:
    entries = []
    current = []
    depth = 0
    for line in content.split("\n"):
        if line.strip().startswith("@") and depth == 0:
            if current:
                entries.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
        depth += line.count("{") - line.count("}")
    if current:
        entries.append("\n".join(current))
    return entries


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
        month_lower = month_val.lower()
        if month_lower in MONTH_NAMES:
            return f"month = {{{MONTH_NAMES[month_lower]}}}"
        return m.group(0)
    return re.sub(r'month\s*=\s*\{([^}]+)\}', _replace, entry)


def _fix_title(entry: str) -> str:
    def _replace_field(m):
        field = m.group(1)
        value = m.group(2)
        if value.isupper():
            clean = _to_title_case(value)
            return f"{field} = {{{clean}}}"
        return m.group(0)
    return re.sub(r'(title|booktitle|journal)\s*=\s*\{([^}]+)\}', _replace_field, entry)


def _to_title_case(text: str) -> str:
    small_words = {"a", "an", "the", "and", "but", "or", "for", "nor", "on",
                   "at", "to", "by", "in", "of", "with", "de", "la", "el", "los",
                   "las", "del", "en", "un", "una", "y", "e", "o", "que", "por",
                   "para", "con", "sin", "su", "al", "se", "no", "es"}
    words = re.findall(r'\S+', text)
    result = []
    for i, w in enumerate(words):
        if w.upper() in FIXED_ACRONYMS:
            result.append(w.upper())
        elif i == 0 or i == len(words) - 1 or w.lower() not in small_words:
            result.append(w[0].upper() + w[1:].lower() if len(w) > 1 else w.upper())
        else:
            result.append(w.lower())
    return " ".join(result)


def _protect_acronyms(entry: str) -> str:
    for acro in sorted(FIXED_ACRONYMS, key=len, reverse=True):
        pattern = r'(?<!\{)' + re.escape(acro) + r'(?!\})'
        entry = re.sub(
            pattern,
            lambda m: '{' + m.group(0) + '}',
            entry
        )
    return entry


def _fix_corporate_authors(entry: str) -> str:
    for corp in CORPORATE_NAMES:
        if corp.lower() in entry.lower():
            entry = re.sub(
                rf'([\s=])\{{{{{{{re.escape(corp)}\}}}}}}\}}',
                rf'\1{{{{{corp}}}}}',
                entry,
                flags=re.IGNORECASE,
            )
            if f"{{{corp}}}" not in entry:
                entry = re.sub(
                    rf'author\s*=\s*\{{{{?{re.escape(corp)}[}}]}}*',
                    f'author = {{{{{{{corp}}}}}}}',
                    entry,
                    flags=re.IGNORECASE,
                )
    return entry


def _add_datasheet_note(entry: str) -> str:
    is_manual = re.match(r'@manual', entry.strip(), re.IGNORECASE)
    if not is_manual:
        return entry

    title_match = re.search(r'title\s*=\s*\{(.+?)\}', entry, re.DOTALL)
    title_text = title_match.group(1) if title_match else ""

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
