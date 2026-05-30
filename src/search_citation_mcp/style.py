"""Formato de autores y meses para BibTeX IEEE."""

_MONTH_MAP = {
    "jan": "1", "january": "1", "ene": "1", "enero": "1",
    "feb": "2", "february": "2", "febrero": "2",
    "mar": "3", "march": "3", "marzo": "3",
    "apr": "4", "april": "4", "abr": "4", "abril": "4",
    "may": "5", "mayo": "5",
    "jun": "6", "june": "6", "junio": "6",
    "jul": "7", "july": "7", "julio": "7",
    "aug": "8", "august": "8", "ago": "8", "agosto": "8",
    "sep": "9", "september": "9", "set": "9", "septiembre": "9",
    "oct": "10", "october": "10", "octubre": "10",
    "nov": "11", "november": "11", "noviembre": "11",
    "dec": "12", "december": "12", "dic": "12", "diciembre": "12",
}


def author_to_ieee(raw: str) -> str:
    """Convierte 'Apellido, Nombre' a iniciales IEEE: 'N. Apellido'."""
    parts = raw.split(",", 1)
    if len(parts) != 2:
        return raw.strip()
    last = parts[0].strip()
    first = parts[1].strip()
    initials = " ".join(
        f"{c[0]}." if not c.endswith(".") else c
        for c in first.split() if c
    )
    return f"{initials} {last}"


def format_authors(author_str: str) -> str:
    """Convierte lista de autores BibTeX a formato IEEE."""
    authors = [a.strip() for a in author_str.split(" and ")]
    return ", ".join(author_to_ieee(a) for a in authors)


def abbr_month(month) -> str:
    """Convierte nombre de mes (ES/EN) o número a dígito 1-12 sin leading zero."""
    raw = str(month).strip().lower()
    if raw.isdigit():
        return str(int(raw))
    return _MONTH_MAP.get(raw, str(month))
