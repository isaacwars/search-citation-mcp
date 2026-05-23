import pytest
from search_citation_mcp.generate import (
    from_fields, validate_fields, from_crossref_data, from_doi, SCHEMA,
    _make_key,
)


class TestSchema:
    def test_all_types_exist(self):
        expected = {
            "article", "inproceedings", "book", "incollection",
            "techreport", "mastersthesis", "phdthesis",
            "manual", "misc", "online",
        }
        assert set(SCHEMA.keys()) == expected

    def test_article_required(self):
        assert SCHEMA["article"]["required"] == ["author", "title", "journal", "year"]

    def test_manual_minimal_required(self):
        assert SCHEMA["manual"]["required"] == ["title"]

    def test_misc_no_required(self):
        assert SCHEMA["misc"]["required"] == []


class TestFromFields:
    def test_article_minimal(self):
        entry = from_fields("article", {
            "author": "Smith, John",
            "title": "A Study of PV Systems",
            "journal": "IEEE Trans.",
            "year": "2023",
        })
        assert "@article{" in entry
        assert "smith2023" in entry.lower() or "Smith2023" in entry
        assert "author = {Smith, John}" in entry
        # protect_fields wraps known acronyms like PV
        assert "A Study of" in entry

    def test_article_with_all_fields(self):
        entry = from_fields("article", {
            "author": "Doe, Jane",
            "title": "Harmonic Analysis",
            "journal": "IEEE Trans. Power Del.",
            "year": "2020",
            "volume": "35",
            "number": "4",
            "pages": "100--120",
            "month": "6",
            "doi": "10.1109/test.2020",
            "url": "https://example.com",
            "note": "Test entry",
            "key": "harmonic2020",
        })
        assert "harmonic2020" in entry
        assert "volume = {35}" in entry
        assert "number = {4}" in entry
        assert "pages = {100--120}" in entry
        assert "doi = {10.1109/test.2020}" in entry

    def test_month_normalized(self):
        entry = from_fields("article", {
            "author": "Smith, John",
            "title": "Test",
            "journal": "IEEE",
            "year": "2020",
            "month": "January",
        })
        assert "month = {1}" in entry

    def test_missing_required_raises(self):
        with pytest.raises(ValueError, match="Falta"):
            from_fields("article", {
                "author": "Smith, John",
                "title": "Test",
            })

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="no reconocido"):
            from_fields("patent", {"number": "123"})

    def test_manual_minimal(self):
        entry = from_fields("manual", {
            "title": "PQ3100 Power Quality Analyzer",
            "note": "Datasheet",
        })
        assert "@manual{" in entry
        assert "title = {PQ3100 Power Quality Analyzer}" in entry
        assert "note = {Datasheet}" in entry

    def test_custom_key(self):
        entry = from_fields("misc", {
            "title": "Some Page",
            "url": "https://example.com",
            "key": "myref2024",
        })
        assert "myref2024" in entry

    def test_schema_warns_on_unknown_fields(self):
        with pytest.warns(UserWarning, match="no reconocidos"):
            from_fields("article", {
                "author": "Smith, John",
                "title": "Test",
                "journal": "IEEE",
                "year": "2020",
                "unknown_field": "value",
            })

    def test_techreport(self):
        entry = from_fields("techreport", {
            "author": "{Comisión Federal de Electricidad}",
            "title": "Especificación CFE L0000-01",
            "institution": "CFE",
            "year": "2020",
        })
        assert "@techreport{" in entry
        assert "institution = {CFE}" in entry

    def test_inproceedings(self):
        entry = from_fields("inproceedings", {
            "author": "Smith, J. and Jones, K.",
            "title": "PV Grid Integration",
            "booktitle": "Proc. IEEE PVSC",
            "year": "2019",
        })
        assert "@inproceedings{" in entry
        assert "Proc." in entry
        assert "IEEE" in entry

    def test_book(self):
        entry = from_fields("book", {
            "author": "Rashid, Muhammad H.",
            "title": "Power Electronics Handbook",
            "publisher": "Academic Press",
            "year": "2017",
        })
        assert "@book{" in entry
        assert "publisher = {Academic Press}" in entry


class TestValidateFields:
    def test_valid_article(self):
        errors = validate_fields("article", {
            "author": "Smith, J.",
            "title": "Test",
            "journal": "IEEE",
            "year": "2020",
        })
        assert errors == []

    def test_missing_field(self):
        errors = validate_fields("article", {
            "author": "Smith, J.",
            "title": "Test",
        })
        assert len(errors) > 0
        assert any("journal" in e for e in errors)

    def test_unknown_type(self):
        errors = validate_fields("patent", {})
        assert len(errors) == 1
        assert "no reconocido" in errors[0].lower()


class TestFromCrossrefData:
    def test_article(self):
        data = {
            "type": "article",
            "authors": ["Smith, John", "Doe, Jane"],
            "title": "A Study of PV Systems.",
            "journal": "Renewable Energy",
            "volume": 150,
            "year": 2023,
            "doi": "10.1016/j.renene.2023.01.001",
            "pages": "100-120",
            "publication_date": "2023-01-15",
        }
        entry = from_crossref_data(data)
        assert "@article{" in entry
        assert "author = {Smith, John and Doe, Jane}" in entry
        assert "journal = {Renewable Energy}" in entry
        assert "pages = {100--120}" in entry
        assert "month = {1}" in entry

    def test_unknown_type_falls_back_to_misc(self):
        data = {
            "type": "dataset",
            "authors": ["Smith, John"],
            "title": "Research Data",
            "year": 2023,
        }
        entry = from_crossref_data(data)
        assert "@misc{" in entry


class TestMakeKey:
    def test_normal_author(self):
        data = {"author": "Garcia Marquez, Gabriel", "year": "2023"}
        key = _make_key(data, "article")
        assert key == "marquez2023"

    def test_no_author_uses_type(self):
        data = {"year": "2023"}
        key = _make_key(data, "book")
        assert key == "book2023"
