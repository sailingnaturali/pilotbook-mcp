# Semantic Anchorage Search — Design

**Date:** 2026-06-08
**Status:** Approved (brainstorming) → ready for implementation plan
**Repo:** pilotbook-mcp (with a small upstream addition to vault-search)

## Purpose

Add free-text **semantic** retrieval over the pilot-book anchorage vault to `pilotbook-mcp`,
via a new `search_anchorages` tool backed by the `vault-search` hybrid-retrieval module. This
complements — does not replace — the existing structured/geo tools (`find_anchorages_near`,
`rank_anchorages`, `get_anchorage`, `list_sources`): those answer "3–5 m, good holding,
protected from S, near 49.4°N"; the new tool answers "somewhere quiet to wait out unsettled
weather with a beach to land the dinghy."

## Non-goals

- Replacing or duplicating the structured comfort scoring in `rank_anchorages`.
- Structured filters on the semantic tool (depth/sector/holding) — the agent composes by
  chaining semantic candidates into the existing tools.
- Weighted RRF — if the eval shows hybrid is close but BM25-diluted, that's a follow-on
  enhancement to `vault-search`, not this spec.
- Changing the ingestion pipeline's behavior (index build is lazy at query time, not an
  ingestion step).

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Code acquisition | Make the `vault-search` GitHub repo public (MIT, **no PyPI**); depend on it via a **git source** (uv `[tool.uv.sources]`) pinned to a tag, under a new `[search]` optional extra | One source of truth, npm-style git dependency, zero registry ceremony; base `uvx pilotbook-mcp` stays light (`mcp`+`pyyaml`). Flip to PyPI later only if it gets outside traction (delete the source override). |
| Chunk strategy | `whole_file` (one chunk per anchorage) | Anchorage files are already ~150–320-word coherent units with no internal headings. |
| Index lifecycle | Lazy build, cached, self-healing | Index can't silently go stale; a fresh vault checkout just works. |
| Cache location | XDG: `~/.cache/pilotbook-mcp/<hash-of-vault-path>.db` | Keeps the private vault repo clean of derived artifacts. |
| Tool contract | Pure semantic, rich metadata | One clear responsibility; agent composes with existing tools. |
| `text` payload | Full anchorage body + citation | Owner's own purchased books, private MCP, query-time grounding = legitimate personal use; full body is more useful than a snippet. |
| Retriever mode | Chosen by the eval (hybrid vs vector) | Measured per-vault, not assumed (colregs showed vector can beat hybrid on terse corpora). |

## Architecture

### Upstream: vault-search `mode` param (small, in the vault-search repo)

Add a `mode` parameter to `vault_search.search.search()`:
`mode="hybrid"` (default, current behavior), `"vector"` (KNN only), `"keyword"` (BM25 only).
This lets consumers select the retriever the eval recommends without reimplementing fusion.
Returns `list[SearchHit]` as today. ~10 lines + unit tests. Tagged as a new vault-search
release (e.g. `v0.2.0`) that pilotbook-mcp's git source pins.

### pilotbook-mcp: `src/pilotbook_mcp/search.py`

One focused module, lazily imported so the soft dependency stays soft.

- **`PILOT` profile** — a `vault_search.VaultProfile`:
  - `glob="anchorages/**/*.md"`
  - `front_matter_fields=["name", "region", "source", "source_page", "source_pdf", "lat", "lon"]`
  - `chunk_strategy="whole_file"`
  - `breadcrumb="{name} — {region}"`
  - `citation="{name} ({source}, p.{source_page})"`
- **`AnchorageIndex`** — wraps the cache lifecycle:
  - `cache_path(vault_root)` → `~/.cache/pilotbook-mcp/<sha1(vault_root)>.db`
  - `_fingerprint(vault_root)` → hash of sorted `(relpath, size, mtime_ns)` over matched files
  - `ensure(vault_root)` → opens the cached db; if missing/unreadable or the stored fingerprint
    differs from the current one, rebuilds (chunk → embed → index) and writes the new
    fingerprint into a `meta` table; returns an open `vault_search.Index` + the shared `Embedder`.
  - Build + query run via `asyncio.to_thread(...)` from the async tool handler so the MCP
    event loop is never blocked.
  - The `Embedder` and open `Index` are memoized on the server instance across calls.
- **`search_anchorages(vault_root, query, limit, mode)`** — calls `ensure`, runs
  `vault_search.search(index, embedder, query, limit, mode=mode)`, maps each `SearchHit` to the
  payload below.

### Soft-dependency behavior

`search.py` imports `vault_search` inside a try/except (or a guarded helper). If unavailable:
the `search_anchorages` tool either is not registered, or returns a structured message
`{"error": "semantic search requires: pip install pilotbook-mcp[search]"}`. The other four
tools and server startup are unaffected — mirrors the existing `[ingest]` extra pattern.

