import os
import tempfile
import shutil

import pytest
from search_citation_mcp.bibliography import (
    _resolve_path, append_entry, existing_dois, existing_keys,
)


class TestResolvePath:
    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("BIBLIOGRAPHY_PATH", raising=False)
        path = _resolve_path()
        assert path.name == "bibliografia.bib"

    def test_env_var_used(self, monkeypatch):
        monkeypatch.setenv("BIBLIOGRAPHY_PATH", "./mi_biblio.bib")
        path = _resolve_path()
        assert path.name == "mi_biblio.bib"

    def test_explicit_path_overrides_env(self, monkeypatch):
        monkeypatch.setenv("BIBLIOGRAPHY_PATH", "./ignored.bib")
        path = _resolve_path("./explicit.bib")
        assert path.name == "explicit.bib"

    def test_path_traversal_blocked(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="escapa"):
            _resolve_path("../../etc/passwd")

    def test_absolute_within_workspace(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        safe = tmp_path / "sub" / "test.bib"
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.touch()
        path = _resolve_path(str(safe))
        assert path == safe.resolve()


class TestAppendEntry:
    def test_writes_entry_and_returns_key(self, monkeypatch, tmp_path):
        bib_path = tmp_path / "test.bib"
        monkeypatch.setenv("BIBLIOGRAPHY_PATH", str(bib_path))

        entry = '@article{smith2023,\n    author = {Smith, John},\n    title = {A Study},\n    journal = {IEEE Trans.},\n    year = {2023},\n    doi = {10.1109/test.2023},\n}'
        key = append_entry(entry, str(bib_path))
        assert key == "smith2023"
        assert bib_path.exists()
        content = bib_path.read_text()
        assert "smith2023" in content

    def test_duplicate_doi_rejected(self, monkeypatch, tmp_path):
        bib_path = tmp_path / "test2.bib"
        monkeypatch.setenv("BIBLIOGRAPHY_PATH", str(bib_path))

        entry1 = '@article{smith2023,\n    author = {Smith},\n    title = {First},\n    journal = {IEEE},\n    year = {2023},\n    doi = {10.1109/dup.2023},\n}'
        append_entry(entry1, str(bib_path))

        entry2 = '@article{jones2023,\n    author = {Jones},\n    title = {Second},\n    journal = {IEEE},\n    year = {2023},\n    doi = {10.1109/dup.2023},\n}'
        with pytest.raises(ValueError, match="ya existe"):
            append_entry(entry2, str(bib_path))

    def test_key_collision_generates_suffix(self, monkeypatch, tmp_path):
        bib_path = tmp_path / "test3.bib"
        monkeypatch.setenv("BIBLIOGRAPHY_PATH", str(bib_path))

        e1 = '@article{smith2023,\n    author = {Smith},\n    title = {First},\n    journal = {IEEE},\n    year = {2023},\n}'
        key1 = append_entry(e1, str(bib_path))
        assert key1 == "smith2023"

        e2 = '@article{smith2023,\n    author = {Smith},\n    title = {Second},\n    journal = {IEEE},\n    year = {2023},\n}'
        key2 = append_entry(e2, str(bib_path))
        assert key2 in ("smith2023a", "smith2023b")
        assert key2 != "smith2023"

    def test_multi_letter_suffix(self, monkeypatch, tmp_path):
        """Verifica que después de smith2023z venga smith2023aa."""
        bib_path = tmp_path / "test4.bib"
        monkeypatch.setenv("BIBLIOGRAPHY_PATH", str(bib_path))

        entry_tpl = '@article{smith2023,\n    author = {Smith},\n    title = {Test},\n    journal = {IEEE},\n    year = {2023},\n}'
        # Fill keys: smith2023 + a through z = 27 entries
        for _ in range(27):
            append_entry(entry_tpl, str(bib_path))

        # Next one should overflow to aa
        key = append_entry(entry_tpl, str(bib_path))
        assert key.startswith("smith2023a")
        assert len(key) > len("smith2023a")  # smith2023aa o smith2023ab


class TestExistingDois:
    def test_empty_file(self, monkeypatch, tmp_path):
        bib_path = tmp_path / "empty.bib"
        bib_path.touch()
        dois = existing_dois(str(bib_path))
        assert dois == set()

    def test_existing_doi_found(self, monkeypatch, tmp_path):
        bib_path = tmp_path / "has_doi.bib"
        bib_path.write_text('@article{test, author={Smith}, title={T}, journal={J}, year={2023}, doi={10.1109/test.2023}}')
        dois = existing_dois(str(bib_path))
        assert "10.1109/test.2023" in dois
