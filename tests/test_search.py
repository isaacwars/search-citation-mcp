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
