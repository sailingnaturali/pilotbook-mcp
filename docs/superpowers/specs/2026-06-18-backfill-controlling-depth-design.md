# Backfill controlling_depth_m across the vault — design

**Date:** 2026-06-18
**Status:** approved (design); implementation pending
**Repo:** `pilotbook-mcp`
**Builds on:** `2026-06-18-draft-aware-clearance-design.md` (the field + clearance verdict already shipped)

## Problem

The draft-aware keel-clearance feature is live, but **every anchorage reads `unknown`** —
no record has `controlling_depth_m` populated. A survey of the real vault (673 anchorages
across 7 Salish Sea Pilot books) found that the regex patterns shipped with the confirm
pass (`drawing X or less`, `controlling depth X`, `bar carries X`) match **zero** real
prose. The author's actual entrance-depth idioms are different:

- "the narrow eastern entrance **shallows to 1.1 metres** (less than four feet) **above zero tide**"
- "**drawing more than 2m** should enter on rising tide"
- "Depths in the entrance in places **drop to 0.2 fathoms** (about one foot) **at zero tide**"
- "entrance channel **dries near half tide**" / "shallow approach … suitable only for shoal-draft"

The dominant pattern is **"shallows/drops/falls to X [metres|fathoms|feet] … at/above zero
tide"** — a charted least depth at datum — with mixed units and frequent qualitative-only
descriptions. The hazard: prose like "anchor in 5–6 metres at zero tide" is an *anchoring*
depth, not an entrance one, and misreading one as the other is the exact failure a
keel-safety field must avoid.

## Scope (settled in brainstorming)

- **Whole vault** — all 673 anchorages across all 7 books.
- **Method — LLM proposes, regex confirms.** A focused single-field LLM pass judges the
  entrance-vs-anchoring distinction (which regex does poorly) from each anchorage's
  existing prose; a rebuilt deterministic regex then confirms the proposed number is
  literally present in the prose before it is kept. This is the same "LLM proposes,
  deterministic confirms" pattern the shipped clearance design already chose.
- **Rejected:** full `--force` re-ingest (re-runs LLM extraction on *every* field and
  would clobber curated exposure audits) and pure hand-fill (intractable at 673).

## 1. New CLI command: `pilotbook backfill-depths`

Operates on the **existing** vault; touches only `controlling_depth_m`.

```
pilotbook backfill-depths [--source "<book>" | --all] [--vault <path>] [--apply]
```

- Dry-run by default (reports what it *would* set); `--apply` writes.
- Resumable — skips records that already have `controlling_depth_m` set.
- `--source` limits to one book; `--all` walks every book.
- Reuses `cli._make_client()` for the Anthropic client and the existing
  `Vault.load` / `write_anchorage` round-trip, so every other curated field is preserved.
- Wired into `cli.main()` as a new subparser alongside `ingest`/`review`/`index`/`audit`.

## 2. The focused LLM proposer

A new single-purpose tool call, separate from the big `record_anchorage` extractor.
Lives in `src/pilotbook_mcp/ingest/depth_propose.py` (its own module — one clear job).

- Input: one anchorage's prose. Output: `controlling_depth_m` in metres, or null.
- Forced structured tool use (`propose_controlling_depth`), instruction block marked for
  prompt caching (identical across every record).
- Its entire job is the **entrance-vs-anchoring judgment**. The instruction is built from
  the real idioms with explicit negative examples:
  - Positive: "shallows/drops/falls to X … at/above zero tide", "drawing more than X m →
    enter on rising tide", "entrance … X metres … zero tide".
  - Negative (return null): "anchor in 5–6 metres at zero tide" (anchoring depth),
    "depths of 5–7 metres inside" (interior depth), pure "dries near half tide" with no
    metre figure.
  - Convert feet/fathoms to metres; report metres.
- Signature: `propose_controlling_depth(prose: str, *, client, model="claude-sonnet-4-6") -> float | None`.
- Tested with a fake client (the `tests/ingest/test_extract.py` pattern); no live API in tests.

## 3. Rebuilt confirm regex + division of labor

The regex's job shifts to **anti-hallucination only**: confirm the LLM's number is
literally present in the prose as a depth. The **LLM owns the entrance-vs-anchoring
semantics**; the regex does not re-gate on context (keeps recall up).

Changes to `src/pilotbook_mcp/ingest/confirm.py`:

