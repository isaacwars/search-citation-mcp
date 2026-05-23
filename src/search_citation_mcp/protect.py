import re

ACRONYMS = sorted([
    "AC", "ADC", "AI", "AOPDS", "CEC", "CFE", "CNE", "CRE", "DC",
    "DOF", "DSP", "DTR", "FPGA", "IGBT", "IEA", "IEC", "IEEE",
    "IET", "INDUSCON", "IPN", "LAPEM", "LTE", "MATLAB", "MOSFET",
    "MPPT", "NASA", "NOM", "PLADESE", "PLOS", "PLC", "PV",
    "PVC", "PVSyst", "SCADA", "SEDE", "SENER", "SFVI", "Simulink",
    "SSE", "THD", "UNAM", "WCPEC", "ICHVEPS",
], key=len, reverse=True)

_ACRONYM_PATTERN = '|'.join(re.escape(a) for a in ACRONYMS)
ACRONYM_RE = re.compile(r'\b(' + _ACRONYM_PATTERN + r')\b')


def protect(text: str) -> str:
    """Envuelve siglas conocidas en llaves BibTeX."""
    def _replace(m):
        acro = m.group(0)
        before = text[max(0, m.start() - 1):m.start()]
        after = text[m.end():m.end() + 1] if m.end() < len(text) else ''
        if before == '{' and after == '}':
            return acro
        return '{' + acro + '}'
    return ACRONYM_RE.sub(_replace, text)


def protect_fields(entry: dict) -> dict:
    """Aplica protect() a title, booktitle y journal de una entrada .bib."""
    for field in ("title", "booktitle", "journal"):
        if field in entry:
            entry[field] = protect(entry[field])
    return entry
