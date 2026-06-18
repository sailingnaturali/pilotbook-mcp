# Draft-aware keel-clearance flag — design

**Date:** 2026-06-18
**Status:** approved (design); implementation pending
**Repo:** `pilotbook-mcp` (published, generic plugin)

## Problem

The pilot-book tools take position, radius, and forecast — there is **no draft input
anywhere**. Depth/entrance caveats (e.g. Anderson Cove's "vessels drawing 1.8 m or
less") live only in prose and are applied by hand, if at all. Nothing guarantees a
shallow-entrance anchorage gets flagged for *this* vessel's draft. We want the tools to
surface a keel-clearance verdict so a too-thin entrance can't pass unremarked.

## Scope decisions (settled in brainstorming)

1. **Draft source — optional `draft_m` parameter.** The plugin is generic; it does not
   read SignalK or bake in a vessel constant. The caller/agent passes the vessel draft
   (Naturali = 1.37 m, from SignalK `design.draft`).
2. **Controlling-depth extraction — LLM proposes, deterministic/human confirms.** A
   number survives only if the Claude extractor and a literal-text regex rule agree;
   otherwise it stays `None` (= unknown), never a guess. Keel-safety values are not
   trusted to an LLM alone.
3. **Verdict semantics — flag only, never reorders.** Tides change entrance
   accessibility, so a static chart-datum depth must not exclude or down-rank an
   anchorage. Each result is annotated; ordering stays comfort-based.
4. **Tide handling — chart datum + explicit caveat (v1).** The flag compares draft vs
   controlling depth at chart datum and labels it plainly; the human/agent adds tide.
   Tide-correction is a deferred follow-on.

## 1. Data model — one new field

Add to `Anchorage` (`src/pilotbook_mcp/models.py`):

```python
controlling_depth_m: float | None = None   # charted least depth on the approach/entrance (bar, sill, shoal)
```

- Distinct from existing `depth_min_m`/`depth_max_m` (anchoring depth — where you drop
  the hook). `controlling_depth_m` is the constraining shoal you must cross to get in.
- `None` = not recorded. Round-trips through markdown frontmatter like every other
  field (the `to_markdown`/`from_markdown` drop-None logic already handles it).
- Surfaces automatically in `get_anchorage` (add to the record dict in `tools.py`).

**Explicitly out of scope:** no gating on `depth_min_m`. If draft exceeds the shallow
end of the anchoring range, you anchor in the deeper part — the entrance bar is the
grounding risk, so `controlling_depth_m` is the only safety gate v1 adds.

## 2. Ingest — LLM proposes, deterministic confirms

- Add `controlling_depth_m` to the `record_anchorage` tool schema in
  `src/pilotbook_mcp/ingest/extract.py`, with instructions to fill it **only** from
  explicit approach/entrance-depth language, never from anchoring depth.
- New deterministic confirm step: regex-scan the prose for the known phrasings and
  validate the LLM's number against what the text literally states:
  - `drawing X m(etres) or less`
  - `controlling depth X m`
  - `bar (dries|carries) X m`
  - `entrance … X m`
  - (extensible list; capture metres, allow "m"/"metres"/"meters")
- Decision per record:
  - LLM number **matches** a literal text figure → keep.
  - LLM number present but **not found / mismatched** in prose → drop to `None` and
    emit an audit line for manual review (mirror the existing `ingest/audit.py`
    pattern).
  - LLM left it absent but regex finds a figure → record it (regex-sourced) and audit
    for review.
- Net: a value survives only on agreement; anything uncertain stays `None`.

## 3. Tool surface — optional `draft_m`

Add two optional params to the discovery/verdict tools:

- `draft_m: float | None` — vessel draft in metres.
- `keel_safety_margin_m: float = 0.5` — required under-keel clearance.

Applied to:

- **`find_anchorages_near`** — each returned anchorage gains a `keel_clearance` block.
- **`assess_anchorage`** — same block on each ranked candidate (the composed
  "where do we anchor tonight" flow).

Unchanged:

- **`rank_anchorages`** stays comfort-only (ranking does not thread draft).
- **`get_anchorage`** simply exposes the new `controlling_depth_m` field.

When `draft_m` is omitted, output is byte-for-byte identical to today — purely
additive, safe for other users of the published plugin. Update the MCP `inputSchema`
entries in `server.py` for the two affected tools.

## 4. The clearance verdict (flag only, never reorders)

With `draft_m` supplied, each anchorage gets:

```json
"keel_clearance": {
  "state": "clear | tight | unsafe_at_datum | unknown",
  "controlling_depth_m": 1.8,
  "draft_m": 1.37,
  "note": "1.8 m at chart datum vs 1.37 m draft — add tide height before trusting."
}
```

State logic (let `d = controlling_depth_m`, `draft`, `margin`):

| Condition | state | note |
|-----------|-------|------|
| `d is None` | `unknown` | "Entrance depth not recorded; verify locally." |
| `d >= draft + margin` | `clear` | "{d} m at chart datum vs {draft} m draft — add tide height before trusting." |
| `draft <= d < draft + margin` | `tight` | same datum caveat, framed as marginal clearance |
| `d < draft` | `unsafe_at_datum` | "{d} m at chart datum is below {draft} m draft — at chart datum; a rising tide may open it." |

Every note carries the **"at chart datum — add tide height"** caveat. Ordering is
untouched.

Implementation lives in a new pure module (`src/pilotbook_mcp/clearance.py`) with a
single `keel_clearance(controlling_depth_m, draft_m, margin_m) -> dict` function, called
by `tools.find_anchorages_near` and `assess.assess_anchorage`. Keeping it pure and
isolated makes the four states trivially testable without I/O.

## 5. Testing (TDD — failing tests first)

- `tests/test_models.py` — round-trip the new `controlling_depth_m` field through
  markdown (present and absent).
- `tests/test_clearance.py` (new) — the four states, margin boundaries (exactly at
  `draft`, exactly at `draft + margin`), and `None` → unknown.
- `tests/test_tools.py` — `find_anchorages_near` output is unchanged when `draft_m`
  omitted; `keel_clearance` block present and correct when supplied.
- `tests/test_assess.py` — `assess_anchorage` annotates each candidate; ordering
  unchanged vs the comfort-only baseline.
- `tests/ingest/test_extract.py` (and/or a new ingest confirm test) — regex-confirm
  pass: matching number kept, mismatched/unfindable dropped to `None` + audited,
  regex-only figure recorded + audited.

## 6. Deferred follow-on (out of scope)

Tide-aware clearance: `assess_anchorage` pulls the overnight tide curve from
currents-mcp and computes worst-case (low-water) clearance during the stay. Slots in
beside the already-noted "tide-corrected scope tool." Not in v1 — would couple
pilotbook to currents-mcp.

## Defaults chosen (revisit if needed)

- Under-keel safety margin **0.5 m**, configurable per call via `keel_safety_margin_m`.
- `rank_anchorages` left comfort-only (draft not threaded through it).
