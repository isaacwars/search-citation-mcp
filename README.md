# Search & Citation MCP

[![PyPI](https://img.shields.io/pypi/v/search-citation-mcp)](https://pypi.org/project/search-citation-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/search-citation-mcp)](https://pypi.org/project/search-citation-mcp/)
[![License](https://img.shields.io/pypi/l/search-citation-mcp)](LICENSE)

MCP server for academic paper search and IEEE citation generation. Searches across 3 sources in parallel (OpenAlex + Crossref + Semantic Scholar), generates `biblatex-ieee` BibTeX, validates entries, downloads PDFs, and maintains your bibliography — all through 9 LLM-accessible tools.

## Install

```bash
pip install search-citation-mcp
```

No config required. Creates `./bibliografia.bib` on first citation.

## Usage

### MCP Server

Add to any MCP client config:

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

Config files by client:

| Client | File |
|---|---|
| Claude Desktop | `claude_desktop_config.json` |
| Cursor | `.cursor/mcp.json` |
| Antigravity | `.antigravity/mcp.json` |
| Gemini CLI | `~/.gemini/settings.json` |
| opencode | `opencode.json` |
| Cline | `.cline/mcp.json` |
| Continue | `~/.continue/config.json` |

HTTP mode for multi-client setups:

```json
{
  "mcpServers": {
    "search-citation": {
      "command": "uvx",
      "args": ["search-citation-mcp", "--transport", "streamable-http"],
      "env": { "MCP_PORT": "8000" }
    }
  }
}
```

### CLI

```bash
search-citation search "photovoltaic harmonics" -n 10
search-citation add --doi 10.1016/j.rser.2015.08.042
search-citation cite --doi 10.1016/j.rser.2015.08.042
search-citation related 10.1016/j.rser.2015.08.042 -n 5
search-citation detect "10.1016/j.rser.2015.08.042"
search-citation fix-bib bibliografia.bib --dry-run
search-citation download 10.1016/j.rser.2015.08.042 -o ./pdfs
search-citation cache
```

## Tools

| Tool | Description |
|---|---|
| `search_papers` | Parallel search via OpenAlex + Crossref + Semantic Scholar |
| `add_from_doi` | Add citation by DOI (Crossref → S2 → OpenAlex pipeline) |
| `cite_paper` | Generate `.bib` entry without writing to file |
| `add_to_bibliography` | Add manual entry for sources without DOI |
| `find_related_papers` | Related papers via citation graph + semantic similarity |
| `detect_input` | Detect if text is a DOI, arXiv, PMID, ISBN, URL, or title |
| `list_cached` | List recent cached searches |
| `fix_bib` | Fix Title Case, protect acronyms, add datasheet notes |
| `download_paper` | Download PDF from OA sources (with Sci-Hub fallback) |

## Configuration

Optional environment variables:

```bash
OPENALEX_API_KEY=           # Better rate limits
SEMANTIC_SCHOLAR_API_KEY=   # Enables third search source
CROSSREF_MAILTO=            # Crossref polite pool
UNPAYWALL_EMAIL=            # PDF downloads via Unpaywall
BIBLIOGRAPHY_PATH=          # Custom .bib path (default: ./bibliografia.bib)
EZPROXY_HOST=               # Institutional proxy (e.g. bibliotecabuap.elogim.com)
SCIHUB_ENABLED=1            # Enable Sci-Hub as last-resort PDF source
MCP_HOST=127.0.0.1          # HTTP transport host
MCP_PORT=8000               # HTTP transport port
```

## BibTeX Types

`article` · `inproceedings` · `book` · `techreport` · `mastersthesis` · `phdthesis` · `manual` · `misc` · `online` · `incollection`

All validated against IEEE schema with required and optional fields. Auto-protects acronyms (`{IEEE}`, `{CFE}`, `{MATLAB}`) and converts month names (English/Spanish).

## Development

```bash
git clone https://github.com/isaacwars/search-citation-mcp.git
cd search-citation-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest tests/ -v        # 123 tests
```

## Security

- stdio transport by default — no network exposure
- All credentials via environment variables, never hardcoded
- Path traversal blocked on every file operation
- Output confined to workspace directory

## License

Apache 2.0 with Commons Clause — see [LICENSE](LICENSE)
