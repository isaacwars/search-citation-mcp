# Search & Citation MCP

Academic search and IEEE citation engine as an MCP (Model Context Protocol) server. Designed to integrate with AI coding assistants (Claude Desktop, Cursor, opencode) and MCP daemons.

**9 tools** that allow an LLM to search papers across 3 sources (OpenAlex + Crossref + Semantic Scholar), validate metadata, generate `biblatex-ieee` BibTeX citations, download open-access PDFs, and maintain a bibliography.

[![PyPI version](https://img.shields.io/pypi/v/search-citation-mcp)](https://pypi.org/project/search-citation-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/search-citation-mcp)](https://pypi.org/project/search-citation-mcp/)
[![License](https://img.shields.io/pypi/l/search-citation-mcp)](https://github.com/isaacwars/search-citation-mcp/blob/main/LICENSE)

## Install

```bash
pip install search-citation-mcp
```

## Quick Start (uvx — zero install)

Add to your MCP client configuration:

### Any MCP Client (Claude Desktop, Cursor, Antigravity, Gemini CLI, opencode, Cline, Continue)

```json
{
  "mcpServers": {
    "search-citation": {
      "command": "uvx",
      "args": ["search-citation-mcp"]
    }
  }
}
```

Config file locations:

| Client | Config File |
|---|---|
| Claude Desktop | `claude_desktop_config.json` |
| Cursor | `.cursor/mcp.json` |
| Antigravity (Google) | `.antigravity/mcp.json` or `mcp.json` |
| Gemini CLI | `~/.gemini/settings.json` |
| opencode | `opencode.json` |
| Cline (VSCode) | `.cline/mcp.json` |
| Continue (VSCode/JetBrains) | `~/.continue/config.json` |

### HTTP Mode (multi-client / daemon)

Expose the server on the network for multiple simultaneous clients:

```json
{
  "mcpServers": {
    "search-citation": {
      "command": "uvx",
      "args": ["search-citation-mcp", "--transport", "streamable-http"],
      "env": {
        "MCP_HOST": "0.0.0.0",
        "MCP_PORT": "8000"
      }
    }
  }
}
```

## Configuration (.env)

Optional — set environment variables in your MCP client config or create a `.env` file:

```bash
OPENALEX_API_KEY=           # Optional: better rate limits
SEMANTIC_SCHOLAR_API_KEY=   # Enables semantic search (third source)
CROSSREF_MAILTO=            # Optional: Crossref polite pool
UNPAYWALL_EMAIL=            # Enables Unpaywall PDF downloads
BIBLIOGRAPHY_PATH=./bibliografia.bib
EZPROXY_HOST=               # Optional: institutional proxy
SCIHUB_ENABLED=             # Optional: set to 1 to enable Sci-Hub fallback
```

## MCP Tools

| Tool | Description |
|---|---|
| `search_papers` | Search papers via OpenAlex + Crossref + Semantic Scholar (3 sources in parallel) |
| `add_from_doi` | Add citation by DOI with Crossref → S2 → OpenAlex validation pipeline |
| `cite_paper` | Generate `.bib` entry without writing to file |
| `add_to_bibliography` | Add manual entry to `.bib` (CFE, NOM, IEC, thesis, datasheets) |
| `find_related_papers` | Find related papers via citation graph + semantic similarity |
| `detect_input` | Detect whether text is a DOI, arXiv, PMID, ISBN, or URL |
| `list_cached` | List recent cached searches |
| `fix_bib` | Fix Title Case, protect acronyms (`{IEEE}`, `{CFE}`), add datasheet notes |
| `download_paper` | Download PDF from free sources (OA → S2 → Unpaywall → arXiv) |

## CLI Usage

```bash
# Install with pip
pip install search-citation-mcp

# Search
search-citation search "photovoltaic" -n 5

# Add citation by DOI
search-citation add --doi 10.1016/j.rser.2015.08.042

# Generate citation without writing
search-citation cite --doi 10.1016/j.rser.2015.08.042

# Find related papers
search-citation related 10.1016/j.rser.2015.08.042 -n 5

# Detect input type
search-citation detect "10.1016/j.rser.2015.08.042"

# Fix and validate .bib files
search-citation fix-bib bibliografia.bib --dry-run

# Download PDF
search-citation download 10.1016/j.rser.2015.08.042 -o ./pdfs

# View cached searches
search-citation cache
```

## Supported BibTeX Entry Types

`article` · `inproceedings` · `book` · `techreport` · `mastersthesis` · `phdthesis` · `manual` · `misc` · `online` · `incollection`

Validated against IEEE schema with required and optional fields per type.

## Development

```bash
git clone https://github.com/isaacwars/search-citation-mcp.git
cd search-citation-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest tests/ -v
```

## Security

- **stdio** transport by default — no TCP port, no network exposure
- Path traversal blocked on all file operations
- Credentials via environment variables only, never hardcoded
- Zero personal data in source code
- PDF and `.bib` output confined to project workspace

## License

Apache 2.0 with Commons Clause — see [LICENSE](LICENSE)
