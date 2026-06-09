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
`PILOTBOOK_VAULT_PATH`.

## Install

    uv sync --all-extras --dev

## Run the server

    PILOTBOOK_VAULT_PATH=/path/to/vault uv run pilotbook-mcp

## Ingest a book

    PILOTBOOK_VAULT_PATH=/path/to/vault uv run pilotbook ingest book.pdf --source "Publisher — Title YEAR"

## Semantic search (`[search]` extra)

### Install

    uv sync --extra search
    # or
    pip install 'pilotbook-mcp[search]'

### What `search_anchorages` does

`search_anchorages` accepts a free-text query and returns ranked anchorage hits
using an embedded vector index over the vault prose.  Use it when you want to
describe a situation or vibe rather than filter by position or structured
attributes:

- "hurricane-hole with all-round protection to wait out a SE gale"
- "sandy beach to land the dinghy and build a campfire"
- "historic First Nations site with a midden to explore"

**When to prefer the structured tools instead:**

| Goal | Tool |
|------|------|
| Anchorages within N nm of a position | `find_anchorages_near` |
| Rank candidates by comfort given a forecast | `rank_anchorages` |
| Fetch full details for a known anchorage | `get_anchorage` |
| Browse available regions/sources | `list_sources` |

### Cache

On first use, `search_anchorages` builds a local embedding index and writes it
to `~/.cache/pilotbook-mcp/<hash>.db` (respects `$XDG_CACHE_HOME`).  The hash
is derived from the vault path; the fingerprint tracks file sizes and mtimes so
the cache self-heals automatically when vault content changes.  Subsequent calls
are instant.

### Results (pilot vault, measured 2026-06-08)

Measured on 20 natural-language queries spanning all seven source regions
(Broughton Archipelago, Desolation Sound, Gulf Islands, Puget Sound, San Juan
Islands, Sunshine Coast, West Coast of Vancouver Island).  Default retriever is
set from the winning mode.

```
retriever     R@1    R@3    R@5    MRR
keyword      0.85   0.95   0.95   0.90
vector       0.60   0.65   0.65   0.64
hybrid       0.70   0.80   0.90   0.79
```

**Keyword BM25 wins** (MRR 0.90 vs hybrid 0.79 vs vector 0.64) on this corpus.
Anchorage prose is rich with distinctive place names, geographic terms and
feature vocabulary that BM25 matches precisely; the queries in the golden set
that mention unique landmarks (spits, lagoons, waterfalls, First Nations
connections) land on the right entry by term overlap alone.  Re-run
`scripts/eval_search.py` if the vault grows materially to verify this holds.
