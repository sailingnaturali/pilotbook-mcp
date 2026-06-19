# Evidence-quote confirmation for controlling_depth_m — design

**Date:** 2026-06-18
**Status:** approved (design); implementation pending
**Repo:** `pilotbook-mcp`
**Supersedes:** the confirmation mechanism in `2026-06-18-backfill-controlling-depth-design.md`
and the ingest-time extraction added in `2026-06-18-draft-aware-clearance-design.md`
(Tasks 7 & 9 there).

## Problem

A live dry-run of `pilotbook backfill-depths` on the Gulf Islands book (113 anchorages)
populated **0**, dropping all 5 LLM proposals — and the LLM's values were *correct*
(Anderson Cove 1.8 m, Pirates Cove 2 m, Roche Cove 0.5 m). The **regex confirm** is the
bottleneck: the real prose can't be matched by a digit-based regex.

- Parentheticals break contiguous patterns: "vessels drawing 1.8 metres **(six feet)** or
  less can enter".
- Numbers are spelled out: "keels that **draw two metres** or more", "drawing **less than
  half a metre**".

These are the dominant style, not edge cases. Patching the regex (strip parentheticals,
parse "two"/"half a"/fractions) is brittle and endless. The confirmation *mechanism* is
wrong for this prose.

## Decision (settled in brainstorming)

- **Pivot to evidence-quote confirmation** (the pattern already used by `ingest/audit.py`):
  the LLM returns the verbatim phrase it read the depth from; we confirm that phrase is a
  literal substring of the prose. The model can't fabricate a real quote, so
  anti-hallucination holds, while spelled-out numbers and parentheticals no longer matter.
- **The backfill is the sole populator** of `controlling_depth_m`. The ingest-time
  extraction is removed; the brittle regex is deleted.

## 1. Remove the regex + ingest-time path

The `Anchorage.controlling_depth_m` field, its exposure in `get_anchorage`, and the
runtime `keel_clearance` verdict all **stay** — only how the field gets *populated*
changes. Remove:

- **`src/pilotbook_mcp/ingest/extract.py`**: delete `controlling_depth_m` from the
  `record_anchorage` tool schema and the sentence about it in `_INSTRUCTIONS`. The big
  extractor no longer touches the field. Remove
  `tests/ingest/test_extract.py::test_extract_schema_includes_controlling_depth`.
- **`src/pilotbook_mcp/ingest/cli.py` `run_ingest`**: remove the
  `confirm_controlling_depth(a)` call, the `depth_reviews` accumulator, and the
  controlling-depth review lines in the summary. (Reverts the ingest-time confirm.)
- **`src/pilotbook_mcp/ingest/confirm.py`**: delete `find_controlling_depths`, the
  `_PATTERNS`/`_NUM`/`_UNIT`/`_DEPTH`/`_FACTOR`/`_TOLERANCE_M` regex machinery, and the
  old `confirm_controlling_depth(anchorage)` validator. Replace with the quote checker
  (section 3). Remove the now-obsolete regex tests in `tests/ingest/test_confirm.py`.

## 2. Proposer returns an evidence quote

`src/pilotbook_mcp/ingest/depth_propose.py`:

- Add an `evidence` string to `PROPOSE_TOOL`'s input schema: "the verbatim phrase from the
  prose that states this approach/entrance depth". Instruct the model to quote the exact
  source phrase (do not paraphrase). `required` becomes `["has_controlling_depth"]`
  (unchanged — `controlling_depth_m` and `evidence` are conditional).
- `propose_controlling_depth(prose, *, client, model) -> tuple[float | None, str | None]`
  now returns `(depth_m, evidence)`. It returns `(None, None)` unless ALL of:
  `has_controlling_depth` is true, `controlling_depth_m` is int/float, and `evidence` is a
  non-empty string. (No usable quote ⇒ unconfirmable ⇒ treat as no proposal.)

## 3. Quote confirmation

