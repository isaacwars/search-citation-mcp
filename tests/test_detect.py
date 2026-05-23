import pytest
from search_citation_mcp.detect import detect_input


class TestDetectInput:
    def test_doi(self):
        result = detect_input("10.1016/j.rser.2015.08.042")
        assert result["type"] == "doi"
        assert result["value"] == "10.1016/j.rser.2015.08.042"

    def test_doi_with_https_prefix(self):
        result = detect_input("https://doi.org/10.1109/TIE.2009.2017820")
        assert result["type"] == "doi"
        assert "10.1109" in result["value"]

    def test_arxiv_id_new(self):
        result = detect_input("2301.12345")
        assert result["type"] == "arxiv"
        assert result["value"] == "2301.12345"

    def test_arxiv_id_old(self):
        result = detect_input("hep-th/9901001")
        assert result["type"] == "arxiv"
        assert result["value"] == "hep-th/9901001"

    def test_arxiv_full_url(self):
        result = detect_input("https://arxiv.org/abs/2301.12345")
        assert result["type"] == "arxiv"
        assert result["value"] == "2301.12345"

    def test_pmid(self):
        result = detect_input("PMID: 12345678")
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    def test_isbn_13(self):
        result = detect_input("978-3-16-148410-0")
        assert result["type"] == "isbn"
        assert result["value"] == "9783161484100"

    def test_isbn_10(self):
        result = detect_input("0-306-40615-2")
        assert result["type"] == "isbn"
        assert result["value"] == "0306406152"

    def test_url(self):
        result = detect_input("https://example.com/paper.pdf")
        assert result["type"] == "url"
        assert result["value"] == "https://example.com/paper.pdf"

    def test_title_detected(self):
        result = detect_input("A Novel Approach to Photovoltaic Grid Integration")
        assert result["type"] == "title"
        assert result["value"] == "A Novel Approach to Photovoltaic Grid Integration"

    def test_empty_string(self):
        result = detect_input("")
        assert result["type"] == "unknown"
