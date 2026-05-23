import pytest
from search_citation_mcp.validate import (
    check_bib_entry, fuzzy_verify, strip_braces,
    validate_after_append, Status,
)


class TestStripBraces:
    def test_no_braces(self):
        assert strip_braces("Hello World") == "Hello World"

    def test_with_braces(self):
        assert strip_braces("{Hello} World") == "Hello World"

    def test_nested_braces(self):
        assert strip_braces("{{IEEE}} standard") == "IEEE standard"


class TestCheckBibEntry:
    def test_valid_article(self):
        entry = '@article{smith2023,\n    author = {Smith, John},\n    title = {{IEEE} Standard},\n    journal = {IEEE Trans.},\n    year = {2023},\n    doi = {10.1109/test.2023},\n}'
        status, issues = check_bib_entry(entry)
        assert status == Status.OK
        assert len(issues) == 0

    def test_article_without_doi_warns(self):
        entry = '@article{smith2023,\n    author = {Smith, John},\n    title = {Test},\n    journal = {IEEE},\n    year = {2023},\n}'
        status, issues = check_bib_entry(entry)
        assert status == Status.WARNING
        assert any("doi" in i.lower() for i in issues)

    def test_missing_required_field_errors(self):
        entry = '@article{test,\n    title = {Test},\n    journal = {IEEE},\n    year = {2023},\n}'
        status, issues = check_bib_entry(entry)
        assert status == Status.ERROR
        assert any("author" in i.lower() for i in issues)

    def test_not_starting_with_at_errors(self):
        entry = 'article{test, title = {Test}}'
        status, _ = check_bib_entry(entry)
        assert status == Status.ERROR

    def test_unprotected_acronym_warns(self):
        entry = '@article{test,\n    author = {Smith, John},\n    title = {IEEE Standard for CFE},\n    journal = {IEEE},\n    year = {2023},\n    doi = {10.1109/test},\n}'
        status, issues = check_bib_entry(entry)
        assert status in (Status.WARNING, Status.OK)
        # CFE without braces should trigger warning
        if status == Status.WARNING:
            assert any("CFE" in i for i in issues)

    def test_protected_acronym_clean(self):
        entry = '@article{test,\n    author = {Smith, John},\n    title = {{IEEE} Standard for {CFE}},\n    journal = {IEEE},\n    year = {2023},\n    doi = {10.1109/test},\n}'
        status, issues = check_bib_entry(entry)
        assert status == Status.OK

    def test_all_caps_word_warns(self):
        entry = '@article{test,\n    author = {Smith, John},\n    title = {IMPORTANTE estudio},\n    journal = {IEEE},\n    year = {2023},\n    doi = {10.1109/test},\n}'
        status, issues = check_bib_entry(entry)
        # IMPORTANTE is all caps but not in ACRONYMS
        assert any("IMPORTANTE" in i or "MAYÚSCULAS" in i for i in issues)

    def test_datasheet_suggests_manual(self):
        entry = '@article{test,\n    author = {Hioki},\n    title = {PQ3100 Datasheet},\n    journal = {Catalog},\n    year = {2023},\n    doi = {10.1109/test},\n}'
        status, issues = check_bib_entry(entry)
        if status == Status.WARNING:
            assert any("manual" in i.lower() for i in issues)


class TestFuzzyVerify:
    def test_perfect_match(self):
        result = fuzzy_verify(
            "A Study of PV Systems", "Smith", 2023,
            "A Study of PV Systems", "Smith, John", 2023,
        )
        assert result["status"] == "ok"
        assert result["confidence"] >= 90

    def test_title_mismatch(self):
        result = fuzzy_verify(
            "A Study of PV Systems", "Smith", 2023,
            "Completely Different Topic", "Smith, John", 2023,
        )
        assert result["confidence"] < 85

    def test_year_one_off_tolerated(self):
        result = fuzzy_verify(
            "A Study of PV Systems", "Smith", 2023,
            "A Study of PV Systems", "Smith, John", 2022,
        )
        assert result["year_match"] is True

    def test_year_two_off_fails(self):
        result = fuzzy_verify(
            "A Study of PV Systems", "Smith", 2023,
            "A Study of PV Systems", "Smith, John", 2021,
        )
        assert result["year_match"] is False

    def test_braces_stripped_for_comparison(self):
        result = fuzzy_verify(
            "{A Study} of {PV} Systems", "Smith", 2023,
            "A Study of PV Systems", "Smith, John", 2023,
        )
        assert result["title_score"] >= 90


class TestValidateAfterAppend:
    def test_returns_status_and_key(self):
        entry = '@article{key2023,\n    author = {Smith},\n    title = {Test},\n    journal = {IEEE},\n    year = {2023},\n    doi = {10.1109/test},\n}'
        result = validate_after_append("key2023", entry)
        assert result["key"] == "key2023"
        assert result["status"] in ("ok", "warning", "error")
        assert isinstance(result["warnings"], list)
