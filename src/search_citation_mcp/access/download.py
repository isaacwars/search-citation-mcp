"""Descarga de PDFs desde repositorios gratuitos de acceso abierto.

Cadena de descarga free-first:
1. OpenAlex oa_url
2. Semantic Scholar openAccessPdf
3. Unpaywall API (gratis, requiere UNPAYWALL_EMAIL)
4. arXiv (si tiene arXiv ID)
5. Sci-Hub (opcional, configurable via SCIHUB_ENABLED)
"""

import ipaddress
import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from curl_cffi import requests as curl_requests

log = logging.getLogger("search-citation")

SCIHUB_MIRRORS = os.getenv(
    "SCIHUB_MIRRORS", "sci-hub.ru,sci-hub.st,sci-hub.se"
).split(",")

IMPERSONATE_BROWSER = os.getenv("IMPERSONATE_BROWSER", "chrome131")
MAX_PDF_SIZE = 100 * 1024 * 1024  # 100 MB

_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


# ---------------------------------------------------------------------------
# URL/path safety helpers
# ---------------------------------------------------------------------------

def _safe_output_path(output_dir: str, basename: str) -> Path:
    """Resuelve output_dir contra CWD y valida que no escape del workspace."""
    cwd = Path.cwd().resolve()
    out = (cwd / output_dir).resolve()
    try:
        out.relative_to(cwd)
    except ValueError:
        raise ValueError(
            f"Directorio de salida '{output_dir}' escapa del workspace "
            f"(resuelto a '{out}')"
        )
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', '_', basename or "paper")
    return out / f"{safe}.pdf"


def _is_allowed_url(url: str) -> bool:
    """Rechaza URLs con esquemas no esperados o que apunten a redes internas."""
    allowed = {"http", "https", ""}
    scheme = urlparse(url).scheme or ""
    if scheme not in allowed:
        return False
    parsed = urlparse(url)
    if not parsed.hostname:
        return True
    if parsed.hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        addr = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return True
    for net in _BLOCKED_NETS:
        if addr in net:
            return False
    return True


# ---------------------------------------------------------------------------
# Main download orchestration
# ---------------------------------------------------------------------------

def download_paper(doi: str, output_dir: str = "./papers",
                   oa_url: str = "", s2_pdf_url: str = "",
                   arxiv_id: str = "") -> dict:
    """Descarga el PDF de un paper desde fuentes gratuitas.

    Returns:
        {"success": bool, "path": str, "source": str, "error": str}
    """
    safe_name = re.sub(r'[<>:"/\\|?*]', '_',
                       doi.replace("https://doi.org/", ""))
    dest = _safe_output_path(output_dir, safe_name)

    if dest.exists():
        return {
            "success": True, "path": str(dest), "source": "cache",
            "size": dest.stat().st_size,
        }

    session = curl_requests.Session()

    queue = []
    if oa_url:
        queue.append(("openalex", oa_url, None))
    if s2_pdf_url:
        queue.append(("semanticscholar", s2_pdf_url, None))
    queue.append(("unpaywall", None, doi))
    if arxiv_id:
        queue.append(("arxiv", f"https://arxiv.org/pdf/{arxiv_id}.pdf", None))
    if os.getenv("SCIHUB_ENABLED", "").lower() in ("1", "true", "yes"):
        queue.append(("scihub", None, doi))

    for source, url, arg_doi in queue:
        if source in ("unpaywall", "scihub"):
            func = _try_unpaywall if source == "unpaywall" else _try_scihub
            result = func(arg_doi, dest, session)
        else:
            result = _try_download(url, dest, source, session)
        if result["success"]:
            return result

    return {
        "success": False, "path": "", "source": "",
        "error": "No se encontró PDF gratuito para este DOI.",
    }


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _write_file(dest: Path, content: bytes) -> Path:
    """Escribe atómicamente: temp file + rename para evitar archivos truncados."""
    fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".download_", suffix=".tmp")
    try:
        with open(fd, "wb") as f:
            f.write(content)
        tmp = Path(tmp_path)
        tmp.replace(dest)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return dest

