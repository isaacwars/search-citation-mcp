"""Normalización de DOIs: quita prefijos URL, lower, strip."""

import re

_DOI_PREFIX_RE = re.compile(r'https?://(?:dx\.)?doi\.org/', re.IGNORECASE)


def normalize_doi(doi: str) -> str:
    """Limpia y normaliza un DOI: quita prefijo URL, lower, strip."""
    doi = (_DOI_PREFIX_RE.sub('', doi) if doi else '').strip().lower()
    return doi
