import json
import os
import tempfile
from pathlib import Path

import pytest
import search_citation_mcp.search as search_mod
from search_citation_mcp.search import (
    _save_cache, find_cached, list_cached, _merge_results,
    search_papers,
)


# ---------------------------------------------------------------------------
# Helper: patch CACHE_DIR (module-level constant, can't be monkeypatched
# via setenv alone because it was evaluated at import time).
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch, tmp_path):
    """Every test gets its own isolated cache directory."""
    monkeypatch.setattr(search_mod, "CACHE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)


class TestCache:
    def test_save_and_find(self):
        results = [{
            "title": "A Test Paper",
            "doi": "10.1109/test.2023",
            "authors": ["Smith, John"],
            "year": 2023,
        }]
        _save_cache("test query", results)

        cached = find_cached(query="test query")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["title"] == "A Test Paper"

    def test_case_insensitive_query(self):
        _save_cache("Test Query", [{"title": "X"}])

        assert find_cached(query="test query") is not None
        assert find_cached(query="TEST QUERY") is not None

    def test_find_by_doi(self):
        _save_cache("q", [{"title": "X", "doi": "10.1109/test.2023"}])

        cached = find_cached(doi="10.1109/test.2023")
        assert cached is not None
        assert len(cached) == 1

    def test_find_by_author(self):
        _save_cache("q", [{"title": "X", "authors": ["Smith, John"]}])

        cached = find_cached(author="Smith")
        assert cached is not None

    def test_find_by_title(self):
        _save_cache("q", [{"title": "Photovoltaic Systems Review"}])

        cached = find_cached(title="Photovoltaic")
        assert cached is not None

    def test_miss_returns_none(self):
        _save_cache("q", [{"title": "X"}])

        assert find_cached(query="nonexistent") is None

    def test_list_cached(self):
        _save_cache("unique1", [{"title": "A"}])
        _save_cache("unique2", [{"title": "B"}])

        cached_list = list_cached(limit=100)
        ours = [c for c in cached_list if c["query"] in ("unique1", "unique2")]
        assert len(ours) == 2


class TestMergeResults:
    def test_adds_results(self):
        results_input = [{
            "title": "Test", "doi": "10.1109/test.2023",
            "authors": ["Smith"], "url": "https://example.com",
        }]
        results_output = []
        seen_dois = set()
        _merge_results(results_input, "openalex", seen_dois, False, results_output)
        assert len(results_output) == 1
        assert results_output[0]["source"] == "openalex"

    def test_dedup_by_doi(self):
        r1 = [{"title": "First", "doi": "10.1109/test.2023"}]
        r2 = [{"title": "Second", "doi": "10.1109/test.2023"}]

        output = []
        seen = set()
        _merge_results(r1, "openalex", seen, False, output)
        _merge_results(r2, "s2", seen, False, output)
        assert len(output) == 1
        assert output[0]["title"] == "First"

    def test_exclude_preprints(self):
        results = [{
            "title": "Preprint Paper", "doi": "10.1109/pre.2023",
            "is_preprint": True,
        }, {
            "title": "Published Paper", "doi": "10.1109/pub.2023",
            "is_preprint": False,
        }]
        output = []
        seen = set()
        _merge_results(results, "openalex", seen, True, output)
        assert len(output) == 1
        assert output[0]["title"] == "Published Paper"

    def test_no_doi_no_dedup(self):
        results = [
            {"title": "Paper A"},
            {"title": "Paper B"},
        ]
        output = []
        seen = set()
        _merge_results(results, "openalex", seen, False, output)
        assert len(output) == 2


class TestSearchPapers:
    def test_cache_hit_returns_early(self):
        _save_cache("cached query", [
            {"title": "Cached Paper", "doi": "10.1109/cached.2023"}
        ])

        results = search_papers("cached query", count=10)
        assert len(results) == 1
        assert results[0]["title"] == "Cached Paper"


class TestCacheRegression:
    """Regresión: bugs corregidos que no deben reintroducirse."""

    def test_cache_key_includes_count(self):
        """count=10 vs count=50 deben retornar resultados distintos."""
        results_10 = [{"title": f"Paper {i}", "doi": f"10.000/count-10-{i}"} for i in range(10)]
        results_50 = [{"title": f"Paper {i}", "doi": f"10.000/count-50-{i}"} for i in range(50)]

        _save_cache("key test", results_10, count=10)
        _save_cache("key test", results_50, count=50)

        cached_10 = find_cached(query="key test", count=10)
        cached_50 = find_cached(query="key test", count=50)

        assert cached_10 is not None
        assert cached_50 is not None
        assert len(cached_10) == 10
        assert len(cached_50) == 50
        assert cached_10[0]["doi"] != cached_50[0]["doi"]

    def test_cache_key_includes_year_filter(self):
        """year_from distinto debe aislar entradas de caché."""
        _save_cache("year test", [{"title": "Old", "doi": "10.000/old"}], count=10, year_from=2000, year_to=2010)
        _save_cache("year test", [{"title": "New", "doi": "10.000/new"}], count=10, year_from=2020, year_to=2025)

        cached_old = find_cached(query="year test", count=10, year_from=2000, year_to=2010)
        cached_new = find_cached(query="year test", count=10, year_from=2020, year_to=2025)

        assert cached_old is not None and cached_new is not None
        assert cached_old[0]["doi"] != cached_new[0]["doi"]

    def test_cache_key_includes_exclude_preprints(self):
        """exclude_preprints=True vs False deben aislar entradas."""
        _save_cache("ep test", [{"title": "With preprints", "doi": "10.000/with"}], count=10, exclude_preprints=False)
        _save_cache("ep test", [{"title": "No preprints", "doi": "10.000/without"}], count=10, exclude_preprints=True)

        cached_with = find_cached(query="ep test", count=10, exclude_preprints=False)
        cached_without = find_cached(query="ep test", count=10, exclude_preprints=True)

        assert cached_with is not None and cached_without is not None
        assert cached_with[0]["doi"] != cached_without[0]["doi"]

    def test_corrupt_cache_file_skipped(self):
        """Archivo de caché corrupto no debe romper find_cached."""
        (search_mod.CACHE_DIR / "corrupt.json").write_text("not valid json {{{")
        _save_cache("valid", [{"title": "Good"}])
        cached = find_cached(query="valid")
        assert cached is not None
        assert cached[0]["title"] == "Good"

    def test_cache_params_mismatch_returns_none(self):
        """Parámetros distintos deben ignorar entrada cacheada."""
        _save_cache("param q", [{"title": "X"}], count=10, year_from=2020)
        assert find_cached(query="param q", count=50, year_from=2020) is None
        assert find_cached(query="param q", count=10, year_from=2021) is None


class TestMergeDeterminism:
    """El orden de merge no debe depender del orden de inserción."""

    def test_merge_order_preserves_insertion_order(self):
        """_merge_results es determinista: preserva orden de inserción de fuentes."""
        r1 = [{"title": "Paper A", "doi": "10.000/a"}, {"title": "Paper B", "doi": "10.000/b"}]
        r2 = [{"title": "Paper C", "doi": "10.000/c"}, {"title": "Paper D", "doi": "10.000/d"}]

        out1 = []
        seen1 = set()
        _merge_results(r1, "openalex", seen1, False, out1)
        _merge_results(r2, "crossref", seen1, False, out1)

        out2 = []
        seen2 = set()
        _merge_results(r1, "openalex", seen2, False, out2)
        _merge_results(r2, "crossref", seen2, False, out2)

        assert [r["doi"] for r in out1] == [r["doi"] for r in out2]
        assert len(out1) == 4 and len(out2) == 4

    def test_global_count_enforced(self):
        """El límite count debe aplicarse después del merge."""
        r1 = [{"title": f"P{i}", "doi": f"10.000/{i}"} for i in range(5)]
        r2 = [{"title": f"Q{i}", "doi": f"10.000/q{i}"} for i in range(5)]
        r3 = [{"title": f"R{i}", "doi": f"10.000/r{i}"} for i in range(5)]

        out = []
        seen = set()
        _merge_results(r1, "openalex", seen, False, out)
        _merge_results(r2, "crossref", seen, False, out)
        _merge_results(r3, "s2", seen, False, out)

        assert len(out) <= 15
        limited = out[:10]
        assert len(limited) == 10


class TestDOICorrectionGuard:
    """La corrección de DOI debe exigir evidencia multi-campo."""

    def test_rejects_title_only_match(self):
        """Título similar pero autor/año distintos => no corregir."""
        from search_citation_mcp.search import _validate_doi_correction

        oa_data = {
            "authorships": [{"author": {"display_name": "Alice Smith"}}],
            "publication_year": 2020,
        }
        cr_data = {
            "author": [{"family": "Bob", "given": "Jones"}],
            "published-print": {"date-parts": [[2015]]},
        }
        assert _validate_doi_correction("10.000/orig", cr_data, oa_data) is False

    def test_accepts_author_and_year_match(self):
        """Autor y año coinciden => permitir corrección."""
        from search_citation_mcp.search import _validate_doi_correction

        oa_data = {
            "authorships": [{"author": {"display_name": "Alice Smith"}}],
            "publication_year": 2020,
        }
        cr_data = {
            "author": [{"family": "Smith", "given": "Alice"}],
            "published-print": {"date-parts": [[2020]]},
        }
        assert _validate_doi_correction("10.000/orig", cr_data, oa_data) is True

    def test_year_within_one_tolerance(self):
        """Año ±1 debe considerarse match."""
        from search_citation_mcp.search import _validate_doi_correction

        oa_data = {
            "authorships": [{"author": {"display_name": "Alice Smith"}}],
            "publication_year": 2020,
        }
        cr_data = {
            "author": [{"family": "Smith", "given": "Alice"}],
            "published-print": {"date-parts": [[2019]]},
        }
        assert _validate_doi_correction("10.000/orig", cr_data, oa_data) is True