def _try_download(url: str, dest: Path, source: str,
                  session: curl_requests.Session | None = None) -> dict:
    """Intenta descargar un PDF usando browser impersonation."""
    if not url:
        return {"success": False, "error": "URL vacía"}
    if not _is_allowed_url(url):
        return {"success": False, "error": f"Esquema de URL no permitido: {url}"}

    session = session or curl_requests.Session()
    try:
        resp = session.get(
            url, timeout=30, allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,text/html,*/*",
            },
            impersonate=IMPERSONATE_BROWSER,
        )
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        content = resp.content
        content_type = resp.headers.get("Content-Type", "").lower()

        if content[:5] == b"%PDF-" or content[3:8] == b"%PDF-":
            if len(content) > MAX_PDF_SIZE:
                return {"success": False, "error": f"PDF excede límite de {MAX_PDF_SIZE // (1024*1024)} MB"}
            _write_file(dest, content)
            return {
                "success": True, "path": str(dest), "source": source,
                "size": len(content),
            }

        if "html" in content_type and len(content) < 5000:
            refresh = re.search(rb"URL='([^']+)'", content)
            if refresh:
                redirect_url = refresh.group(1).decode()
                if not redirect_url.startswith("http"):
                    from urllib.parse import urljoin
                    redirect_url = urljoin(url, redirect_url)
                if not _is_allowed_url(redirect_url):
                    return {"success": False, "error": f"Esquema de URL no permitido en redirect"}
                resp2 = session.get(
                    redirect_url, timeout=30, allow_redirects=True,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36"
                        ),
                        "Accept": "application/pdf,text/html,*/*",
                    },
                    impersonate=IMPERSONATE_BROWSER,
                )
                if resp2.status_code == 200 and (resp2.content[:5] == b"%PDF-" or resp2.content[3:8] == b"%PDF-"):
                    if len(resp2.content) > MAX_PDF_SIZE:
                        return {"success": False, "error": f"PDF excede límite de {MAX_PDF_SIZE // (1024*1024)} MB"}
                    _write_file(dest, resp2.content)
                    return {
                        "success": True, "path": str(dest),
                        "source": source, "size": len(resp2.content),
                    }

        return {"success": False,
                "error": f"No se pudo obtener PDF ({len(content)} bytes)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _try_unpaywall(doi: str, dest: Path,
                   session: curl_requests.Session | None = None) -> dict:
    """Intenta descargar via Unpaywall API."""
    email = os.getenv("UNPAYWALL_EMAIL", "")
    if not email:
        return {"success": False, "error": "UNPAYWALL_EMAIL no configurado"}
    try:
        resp = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"success": False,
                    "error": f"Unpaywall HTTP {resp.status_code}"}
        data = resp.json()
        best = data.get("best_oa_location") or {}
        oa_locs = [best] + (data.get("oa_locations") or [])
        for loc in oa_locs[:6]:
            url = loc.get("url_for_pdf") or loc.get("url", "")
            if url:
                result = _try_download(url, dest, "unpaywall", session)
                if result["success"]:
                    return result
        return {"success": False, "error": "Unpaywall: sin PDF disponible"}
    except Exception as e:
        return {"success": False, "error": f"Unpaywall: {e}"}


def _try_scihub(doi: str, dest: Path,
                session: curl_requests.Session | None = None) -> dict:
    """Intenta descargar via Sci-Hub (último recurso, opcional)."""
    session = session or curl_requests.Session()
    for mirror in SCIHUB_MIRRORS:
        mirror = mirror.strip()
        if not mirror:
            continue
        try:
            url = f"https://{mirror}/{doi}"
            resp = session.get(
                url, timeout=30, allow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    ),
                    "Accept": "text/html,application/pdf,*/*",
                },
                impersonate=IMPERSONATE_BROWSER,
            )
            if resp.status_code != 200:
                continue

            pdf_url = _extract_scihub_pdf(resp.text, mirror)
            if pdf_url:
                if not pdf_url.startswith("http"):
                    pdf_url = f"https://{mirror}{pdf_url}"
                pdf_resp = session.get(
                    pdf_url, timeout=60, allow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/pdf,*/*",
                    },
                    impersonate=IMPERSONATE_BROWSER,
                )
                if (pdf_resp.status_code == 200
                        and (pdf_resp.content[:5] == b"%PDF-" or pdf_resp.content[3:8] == b"%PDF-")):
                    if len(pdf_resp.content) > MAX_PDF_SIZE:
                        continue
                    _write_file(dest, pdf_resp.content)
                    return {
                        "success": True, "path": str(dest),
                        "source": f"scihub:{mirror}",
                        "size": len(pdf_resp.content),
                    }
        except Exception as e:
            log.debug(f"Sci-Hub mirror {mirror} failed: {e}")
            continue
    return {"success": False, "error": "Sci-Hub: sin acceso en ningún mirror"}


def _extract_scihub_pdf(html: str, mirror: str) -> str:
    """Extrae URL del PDF desde la página de Sci-Hub."""
    for pattern in [
        r'<iframe[^>]+src\s*=\s*"([^"]+)"',
        r'<embed[^>]+src\s*=\s*"([^"]+)"',
        r"<iframe[^>]+src\s*=\s*'([^']+)'",
        r"<embed[^>]+src\s*=\s*'([^']+)'",
        r'location\.href\s*=\s*"([^"]+\.pdf[^"]*)"',
        r"location\.href\s*=\s*'([^']+\.pdf[^']*)'",
        r'<button[^>]+onclick\s*=\s*"location\.href=\'([^\']+)\'"',
    ]:
        m = re.search(pattern, html)
        if m:
            url = m.group(1)
            if url.startswith("//"):
                return f"https:{url}"
            return url
    return ""
