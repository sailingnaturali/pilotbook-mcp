# Evidence-quote Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the brittle digit-regex confirmation of `controlling_depth_m` with a verbatim evidence-quote check (the LLM cites the prose phrase; we verify it's a literal substring), and make the backfill the sole populator — removing the regex and the ingest-time extraction.

**Architecture:** The proposer returns `(depth, evidence)`. A new `quote_confirms(prose, evidence)` confirms the quote is a whitespace-normalised, casefolded, depth-unit-bearing substring of the prose — robust to spelled-out numbers and parentheticals, while still blocking hallucination. The old regex (`find_controlling_depths`), the old `confirm_controlling_depth` validator, the ingest-time confirm call, and `record_anchorage`'s `controlling_depth_m` extraction are all deleted.

**Tech Stack:** Python 3, Anthropic SDK (forced tool use, cached prompt), pytest.

**Design spec:** `docs/superpowers/specs/2026-06-18-evidence-quote-confirmation-design.md`

---

## File structure & task ordering

Ordered so the suite stays green at every task boundary despite cross-module interface changes:

- **T1** `confirm.py`: ADD `quote_confirms` (additive — old regex stays for now).
- **T2** `depth_propose.py`: proposer returns `(depth, evidence)`; rewire `cli.run_backfill_depths` to use the tuple + `quote_confirms`.
- **T3** `confirm.py` + `cli.run_ingest`: delete the now-dead regex, `confirm_controlling_depth`, the ingest-time confirm call, and the stale imports.
- **T4** `extract.py`: remove `controlling_depth_m` from the `record_anchorage` schema + instructions.

`models.py` (the field), `tools.get_anchorage` (exposure), and `clearance.keel_clearance` (runtime) are **unchanged** — only population changes.

---

## Task 1: Add `quote_confirms` to confirm.py (additive)

**Files:**
- Modify: `src/pilotbook_mcp/ingest/confirm.py`
- Test: `tests/ingest/test_confirm.py`

- [ ] **Step 1: Write the failing tests** — Add to `tests/ingest/test_confirm.py` (and add `quote_confirms` to the existing import line `from pilotbook_mcp.ingest.confirm import ...`):

```python
def test_quote_confirms_real_prose_with_parenthetical():
    prose = ("Entrance to Anderson Cove is narrow and shallow, but vessels drawing "
             "1.8 metres (six feet) or less can enter with careful attention.")
    assert quote_confirms(prose, "drawing 1.8 metres (six feet) or less") is True


def test_quote_confirms_is_whitespace_and_case_insensitive():
    prose = "The entrance\n  shallows   to 1.1 METRES at zero tide."
    assert quote_confirms(prose, "shallows to 1.1 metres") is True


def test_quote_confirms_spelled_out_number():
    prose = "keels that draw two metres or more should enter at higher tide"
    assert quote_confirms(prose, "draw two metres or more") is True


def test_quote_not_in_prose_is_rejected():
    assert quote_confirms("a quiet bay with good holding", "drawing 2 metres or less") is False


def test_quote_without_depth_unit_is_rejected():
    prose = "the entrance is shallow and tricky to navigate"
    assert quote_confirms(prose, "the entrance is shallow") is False


def test_empty_evidence_is_rejected():
    assert quote_confirms("vessels drawing 1.8 metres or less", "") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_confirm.py -k quote -v`
Expected: FAIL — `ImportError`/`cannot import name 'quote_confirms'`.

