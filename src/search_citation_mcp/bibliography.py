"""Lectura y escritura de archivos bibliografia.bib."""

import logging
import os
import re
import threading
from pathlib import Path

try:
    import bibtexparser
    HAS_BIBTEX = True
except ImportError:
    HAS_BIBTEX = False

_WRITE_LOCK = threading.Lock()


def _resolve_path(path_str: str = "") -> Path:
    path = Path(path_str or os.getenv("BIBLIOGRAPHY_PATH", "./bibliografia.bib"))
    is_explicit = bool(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve()
    if not is_explicit or (path_str and not os.path.isabs(path_str)):
        cwd = Path.cwd().resolve()
        try:
            resolved.relative_to(cwd)
        except ValueError:
            raise ValueError(
                f"Ruta de bibliografía '{resolved}' escapa del workspace"
            )
    return resolved


def _parse_bib(path: Path) -> list:
    """Parsea un archivo .bib y retorna lista de entries (dicts con campo ID)."""
    if not HAS_BIBTEX:
        return []
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")
    try:
        lib = bibtexparser.parse_string(content)
    except Exception as e:
        logging.warning(f"No se pudo parsear {path}: {e}")
        return []
    result = []
    for e in lib.entries:
        fields = {}
        for field in e.fields:
            fields[field.key] = field.value
        result.append({"ID": e.key, **fields})
    return result


def existing_dois(bib_path: str = "") -> set:
    """Devuelve set de DOIs ya presentes en el .bib."""
    if not HAS_BIBTEX:
        return set()
    path = _resolve_path(bib_path)
    entries = _parse_bib(path)
    return {e.get("doi", "").strip().lower() for e in entries if e.get("doi")}


def existing_keys(bib_path: str = "") -> set:
    """Devuelve set de citation keys ya presentes."""
    if not HAS_BIBTEX:
        return set()
    path = _resolve_path(bib_path)
    entries = _parse_bib(path)
    return {e.get("ID", "") for e in entries}




def append_entry(bib_entry: str, bib_path: str = "") -> str:
    """Agrega una entrada .bib al archivo de bibliografía.

    Returns: key de la entrada agregada.
    Raises: ValueError si el DOI ya existe.
    """
    path = _resolve_path(bib_path)

    entry_key_match = re.search(r'@\w+\{(\w+),', bib_entry)
    entry_doi_match = re.search(r'\bdoi\s*=\s*\{([^}]+)\}', bib_entry)

    with _WRITE_LOCK:
        if entry_doi_match:
            new_doi = entry_doi_match.group(1).strip().lower()
            if new_doi in existing_dois(str(path)):
                raise ValueError(f"DOI ya existe en bibliografía: {new_doi}")

        new_key = entry_key_match.group(1) if entry_key_match else ""
        if new_key:
            keys = existing_keys(str(path))
            if new_key in keys:
                base = re.sub(r'[a-z]+$', '', new_key)
                suffix = 0
                while f"{base}{chr(97 + suffix)}" in keys:
                    suffix += 1
                    if suffix > 25:
                        base = f"{base}a"
                        suffix = 0
                new_key = f"{base}{chr(97 + suffix)}"
                bib_entry = bib_entry.replace(f"{{{entry_key_match.group(1)},", f"{{{new_key},")

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n" + bib_entry + "\n")
        except OSError as e:
            raise OSError(f"No se pudo escribir en {path}: {e}")

    return new_key


def _split_entries(content: str) -> list:
    """Divide un archivo .bib en entradas individuales."""
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
        if depth < 0:
            depth = 0
    if current:
        entries.append("\n".join(current))
    return entries
