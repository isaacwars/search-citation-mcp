"""Detección inteligente de tipo de entrada: DOI, arXiv, PMID, ISBN, URL, título."""

import re

DOI_RE = re.compile(r'\b(10\.\d{4,}(?:\.\d+)?/[-._;()/:a-zA-Z0-9]+)\b')
ARXIV_NEW_RE = re.compile(r'\b(\d{4}\.\d{4,5}(?:v\d+)?)\b')
ARXIV_OLD_RE = re.compile(r'\b([a-z-]+/\d{7}(?:v\d+)?)\b', re.IGNORECASE)
ARXIV_PREFIX_RE = re.compile(r'arxiv[:\s]*(\d{4}\.\d{4,5})', re.IGNORECASE)
PMID_NUMERIC_RE = re.compile(r'^\d{7,8}$')
PMID_PREFIX_RE = re.compile(r'(?:PMID|pmid)[:\s]*(\d{7,8})')
ISBN10_RE = re.compile(r'\b(?:\d[ -]?){9}[\dXx]\b')
ISBN13_RE = re.compile(r'\b(?:97[89][ -]?)(?:\d[ -]?){9}\d\b')
URL_RE = re.compile(r'^https?://', re.IGNORECASE)


def detect_input(text: str) -> dict:
    """Detecta si la entrada es DOI, arXiv ID, PMID, ISBN, URL o título.

    Returns: {"type": "...", "value": "...", "confidence": "..."}
    """
    text = text.strip()

    if not text:
        return {"type": "unknown", "value": "", "confidence": "low"}

    url_match = URL_RE.match(text)
    if url_match:
        doi_in_url = DOI_RE.search(text)
        if doi_in_url:
            return {"type": "doi", "value": doi_in_url.group(1), "confidence": "high"}
        arxiv_match = ARXIV_NEW_RE.search(text)
        if arxiv_match:
            return {"type": "arxiv", "value": arxiv_match.group(1), "confidence": "high"}
        return {"type": "url", "value": text, "confidence": "high"}

    doi_match = DOI_RE.search(text)
    if doi_match:
        return {"type": "doi", "value": doi_match.group(1), "confidence": "high"}

    arxiv_prefix = ARXIV_PREFIX_RE.search(text)
    if arxiv_prefix:
        return {"type": "arxiv", "value": arxiv_prefix.group(1), "confidence": "high"}

    arxiv_new = ARXIV_NEW_RE.match(text)
    if arxiv_new:
        return {"type": "arxiv", "value": arxiv_new.group(1), "confidence": "high"}

    arxiv_old = ARXIV_OLD_RE.match(text)
    if arxiv_old:
        return {"type": "arxiv", "value": arxiv_old.group(1), "confidence": "high"}

    pmid_prefix = PMID_PREFIX_RE.search(text)
    if pmid_prefix:
        return {"type": "pmid", "value": pmid_prefix.group(1), "confidence": "medium"}

    pmid_match = PMID_NUMERIC_RE.match(text)
    if pmid_match:
        return {"type": "pmid", "value": text, "confidence": "medium"}

    isbn_clean = text.replace("-", "").replace(" ", "")
    isbn_text = re.sub(r'^(?:ISBN|isbn)[:\s]*', '', text)
    if ISBN13_RE.match(isbn_text) or ISBN10_RE.match(isbn_text):
        return {"type": "isbn", "value": isbn_clean, "confidence": "medium"}

    return {"type": "title", "value": text, "confidence": "low"}