In `src/pilotbook_mcp/ingest/confirm.py` (module repurposed to quote-confirmation):

```python
def _normalise(text: str) -> str:
    return " ".join((text or "").split()).casefold()

_UNIT_TOKEN = re.compile(r"\b(metres?|meters?|fathoms?|feet|foot|ft)\b", re.I)

def quote_confirms(prose: str, evidence: str) -> bool:
    """True if the LLM's evidence quote is a real, depth-bearing substring of the prose."""
    if not evidence:
        return False
    if not _UNIT_TOKEN.search(evidence):   # must be a depth citation, not arbitrary text
        return False
    return _normalise(evidence) in _normalise(prose)
```

- Whitespace-normalised + casefolded substring match → robust to wrapping/case while still
  proving the phrase is genuinely in the prose.
- The unit-token requirement ensures the quote is a depth statement (a model can't satisfy
  it by quoting an unrelated sentence).
- Deliberately **not** required: that the quote contain the proposed digit — that
  reintroduces the spelled-out-number brittleness. Entrance-vs-anchoring judgement and
  number-reading stay the LLM's responsibility; this function only blocks hallucinated
  citations.

## 4. Backfill wiring

`run_backfill_depths` (shape unchanged — dry-run default, `--source`/`--all`/`--vault`/
`--apply`/`--model`, resumable, skips already-set):

```python
depth, evidence = propose_controlling_depth(a.prose, client=client, model=model)
if depth is None:
    unknown += 1
    continue
if quote_confirms(a.prose, evidence):
    a.controlling_depth_m = depth
    populated.append(f"{a.name} → {depth} m  «{evidence}»")
    if apply:
        write_anchorage(v.root, a)
else:
    dropped.append(f"{a.name}: evidence quote not found in prose (proposed {depth} m)")
```

The dropped/populated lines include the evidence quote so the dry-run report is
eyeball-able for correctness.

## 5. Testing

- **`quote_confirms`** (`tests/ingest/test_confirm.py`, rewritten): real-prose positive
  ("vessels drawing 1.8 metres (six feet) or less can enter" with the same phrase as
  evidence → True); whitespace/case-insensitive match → True; evidence not a substring →
  False; evidence present but no unit token → False; empty evidence → False.
- **Proposer** (`tests/ingest/test_depth_propose.py`, updated): fake client returns
  `{has_controlling_depth, controlling_depth_m, evidence}` → `(depth, evidence)`;
  flag-false → `(None, None)`; flag-true but missing number → `(None, None)`; flag-true +
  number but missing/empty evidence → `(None, None)`. Schema includes `evidence`.
- **Backfill** (`tests/ingest/test_cli.py`, updated): fake client returns an evidence
  quote that IS in the fixture prose → populated under `--apply`, nothing under dry-run;
  a quote that is NOT in the prose → dropped, stays None; already-set record skipped.
- **Removals**: `test_extract_schema_includes_controlling_depth`; all
  `find_controlling_depths` / old `confirm_controlling_depth` regex tests.

## 6. Operational run (unchanged workflow, after merge)

`set -a; source ~/.hermes/.env; set +a; export PILOTBOOK_VAULT_PATH=…/pilotbook-vault`,
then dry-run per book (now showing each populated value with its evidence quote), eyeball,
`--apply`. Commit the populated records in the separate pilotbook-vault repo. The npm
release + Pi redeploy remain the separate outbound step.

## Out of scope

- Tide-correction of the clearance verdict (still deferred).
- Re-running ingest on the books (not needed — the field is populated by the backfill over
  existing prose).
- Spelled-out-number parsing (intentionally avoided — the quote mechanism makes it
  unnecessary).

## Defaults / notes

- Evidence match is whitespace-normalised + casefolded substring; no fuzzy matching
  (fuzzy would weaken the anti-hallucination guarantee).
- `propose_controlling_depth`'s return type changes from `float | None` to
  `tuple[float | None, str | None]` — the only caller is `run_backfill_depths`.