- Rebuild `find_controlling_depths` patterns around the real idioms, capturing the depth
  figure in metres/fathoms/feet:
  - `(?:shallows?|shoals?|drops?|falls?)\s+to\s+<DEPTH>`
  - `drawing\s+(?:more than\s+|up to\s+)?<DEPTH>`
  - `depths?\s+(?:to|of)\s+<DEPTH>` (broad — the LLM has already decided this is the
    entrance figure; the regex only proves the number is in the text)
  - keep the prior precise forms (`controlling depth`, `bar carries`, `drawing X or less`,
    `entrance … sill/bar/least depth`) — they do no harm and cover other books.
  - `<DEPTH>` matches a number followed by `m|metre(s)|meter(s)|fathom(s)|f(ee|oo)t|'`.
- Add unit conversion: a found figure is normalised to metres (fathom ×1.8288, foot
  ×0.3048) before comparison. `find_controlling_depths` returns metres.
- Confirm contract is unchanged in shape but tolerance widens for unit-rounding:
  - LLM proposed a value AND a found (converted-to-metres) figure is within tolerance →
    keep. Tolerance `0.15 m` (was 0.05) to absorb fathom/foot rounding.
  - LLM proposed a value, no matching figure in prose → set None, audit "not found".
  - LLM returned null → stays `unknown` (no figure to record).
- The regex-only fallback branch (record `min(found)` when the model left it blank) is
  retained but is **not** the backfill's primary path — the backfill always has an LLM
  proposal, so that branch only fires for the original ingest-time use.

## 4. Write-back + audit report

`run_backfill_depths` loops the in-scope records:

1. Skip if `controlling_depth_m` already set.
2. `proposed = propose_controlling_depth(a.prose, client=...)`.
3. Assign `a.controlling_depth_m = proposed`, then `confirm_controlling_depth(a)` (which
   may drop it to None and return an audit note).
4. If a value survived: in `--apply` mode, `write_anchorage`; collect a "populated" line.
5. If dropped: collect a "dropped" line. If null: counts as "unknown".

End-of-run summary (dry-run prints the same without writing):

```
Backfilled <N> anchorages (<M> populated, <K> dropped-unconfirmed, <rest> unknown). Vault: <root>
  populated: Anderson Cove → 1.8 m
  dropped:   Foo Cove → LLM proposed 2.0 m, not found in prose
```

One bad record (API or parse error) logs a warning and continues — never aborts the batch
(mirrors `run_ingest`).

## 5. Testing

- **Regex** (`tests/ingest/test_confirm.py` additions):
  - Real-idiom positives: "shallows to 1.1 metres at zero tide" → `[1.1]`; "drop to 0.2
    fathoms" → `[~0.366]`; "drawing more than 2 m" → `[2.0]`.
  - Division of labor in tests: the entrance-vs-anchoring exclusion now lives in the
    **proposer** suite (the LLM decides), NOT the regex suite. Since the regex no longer
    gates on context, the regex tests assert only figure-capture and unit-conversion
    correctness. The prior `bar dries → no match` safety test must still pass (we are not
    re-adding `dries`).
  - Unit conversion: fathom/foot figures normalise to metres within tolerance
    ("0.2 fathoms" → ~0.366 m; "6 feet" → ~1.83 m).
- **Proposer** (`tests/ingest/test_depth_propose.py`, new): fake client returning a tool
  call → entrance prose yields the value; anchoring-only prose yields null; schema
  includes `controlling_depth_m`.
- **Backfill command** (`tests/ingest/test_cli.py` additions): small fixture vault + fake
  client; dry-run writes nothing; `--apply` populates only confirmed records and leaves
  unconfirmed/null as `unknown`; already-set records are skipped (resumable).

## 6. Operational note

~673 focused calls across 7 books, instruction block prompt-cached. Workflow: run
`--source` per book in dry-run, eyeball the audit report, then `--apply`. Publishing the
new tool params (npm release) and redeploying the Pi MCP remain the separate **outbound**
step, unchanged by this work.

## Out of scope

- Tide-correction of the clearance verdict (still the deferred follow-on).
- Any change to runtime `keel_clearance` logic — this only fills the field it reads.
- The original ingest-time extraction (`record_anchorage`) — left as-is; its
  `controlling_depth_m` field and instruction from the prior design stay, and new ingests
  still get a first pass at the field. (A future cleanup could route new ingests through
  the same proposer, but that is not in this scope.)

## Defaults chosen (revisit if needed)

- Confirm tolerance widened to **0.15 m** (from 0.05) to absorb fathom/foot conversion
  rounding.
- Dry-run is the default; writes require `--apply`.
- Backfill is resumable (skips already-populated records) rather than idempotently
  re-deriving every run.
