"""Generación de entradas BibTeX con validación contra SCHEMA IEEE."""

import re
from datetime import datetime

from .protect import protect_fields
from .style import abbr_month

SCHEMA = {
    "article": {
        "required": ["author", "title", "journal", "year"],
        "optional": ["volume", "number", "pages", "month", "doi", "url", "note", "issn", "publisher"],
    },
    "inproceedings": {
        "required": ["author", "title", "booktitle", "year"],
        "optional": ["pages", "address", "month", "doi", "url", "note", "publisher", "organization"],
    },
    "book": {
        "required": ["author", "title", "publisher", "year"],
        "optional": ["address", "edition", "month", "isbn", "note", "doi", "url"],
    },
    "incollection": {
        "required": ["author", "title", "booktitle", "publisher", "year"],
        "optional": ["editor", "address", "pages", "month", "isbn", "note", "doi", "url"],
    },
    "techreport": {
        "required": ["author", "title", "institution", "year"],
        "optional": ["address", "number", "month", "type", "url", "note"],
    },
    "mastersthesis": {
        "required": ["author", "title", "school", "year"],
        "optional": ["address", "month", "url", "note", "doi", "type"],
    },
    "phdthesis": {
        "required": ["author", "title", "school", "year"],
        "optional": ["address", "month", "url", "note", "doi", "type"],
    },
    "manual": {
        "required": ["title"],
        "optional": ["author", "organization", "address", "edition", "month", "year", "url", "note"],
    },
    "misc": {
        "required": [],
        "optional": ["author", "title", "howpublished", "month", "year", "url", "note", "address", "organization", "type"],
    },
    "online": {
        "required": [],
        "optional": ["author", "title", "year", "url", "note", "organization", "urldate"],
    },
}

_OA_TYPE_MAP = {
    "conference": "inproceedings",
    "proceedings": "inproceedings",
    "book": "book",
    "monograph": "book",
    "dissertation": "phdthesis",
    "thesis": "mastersthesis",
    "report": "techreport",
    "posted-content": "misc",
    "dataset": "misc",
    "other": "misc",
}


def _make_key(data: dict, entry_type: str) -> str:
    author = data.get("author", "")
    year = str(data.get("year") or "xxxx")
    if author:
        first_author = re.sub(r'[^a-zA-Z0-9\u00c0-\u024f]', '', author.split(",")[0].split()[-1]).lower()
    else:
        first_author = entry_type
    return f"{first_author}{year}"


def from_doi(doi: str, openalex_data: dict) -> str:
    """Genera entrada .bib a partir de metadata de OpenAlex."""
    oa_type = openalex_data.get("type", "").lower()
    entry_type = _OA_TYPE_MAP.get(oa_type, "article")

    data = {}
    authors = openalex_data.get("authorships", [])
    if authors:
        author_list = []
        for a in authors:
            name = a.get("author", {}).get("display_name", "")
            if name and " " in name:
                parts = name.rsplit(" ", 1)
                first_parts = parts[0].split()
                initials = ". ".join(f"{fp[0]}." for fp in first_parts if fp)
                author_list.append(f"{parts[1]}, {initials}")
            elif name:
                author_list.append(name)
        data["author"] = " and ".join(author_list)

    title = openalex_data.get("title", "")
    if title:
        title = title.strip().rstrip(".")
    data["title"] = title

    if entry_type == "article":
        loc = openalex_data.get("primary_location", {}) or {}
        src = loc.get("source", {}) or {}
        data["journal"] = src.get("display_name", "")
        biblio = openalex_data.get("biblio", {}) or {}
        if biblio.get("volume"):
            data["volume"] = biblio["volume"]
        if biblio.get("issue"):
            data["number"] = biblio["issue"]
        if biblio.get("first_page") and biblio.get("last_page"):
            data["pages"] = f"{biblio['first_page']}--{biblio['last_page']}"
    elif entry_type == "inproceedings":
        loc = openalex_data.get("primary_location", {}) or {}
        src = loc.get("source", {}) or {}
        data["booktitle"] = src.get("display_name", "")
    elif entry_type in ("mastersthesis", "phdthesis"):
        loc = openalex_data.get("primary_location", {}) or {}
        src = loc.get("source", {}) or {}
        data["school"] = src.get("display_name", "")
    elif entry_type == "techreport":
        data["institution"] = openalex_data.get("publisher", "")

    pub_year = openalex_data.get("publication_year")
    if pub_year:
        data["year"] = str(pub_year)

    pub_date = openalex_data.get("publication_date") or ""
    if pub_date:
        parts = pub_date.split("-")
        if len(parts) >= 2:
            data["month"] = abbr_month(parts[1])

    data["doi"] = doi

    return from_fields(entry_type, data)


