import os
import tempfile
import shutil
import json

import pytest
from search_citation_mcp.server import _safe_path, _SEARCH_FIELDS


class TestSafePath:
    def test_normal_relative(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "test.bib").touch()
        path = _safe_path("./test.bib", must_exist=True)
        assert path == (tmp_path / "test.bib").resolve()

    def test_must_exist_fails(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            _safe_path("./nonexistent.bib", must_exist=True)

    def test_must_exist_false_ok(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        path = _safe_path("./nonexistent.bib", must_exist=False)
        assert path == (tmp_path / "nonexistent.bib").resolve()

    def test_path_traversal_blocked(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="escapa"):
            _safe_path("../../etc/shadow")


class TestSearchFields:
    """Verificar que _SEARCH_FIELDS solo contiene campos relevantes."""

    def test_contains_essential_fields(self):
        essential = {"title", "doi", "authors", "year", "abstract", "journal"}
        assert essential.issubset(set(_SEARCH_FIELDS))

    def test_excludes_raw_fields(self):
        assert "raw" not in _SEARCH_FIELDS
        assert "raw_oa" not in _SEARCH_FIELDS