- [ ] **Step 3: Add the functions** — In `src/pilotbook_mcp/ingest/confirm.py`, add after the existing `import re` / imports block (do NOT remove the regex yet — that's Task 3):

```python
_UNIT_TOKEN = re.compile(r"\b(metres?|meters?|fathoms?|feet|foot|ft)\b", re.I)


def _normalise(text: str) -> str:
    """Collapse whitespace and casefold so a verbatim quote matches across wrapping/case."""
    return " ".join((text or "").split()).casefold()


def quote_confirms(prose: str, evidence: str) -> bool:
    """True if the LLM's evidence quote is a real, depth-bearing substring of the prose.

    Anti-hallucination: the model cannot quote text that isn't there. Robust to
    spelled-out numbers and parentheticals because it matches the phrase, not the digit.
    """
    if not evidence:
        return False
    if not _UNIT_TOKEN.search(evidence):   # must be a depth citation, not arbitrary text
        return False
    return _normalise(evidence) in _normalise(prose)
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/ingest/test_confirm.py -v` → PASS (new quote tests + existing regex tests still pass).

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/confirm.py tests/ingest/test_confirm.py
git commit -m "feat: add quote_confirms evidence-quote validator"
```

---

## Task 2: Proposer returns (depth, evidence) + rewire backfill

**Files:**
- Modify: `src/pilotbook_mcp/ingest/depth_propose.py`
- Modify: `src/pilotbook_mcp/ingest/cli.py` (`run_backfill_depths` + imports)
- Test: `tests/ingest/test_depth_propose.py`, `tests/ingest/test_cli.py`

- [ ] **Step 1: Write the failing tests** — Replace the body of the existing proposer tests in `tests/ingest/test_depth_propose.py` so they expect a tuple, and add the evidence cases. The three behavioural tests become:

```python
def test_proposes_value_and_evidence_when_present():
    client = _FakeClient({"has_controlling_depth": True, "controlling_depth_m": 1.1,
                          "evidence": "shallows to 1.1 m at zero tide"})
    depth, evidence = propose_controlling_depth("entrance shallows to 1.1 m at zero tide",
                                                client=client, model="claude-sonnet-4-6")
    assert depth == 1.1
    assert evidence == "shallows to 1.1 m at zero tide"
    assert client.messages.last["tool_choice"] == {"type": "tool", "name": "propose_controlling_depth"}


def test_returns_none_pair_when_no_entrance_depth():
    client = _FakeClient({"has_controlling_depth": False})
    assert propose_controlling_depth("anchor in 8 m over mud", client=client, model="m") == (None, None)


def test_returns_none_pair_when_value_missing():
    client = _FakeClient({"has_controlling_depth": True, "evidence": "shallows to 1 m"})
    assert propose_controlling_depth("x", client=client, model="m") == (None, None)


def test_returns_none_pair_when_evidence_missing():
    client = _FakeClient({"has_controlling_depth": True, "controlling_depth_m": 1.5})
    assert propose_controlling_depth("x", client=client, model="m") == (None, None)
```

Update the schema test to also assert the evidence field:

```python
def test_prompt_and_schema_are_cached_and_well_formed():
    assert build_propose_prompt()[0]["cache_control"] == {"type": "ephemeral"}
    assert PROPOSE_TOOL["name"] == "propose_controlling_depth"
    assert PROPOSE_TOOL["cache_control"] == {"type": "ephemeral"}
    assert PROPOSE_TOOL["input_schema"]["required"] == ["has_controlling_depth"]
    assert "evidence" in PROPOSE_TOOL["input_schema"]["properties"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_depth_propose.py -v`
Expected: FAIL — tuple unpacking / `evidence` assertions fail against the current `float | None` return.

- [ ] **Step 3: Update the proposer** — In `src/pilotbook_mcp/ingest/depth_propose.py`:

(a) Add the `evidence` field to `PROPOSE_TOOL["input_schema"]["properties"]` (after `controlling_depth_m`):

```python
            "evidence": {"type": "string",
                "description": "the VERBATIM phrase from the prose that states this depth — "
                               "quote it exactly, do not paraphrase; omit when has_controlling_depth is false"},
```

(b) Add one line to `_INSTRUCTIONS`, right before the "has_controlling_depth = false" bullet:

```
  Also set `evidence` to the exact phrase you read the depth from, quoted verbatim from the prose.
```

(c) Replace `propose_controlling_depth` with:

```python
def propose_controlling_depth(prose: str, *, client, model: str = "claude-sonnet-4-6") -> tuple[float | None, str | None]:
    """Ask the model for (entrance controlling depth in metres, verbatim evidence quote).

    Returns (None, None) unless the model flags an entrance depth AND supplies both a
    numeric depth and a non-empty evidence quote. Never raises on model-output shape.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=400,
        system=build_propose_prompt(),
        tools=[PROPOSE_TOOL],
        tool_choice={"type": "tool", "name": "propose_controlling_depth"},
        messages=[{"role": "user", "content": prose}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "propose_controlling_depth":
            data = dict(block.input)
            depth = data.get("controlling_depth_m")
            evidence = data.get("evidence")
            if (data.get("has_controlling_depth") and isinstance(depth, (int, float))
                    and isinstance(evidence, str) and evidence.strip()):
                return float(depth), evidence
            return None, None
    return None, None
```

- [ ] **Step 4: Rewire the backfill** — In `src/pilotbook_mcp/ingest/cli.py`:

(a) Change the confirm import (line ~19) to add `quote_confirms`:

```python
from pilotbook_mcp.ingest.confirm import confirm_controlling_depth, quote_confirms
```

(b) Replace the proposal/confirm block inside `run_backfill_depths`'s loop (the `try: proposed = ...` through the `else: dropped.append(note)` block) with:

```python
        try:
            depth, evidence = propose_controlling_depth(a.prose, client=client, model=model)
        except Exception as exc:  # one bad record must not abort the batch
            errored += 1
            logger.warning("depth proposal failed on %s: %s", a.name, exc)
            continue
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

- [ ] **Step 5: Update the backfill test** — In `tests/ingest/test_cli.py`, replace the backfill fake client + fixtures + assertions with:

```python
class _DepthMessages:
    def create(self, **kwargs):
        prose = kwargs["messages"][0]["content"]
        if "shallows to" in prose:
            return _DepthResp({"has_controlling_depth": True, "controlling_depth_m": 1.5,
                               "evidence": "shallows to 1.5 m"})
        if "phantom" in prose.lower():  # proposes a quote that is NOT in the prose
            return _DepthResp({"has_controlling_depth": True, "controlling_depth_m": 2.0,
                               "evidence": "drawing 2 metres or less"})
        return _DepthResp({"has_controlling_depth": False})
```

and the vault builder:

```python
def _make_backfill_vault(tmp_path) -> Path:
    root = tmp_path / "vault"
    _bf_write(root, "Entrance Cove", "The entrance shallows to 1.5 m at zero tide.")
    _bf_write(root, "Deep Bay", "Anchor in 8 m over mud. Good holding.")
    _bf_write(root, "Phantom Cove", "A quiet phantom bay, no stated entrance depth.")
    _bf_write(root, "Already Set", "The entrance shallows to 1.5 m.", controlling=2.0)
    return root
```

and the apply assertions:

```python
def test_backfill_apply_populates_only_quote_confirmed(tmp_path, monkeypatch):
    root = _make_backfill_vault(tmp_path)
    monkeypatch.setattr(cli_mod, "_make_client", lambda: _DepthClient())
    cli_mod.run_backfill_depths(all_books=True, vault=str(root), apply=True)
    v = Vault.load(root)
    assert v.get("Entrance Cove").controlling_depth_m == 1.5   # quote in prose
    assert v.get("Deep Bay").controlling_depth_m is None       # no entrance depth
    assert v.get("Phantom Cove").controlling_depth_m is None   # quote NOT in prose -> dropped
    assert v.get("Already Set").controlling_depth_m == 2.0     # skipped
```

Keep `test_backfill_dry_run_writes_nothing` but rename its assertion target to `Entrance Cove` (already correct). The `_DepthResp` helper and `_DepthClient` from the prior task stay; only `_DepthMessages` payloads gain `evidence`.

- [ ] **Step 6: Run tests** — `uv run pytest tests/ingest/test_depth_propose.py tests/ingest/test_cli.py -v` → PASS. Then `uv run pytest -q` → all green.

- [ ] **Step 7: Commit**

```bash
git add src/pilotbook_mcp/ingest/depth_propose.py src/pilotbook_mcp/ingest/cli.py tests/ingest/test_depth_propose.py tests/ingest/test_cli.py
git commit -m "feat: proposer returns evidence quote; backfill confirms via quote_confirms"
```

---

## Task 3: Delete the dead regex + ingest-time confirm

**Files:**
- Modify: `src/pilotbook_mcp/ingest/confirm.py` (delete regex + old validator)
- Modify: `src/pilotbook_mcp/ingest/cli.py` (`run_ingest` + import)
- Test: `tests/ingest/test_confirm.py`

- [ ] **Step 1: Replace confirm.py with the quote-only module** — Overwrite `src/pilotbook_mcp/ingest/confirm.py` entirely with:

```python
"""Evidence-quote confirmation for controlling_depth_m.

The LLM proposer (ingest/depth_propose.py) returns the verbatim prose phrase it read an
entrance/approach depth from; this module confirms that phrase is a real, depth-bearing
substring of the prose. The model cannot quote text that isn't there, so a hallucinated
depth cannot pass — while spelled-out numbers and parenthetical conversions, which a
digit-regex could not handle, confirm fine because we match the phrase, not the number.
"""

from __future__ import annotations

import re

_UNIT_TOKEN = re.compile(r"\b(metres?|meters?|fathoms?|feet|foot|ft)\b", re.I)


def _normalise(text: str) -> str:
    """Collapse whitespace and casefold so a verbatim quote matches across wrapping/case."""
    return " ".join((text or "").split()).casefold()


def quote_confirms(prose: str, evidence: str) -> bool:
    """True if the LLM's evidence quote is a real, depth-bearing substring of the prose.

    Anti-hallucination: the model cannot quote text that isn't there. Robust to
    spelled-out numbers and parentheticals because it matches the phrase, not the digit.
    """
    if not evidence:
        return False
    if not _UNIT_TOKEN.search(evidence):   # must be a depth citation, not arbitrary text
        return False
    return _normalise(evidence) in _normalise(prose)
```

- [ ] **Step 2: Trim the ingest-time confirm from `run_ingest`** — In `src/pilotbook_mcp/ingest/cli.py`:

(a) Change the confirm import (line ~19) to drop the deleted name:

```python
from pilotbook_mcp.ingest.confirm import quote_confirms
```

(b) Remove the `depth_reviews` initialiser (the line `    depth_reviews: list[str] = []`).

(c) Remove these three lines from the `run_ingest` loop (currently before `a.source_pdf = ...`):

```python
        depth_note = confirm_controlling_depth(a)
        if depth_note:
            depth_reviews.append(depth_note)
```

(d) Remove the depth-review tail after the `Ingested …` print:

```python
    if depth_reviews:
        print(f"{len(depth_reviews)} controlling-depth note(s) to review:")
        for note in depth_reviews:
            print(f"  - {note}")
```

- [ ] **Step 3: Trim the obsolete regex tests** — In `tests/ingest/test_confirm.py`, delete every test that calls `find_controlling_depths` or `confirm_controlling_depth` (all of them except the six `quote_confirms` tests from Task 1), and change the import line to:

```python
from pilotbook_mcp.ingest.confirm import quote_confirms
```

(Remove the now-unused `from pilotbook_mcp.models import Anchorage` import if no remaining test uses it.)

- [ ] **Step 4: Run tests** — `uv run pytest -q` → all green. Then `uv run python -c "import pilotbook_mcp.ingest.cli, pilotbook_mcp.ingest.confirm"` → exit 0 (no reference to the deleted names remains).

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/confirm.py src/pilotbook_mcp/ingest/cli.py tests/ingest/test_confirm.py
git commit -m "refactor: drop regex confirm + ingest-time controlling-depth confirm"
```

---

## Task 4: Remove controlling_depth_m from record_anchorage

**Files:**
- Modify: `src/pilotbook_mcp/ingest/extract.py`
- Test: `tests/ingest/test_extract.py`

- [ ] **Step 1: Delete the obsolete schema test** — In `tests/ingest/test_extract.py`, remove `test_extract_schema_includes_controlling_depth`.

- [ ] **Step 2: Run test to verify removal is needed** — `uv run pytest tests/ingest/test_extract.py -q` → still PASS (we removed the test that would otherwise fail after the schema edit). This step just confirms the suite is green before the source edit.

- [ ] **Step 3: Remove the field from extract.py** — In `src/pilotbook_mcp/ingest/extract.py`:

(a) Delete the `controlling_depth_m` schema block (the four lines starting `"controlling_depth_m": {"type": "number",`).

(b) Delete the controlling-depth sentence from `_INSTRUCTIONS` — the text from "Record \`controlling_depth_m\` (in METRES) ONLY when the page states a least depth on the approach or entrance (a bar, sill, or shoal the boat must cross) — e.g. \"drawing 1.8 m or less\", \"controlling depth 2 m\", \"the bar carries 1.5 m\". Convert feet or fathoms to metres. Do not populate it from anchoring-depth prose. " — so the sentence flows directly from "…W and S are negative)." into "Set \`confidence\` to your confidence in exposed_sectors."

The result should read:
```
W and S are negative). Set `confidence` to your confidence in exposed_sectors.
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/ingest/test_extract.py -v` → PASS. Then `uv run pytest -q` → all green. The `Anchorage` model still has the field; only `record_anchorage` stops extracting it.

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/extract.py tests/ingest/test_extract.py
git commit -m "refactor: record_anchorage no longer extracts controlling_depth_m (backfill owns it)"
```

---

## Final verification (code)

- [ ] `uv run pytest -q` — entire suite green.
- [ ] `uv run python -c "import pilotbook_mcp.ingest.cli, pilotbook_mcp.ingest.confirm, pilotbook_mcp.ingest.depth_propose, pilotbook_mcp.ingest.extract"` — all import; no reference to `find_controlling_depths` / `confirm_controlling_depth` remains (`grep -rn "find_controlling_depths\|confirm_controlling_depth" src tests` returns nothing).
- [ ] `uv run pilotbook backfill-depths --help` — still renders.

## Operational re-run (after merge — live API on the Hermes key)

```bash
set -a; source ~/.hermes/.env; set +a
export PILOTBOOK_VAULT_PATH=/Users/clarkbw/src/sailingnaturali/pilotbook-vault
uv run pilotbook backfill-depths --source "SalishSeaPilot — Gulf Islands 2025"   # dry-run, now shows «evidence»
```
Eyeball the populated values + their quotes; then `--apply`; repeat per book / `--all`; commit the populated records in the pilotbook-vault repo.

## Notes for the implementer

- Keep each task's boundary green — the ordering is deliberate (quote_confirms added before the old regex is removed; proposer/backfill rewired before the ingest-time confirm is deleted).
- `propose_controlling_depth`'s return type changes from `float | None` to `tuple[float | None, str | None]`; its only caller is `run_backfill_depths` (rewired in Task 2).
- Do not touch `models.py`, `tools.get_anchorage`, or `clearance.py` — the field, its exposure, and the runtime verdict are unchanged.