def from_fields(entry_type: str, data: dict) -> str:
    """Genera texto .bib validando campos contra SCHEMA."""
    schema = SCHEMA.get(entry_type)
    if not schema:
        raise ValueError(f"Entry type '{entry_type}' no reconocido. Válidos: {list(SCHEMA.keys())}")

    missing = [f for f in schema["required"] if f not in data or not data[f]]
    if missing:
        raise ValueError(
            f"{entry_type} requiere: {', '.join(schema['required'])}. "
            f"Falta: {', '.join(missing)}"
        )

    allowed = set(schema["required"] + schema["optional"])
    custom_key = data.get("key")
    clean = {k: v for k, v in data.items() if k in allowed and v}

    extra = [k for k in data if k not in allowed and k != "key" and data[k]]
    if extra:
        import warnings
        warnings.warn(
            f"Campos no reconocidos para @{entry_type} ignorados: {', '.join(extra)}"
        )

    if "month" in clean:
        clean["month"] = abbr_month(clean["month"])

    clean = protect_fields(clean)

    key = custom_key or _make_key(clean, entry_type)
    lines = [f"    {k} = {{{v}}}," for k, v in clean.items()]
    body = "\n".join(lines)

    return f"@{entry_type}{{{key},\n{body}\n}}"


def from_crossref_data(cr_data: dict) -> str:
    """Genera texto .bib a partir del formato normalizado de Crossref."""
    entry_type = cr_data.get("type", "article")
    if entry_type not in SCHEMA:
        entry_type = "misc"

    data = {}
    if cr_data.get("authors"):
        data["author"] = " and ".join(cr_data["authors"])
    if cr_data.get("title"):
        data["title"] = cr_data["title"].strip().rstrip(".")

    if entry_type == "article":
        if cr_data.get("journal"):
            data["journal"] = cr_data["journal"]
        if cr_data.get("volume"):
            data["volume"] = str(cr_data["volume"])
        if cr_data.get("issue"):
            data["number"] = str(cr_data["issue"])
        pages = cr_data.get("pages", "")
        if pages:
            data["pages"] = pages.replace("-", "--") if "--" not in pages else pages
        if cr_data.get("issn"):
            data["issn"] = cr_data["issn"]
    elif entry_type == "inproceedings":
        data["booktitle"] = cr_data.get("journal", "")
        pages = cr_data.get("pages", "")
        if pages:
            data["pages"] = pages.replace("-", "--") if "--" not in pages else pages
    elif entry_type == "book":
        data["publisher"] = cr_data.get("publisher", "")
        if cr_data.get("isbn"):
            data["isbn"] = cr_data["isbn"]
        if cr_data.get("edition"):
            data["edition"] = str(cr_data["edition"])
        if cr_data.get("address"):
            data["address"] = cr_data["address"]
    elif entry_type in ("incollection",):
        data["booktitle"] = cr_data.get("journal", "")
        data["publisher"] = cr_data.get("publisher", "")
        pages = cr_data.get("pages", "")
        if pages:
            data["pages"] = pages.replace("-", "--") if "--" not in pages else pages

    if cr_data.get("year"):
        data["year"] = str(cr_data["year"])
    if cr_data.get("doi"):
        data["doi"] = cr_data["doi"]
    if cr_data.get("url"):
        data["url"] = cr_data["url"]

    pub_date = cr_data.get("publication_date", "")
    if pub_date and len(pub_date) >= 7:
        parts = pub_date.split("-")
        if len(parts) >= 2 and parts[1]:
            data["month"] = abbr_month(parts[1])

    return from_fields(entry_type, data)


def validate_fields(entry_type: str, data: dict) -> list:
    """Devuelve lista de errores de validación (vacío = válido)."""
    schema = SCHEMA.get(entry_type)
    if not schema:
        return [f"Tipo '{entry_type}' no reconocido"]
    errors = []
    for f in schema["required"]:
        if f not in data or not data[f]:
            errors.append(f"Falta campo requerido: {f}")
    return errors
