# pilotbook-mcp

MCP server that turns purchased pilot-book PDFs into a private markdown anchorage
vault and recommends the most comfortable overnight anchorage by joining each
anchorage's wind/swell exposure against a forecast.

**Two halves:**
- **Runtime MCP** — loads a markdown vault, exposes `find_anchorages_near`,
  `get_anchorage`, `rank_anchorages`, `list_sources`.
- **Ingestion CLI** (`pilotbook`) — archives + retitles source PDFs and extracts
  anchorage records via the Claude API.

This engine ships **no book content**. Point it at a vault with
`PILOTBOOK_VAULT_PATH`. See `docs/` in the planning repo for the design spec.

## Install

    uv sync --all-extras --dev

## Run the server

    PILOTBOOK_VAULT_PATH=/path/to/vault uv run pilotbook-mcp

## Ingest a book

    PILOTBOOK_VAULT_PATH=/path/to/vault uv run pilotbook ingest book.pdf --source "Publisher — Title YEAR"