## Tool contract

```
search_anchorages(query: str, limit: int = 5) -> {"hits": [Hit, ...]}
```

Each `Hit`:

```json
{
  "name": "Tootoo Cove",
  "region": "Vancouver Island West",
  "lat": 49.366,
  "lon": -126.017,
  "citation": "Tootoo Cove (SalishSeaPilot — West Coast of Vancouver Island 2025, p.74)",
  "score": 0.041,
  "text": "<full anchorage body>"
}
```

- Empty `hits` list when nothing matches — never an error.
- `name`/`lat`/`lon` are exactly the keys needed to chain into `get_anchorage` /
  `rank_anchorages`.
- `lat`/`lon` are parsed back to floats from the string-coerced metadata; if absent/malformed
  they are returned as `null`.

## Data flow

`query` → `AnchorageIndex.ensure(vault_root)` (build if stale) →
`vault_search.search(index, embedder, query, limit, mode)` →
map `SearchHit.chunk.metadata` + `SearchHit.chunk.text` + `SearchHit.score` → `Hit` payload.

Build path (only when stale): matched `*.md` → `chunk_vault(PILOT)` → `Embedder.encode` →
`build_index` → write fingerprint to `meta`.

## Evaluation

- `golden/pilot.yaml`: ~15–20 natural-language anchorage queries, each with `expect` = the
  anchorage `name`(s) that should surface, chosen to exercise semantic gaps (e.g. "quiet spot
  to wait out a southerly with a beach to land the dinghy" → Tootoo Cove; "protected hurricane
  hole deep inlet" → a deep sheltered inlet anchorage).
- A tiny eval script in pilotbook-mcp (e.g. `scripts/eval_search.py`) imports
  `vault_search.eval.run_eval` and calls it with pilotbook-mcp's own `PILOT` profile:
  `run_eval(golden_path, vault_path, PILOT, db_path)` — `run_eval` already accepts a
  `VaultProfile` object, so no CLI profile registration in vault-search is needed. It prints the
  keyword/vector/hybrid R@1/3/5 + MRR table over the real vault.
- The result sets the tool's default `mode`: hybrid if it wins/ties; vector if it clearly
  dominates. The chosen default + the eval table are recorded in the README with the same
  honesty bar as colregs.
- `expect` matches against each hit chunk's `metadata["name"]`.

**Profile ownership (resolved):** the `PILOT` profile is defined once, canonically, in
pilotbook-mcp's `search.py`. Both runtime search and the eval script use that single
definition — no copy in vault-search, no drift.

## Testing (TDD)

- **vault-search `mode`** (vault-search repo): unit tests that `"vector"`/`"keyword"`/`"hybrid"`
  route to the right retriever and return `SearchHit`s.
- **PILOT profile / chunk mapping**: against pilotbook-mcp's existing
  `tests/fixtures/vault/anchorages/` (test-cove, telegraph-harbour) — one chunk per file,
  citation/breadcrumb render correctly, full body preserved in `text`.
- **Index cache + self-heal**: build to a tmp cache → assert query hit; touch a fixture file →
  fingerprint changes → rebuild triggers; missing/corrupt db → rebuilds cleanly.
- **Tool handler**: `search_anchorages` returns the documented payload shape against a tiny
  fixture index; empty query / no match → `{"hits": []}`; soft-dep absent (monkeypatch the
  import) → clear install message; `lat`/`lon` round-trip to floats.
- The pilot golden eval doubles as an integration check (asserts the chosen-mode retriever
  clears a recall floor on the fixture or real vault).

## Error handling

- `vault_search` not installed → tool degrades with `install pilotbook-mcp[search]` guidance;
  server starts; other four tools unaffected.
- Vault unreadable / empty → `{"hits": []}` + a logged warning; no crash.
- First-run fastembed model download needs network; on failure the tool returns a clear
  "embedding model unavailable offline; run once online" message rather than hanging.
- Cache dir not writable → fall back to an in-memory/temp index for the session + logged
  warning (degraded but functional).

## Dependencies

- New optional extra declares the dependency by name:
  `search = ["vault-search>=0.2"]` (pulls fastembed + sqlite-vec transitively). Base install
  unchanged.
- A `[tool.uv.sources]` entry resolves it from the public GitHub repo at a pinned tag, e.g.:
  ```toml
  [tool.uv.sources]
  vault-search = { git = "https://github.com/sailingnaturali/vault-search", tag = "v0.2.0" }
  ```
  No PyPI involved. Publishing to PyPI later is a one-line change (remove the source override).

## Prerequisites (sequenced in the plan, before the pilotbook tool)

1. Add the `mode` param to `vault_search.search.search()` (+ tests) in the vault-search repo.
2. Tag a vault-search release (`v0.2.0`).
3. Make the vault-search GitHub repo **public** (MIT, no secrets) so the git source installs
   with zero auth.
