import os
import tempfile
import shutil
from pathlib import Path

import pytest
from search_citation_mcp.access.download import (
    _safe_output_path, _is_allowed_url, _extract_scihub_pdf,
    download_paper,
)


class TestSafeOutputPath:
    def test_normal_path(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        monkeypatch.chdir(tmp)
        try:
            path = _safe_output_path("./papers", "10.1016_test")
            assert path.name == "10.1016_test.pdf"
            assert path.parent.name == "papers"
        finally:
            shutil.rmtree(tmp)

    def test_creates_directories(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        monkeypatch.chdir(tmp)
        try:
            path = _safe_output_path("./sub/deep/papers", "paper")
            assert path.exists() or path.parent.exists()
        finally:
            shutil.rmtree(tmp)

    def test_path_traversal_blocked(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        monkeypatch.chdir(tmp)
        try:
            with pytest.raises(ValueError, match="escapa"):
                _safe_output_path("../../etc", "malicious")
        finally:
            shutil.rmtree(tmp)

    def test_special_chars_sanitized(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        monkeypatch.chdir(tmp)
        try:
            path = _safe_output_path("./papers", 'test<foo:"bar>')
            assert path.name == "test_foo__bar_.pdf"
        finally:
            shutil.rmtree(tmp)

    def test_doi_slash_sanitized(self, monkeypatch):
        tmp = tempfile.mkdtemp()
        monkeypatch.chdir(tmp)
        try:
            path = _safe_output_path("./papers", "10.1016/j.rser.2015.08.042")
            assert "/" not in path.name
        finally:
            shutil.rmtree(tmp)


class TestIsAllowedURL:
    def test_http_allowed(self):
        assert _is_allowed_url("http://example.com/paper.pdf") is True

    def test_https_allowed(self):
        assert _is_allowed_url("https://example.com/paper.pdf") is True

    def test_empty_string_allowed(self):
        assert _is_allowed_url("") is True

    def test_file_denied(self):
        assert _is_allowed_url("file:///etc/passwd") is False

    def test_ftp_denied(self):
        assert _is_allowed_url("ftp://example.com/paper.pdf") is False

    def test_javascript_denied(self):
        assert _is_allowed_url("javascript:alert(1)") is False

    def test_loopback_rejected(self):
        assert _is_allowed_url("http://127.0.0.1/private") is False
        assert _is_allowed_url("http://127.0.0.1:8080/data") is False

    def test_private_network_rejected(self):
        assert _is_allowed_url("http://10.0.0.1/admin") is False
        assert _is_allowed_url("http://192.168.1.1/config") is False
        assert _is_allowed_url("http://172.16.0.5/secret") is False

    def test_link_local_rejected(self):
        assert _is_allowed_url("http://169.254.1.1/meta") is False

    def test_localhost_rejected(self):
        assert _is_allowed_url("http://localhost:3000/api") is False

    def test_ipv6_loopback_rejected(self):
        assert _is_allowed_url("http://[::1]:8080/data") is False


class TestExtractScihubPDF:
    def test_iframe_src(self):
        html = '<iframe src="/download/1234abcd.pdf" id="pdf"></iframe>'
        result = _extract_scihub_pdf(html, "sci-hub.ru")
        assert "1234abcd.pdf" in result

    def test_embed_src(self):
        html = '<embed src="/download/abcd.pdf" type="application/pdf">'
        result = _extract_scihub_pdf(html, "sci-hub.ru")
        assert "abcd.pdf" in result

    def test_location_href_single_quotes(self):
        html = "location.href='/downloads/10.1016-paper.pdf?download=true'"
        result = _extract_scihub_pdf(html, "sci-hub.se")
        assert "10.1016-paper.pdf" in result

    def test_button_onclick(self):
        html = '<button onclick="location.href=\'/abc.pdf\'">Download</button>'
        result = _extract_scihub_pdf(html, "sci-hub.st")
        assert "abc.pdf" in result

    def test_protocol_relative_url(self):
        html = '<iframe src="//sci-hub.se/downloads/paper.pdf"></iframe>'
        result = _extract_scihub_pdf(html, "sci-hub.se")
        assert result.startswith("https://")

    def test_no_match(self):
        html = '<div>No PDF here</div>'
        result = _extract_scihub_pdf(html, "sci-hub.ru")
        assert result == ""


class TestDownloadPaper:
    def test_cache_hit(self, monkeypatch, tmp_path):
        import re
        doi = "10.test/cache"
        safe = re.sub(r'[<>:"/\\|?*]', '_', doi.replace("https://doi.org/", ""))
        dest = tmp_path / "papers" / f"{safe}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4\nfake pdf content")

        monkeypatch.chdir(tmp_path)
        result = download_paper(doi, output_dir="./papers")
        assert result["success"] is True
        assert result["source"] == "cache"

    def test_empty_urls_handled_gracefully(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = download_paper("10.nonexistent/paper",
                                output_dir="./papers",
                                oa_url="", s2_pdf_url="", arxiv_id="")
        assert result["success"] is False
        assert "error" in result
