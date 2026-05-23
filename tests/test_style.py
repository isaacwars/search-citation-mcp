import pytest
from search_citation_mcp.style import abbr_month, author_to_ieee, format_authors


class TestAbbrMonth:
    def test_english_full(self):
        assert abbr_month("January") == "1"
        assert abbr_month("december") == "12"
        assert abbr_month("June") == "6"

    def test_english_abbreviated(self):
        assert abbr_month("jan") == "1"
        assert abbr_month("Feb") == "2"
        assert abbr_month("Dec") == "12"

    def test_spanish_full(self):
        assert abbr_month("enero") == "1"
        assert abbr_month("diciembre") == "12"
        assert abbr_month("Marzo") == "3"
        assert abbr_month("agosto") == "8"
        assert abbr_month("septiembre") == "9"

    def test_spanish_abbreviated(self):
        assert abbr_month("ene") == "1"
        assert abbr_month("abr") == "4"
        assert abbr_month("dic") == "12"

    def test_already_numeric(self):
        assert abbr_month("1") == "1"
        assert abbr_month(12) == "12"

    def test_unknown_month_returns_original(self):
        result = abbr_month("ventôse")
        assert result == "ventôse"


class TestAuthorToIEEE:
    def test_simple(self):
        assert author_to_ieee("Smith, John") == "J. Smith"

    def test_middle_initial(self):
        assert author_to_ieee("Garcia Marquez, Gabriel Jose") == "G. J. Garcia Marquez"

    def test_no_comma(self):
        assert author_to_ieee("Smith") == "Smith"

    def test_single_name(self):
        assert author_to_ieee("Confucius") == "Confucius"

    def test_already_abbreviated(self):
        assert author_to_ieee("Smith, J.") == "J. Smith"


class TestFormatAuthors:
    def test_single_author(self):
        result = format_authors("Smith, John")
        assert result == "J. Smith"

    def test_multiple_authors(self):
        result = format_authors("Smith, John and Jones, Mary and Brown, Robert K.")
        assert result == "J. Smith, M. Jones, R. K. Brown"

    def test_empty(self):
        assert format_authors("") == ""
