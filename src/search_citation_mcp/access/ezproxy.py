"""EZProxy URL converter — institutional library proxy access."""

import json
import os
from urllib.parse import urlparse

_DEFAULT_PUBLISHER_MAP = {
    "ieeexplore.ieee.org": "ieeexplore.{host}",
    "sciencedirect.com": "sciencedirect.{host}",
    "link.springer.com": "springerlink.{host}",
    "nature.com": "nature.{host}",
    "onlinelibrary.wiley.com": "wiley.{host}",
    "jstor.org": "jstor.{host}",
    "tandfonline.com": "tandfonline.{host}",
    "pubs.acs.org": "acs.{host}",
    "cambridge.org": "cambridge.{host}",
    "academic.oup.com": "oxfordjournals.{host}",
}

_OA_DOMAINS = {
    "arxiv.org", "biorxiv.org", "mdpi.com", "frontiersin.org",
    "researchgate.net", "academia.edu", "plos.org", "doaj.org",
    "pubmedcentral.nih.gov", "ncbi.nlm.nih.gov",
}


def _load_publisher_map() -> dict:
    env_map = os.getenv("EZPROXY_PUBLISHER_MAP", "")
    if env_map:
        try:
            return json.loads(env_map)
        except json.JSONDecodeError:
            pass
    return dict(_DEFAULT_PUBLISHER_MAP)


def to_ezproxy(doi: str = "", url: str = "") -> str:
    """Convierte DOI o URL de editorial a su equivalente via EZProxy.

    Requiere EZPROXY_HOST en .env.
    Retorna cadena vacía si el paper es open access o no hay host configurado.
    """
    host = os.getenv("EZPROXY_HOST", "")
    if not host:
        return ""

    publisher_map = _load_publisher_map()

    if url:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")

        if any(oa in domain for oa in _OA_DOMAINS):
            return ""

        if host in url:
            return url

        for key, template in publisher_map.items():
            if key in domain:
                proxy_domain = template.format(host=host)
                return url.replace(
                    domain, proxy_domain, 1
                ) if domain in parsed.netloc else f"https://{proxy_domain}{parsed.path}"

    if doi and not url:
        return f"https://doi.{host}/{doi}"

    if doi:
        return f"https://doi.{host}/{doi}"

    return ""
