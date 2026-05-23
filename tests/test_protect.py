import pytest
from search_citation_mcp.protect import protect, protect_fields, ACRONYMS


class TestProtect:
    def test_protect_known_acronym(self):
        assert protect("The IEEE standard") == "The {IEEE} standard"

    def test_protect_acronym_at_start(self):
        assert protect("CFE publicó la norma") == "{CFE} publicó la norma"

    def test_protect_acronym_at_end(self):
        assert protect("Norma de la CFE") == "Norma de la {CFE}"

    def test_protect_already_braced(self):
        assert protect("La {IEEE} publicó") == "La {IEEE} publicó"

    def test_protect_no_acronym(self):
        assert protect("Sistema fotovoltaico") == "Sistema fotovoltaico"

    def test_protect_multiple_acronyms(self):
        result = protect("IEEE y IEC publicaron la NOM")
        assert "{IEEE}" in result
        assert "{IEC}" in result
        assert "{NOM}" in result

    def test_protect_substring_not_acronym(self):
        assert protect("el ieeeexplore website") == "el ieeeexplore website"

    def test_protect_empty_string(self):
        assert protect("") == ""

    def test_protect_fields_title(self):
        entry = {"title": "IEEE standard for PV systems", "author": "Smith, J."}
        result = protect_fields(entry)
        assert "{IEEE}" in result["title"]
        assert "{PV}" in result["title"]

    def test_protect_fields_journal(self):
        entry = {"journal": "IEEE Trans. Power Electron.", "author": "Smith, J."}
        result = protect_fields(entry)
        assert "{IEEE}" in result["journal"]

    def test_acronyms_list_is_sorted_by_length_desc(self):
        for i in range(len(ACRONYMS) - 1):
            assert len(ACRONYMS[i]) >= len(ACRONYMS[i + 1])
