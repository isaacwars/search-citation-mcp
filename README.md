# Search & Citation MCP

Academic search and IEEE citation engine as an MCP (Model Context Protocol) server. Designed to integrate with coding assistants like [opencode](https://opencode.ai).

**9 tools** that allow an LLM to search papers, validate metadata, generate BibTeX citations, download open-access PDFs, and maintain a `biblatex-ieee` compatible bibliography.

## Install

```bash
git clone https://github.com/isaacwars/search-citation-mcp.git
cd search-citation-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and set optional keys:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `OPENALEX_API_KEY` | No | Improves OpenAlex rate limit |
| `SEMANTIC_SCHOLAR_API_KEY` | No | Enables Semantic Scholar semantic search |
| `UNPAYWALL_EMAIL` | No | Unpaywall API for PDF downloads |
| `BIBLIOGRAPHY_PATH` | No | Path to `.bib` file (default: `./bibliografia.bib`) |
| `EZPROXY_HOST` | No | Institutional EZProxy host |
| `SCIHUB_ENABLED` | No | Sci-Hub as last-resort fallback (`1` to enable) |

## MCP Usage

Add to `opencode.json`:

```json
{
  "mcp": {
    "search-citation": {
      "command": "/path/to/search-citation-mcp/.venv/bin/search-citation-mcp",
      "env": {
        "BIBLIOGRAPHY_PATH": "./bibliografia.bib"
      }
    }
  }
}
```

### MCP Tools

| Tool | Description |
|---|---|
| `search_papers` | Search papers via OpenAlex + Semantic Scholar |
| `add_from_doi` | Add citation by DOI with Crossref → S2 → OA validation |
| `cite_paper` | Generate `.bib` entry without writing to file |
| `add_to_bibliography` | Add manual entry to `.bib` (CFE, NOM, IEC, thesis, datasheets) |
| `find_related_papers` | Find related papers via citation graph + semantic similarity |
| `detect_input` | Detect whether text is a DOI, arXiv, PMID, ISBN, or URL |
| `list_cached` | List recent cached searches |
| `fix_bib` | Fix Title Case, protect acronyms (`{IEEE}`, `{CFE}`) |
| `download_paper` | Download PDF from free sources (OA → S2 → Unpaywall → arXiv) |

## CLI Usage

```bash
search-citation search "photovoltaic" -n 5
search-citation add --doi 10.1016/j.rser.2015.08.042
search-citation cite --doi 10.1016/j.rser.2015.08.042
search-citation related 10.1016/j.rser.2015.08.042 -n 5
search-citation detect "10.1016/j.rser.2015.08.042"
search-citation fix-bib bibliografia.bib --dry-run
search-citation download 10.1016/j.rser.2015.08.042 -o ./pdfs
search-citation cache
```

## Supported BibTeX Entry Types

`article` · `inproceedings` · `book` · `techreport` · `mastersthesis` · `phdthesis` · `manual` · `misc` · `online` · `incollection`

Validated against IEEE schema with required and optional fields per type.

## Tests

```bash
pytest tests/ -v
```

123 unit tests covering acronym protection, BibTeX validation, input detection, `.bib` generation, path safety, caching, and key collision resolution.

## Security

- **stdio** transport — no TCP port, no network exposure
- Path traversal blocked on all file operations
- Credentials via environment variables only, never hardcoded
- Zero personal data in source code
- PDF and `.bib` output confined to project workspace

## License

APACHE 2.0 
