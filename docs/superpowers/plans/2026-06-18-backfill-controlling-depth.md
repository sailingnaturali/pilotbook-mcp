# Backfill controlling_depth_m Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `controlling_depth_m` across the existing 673-anchorage vault with a new `pilotbook backfill-depths` command — an LLM proposes the entrance/approach least depth from each anchorage's prose, a rebuilt deterministic regex confirms the number is literally in the text, and only confirmed values are written.

**Architecture:** Three units. (1) `ingest/confirm.py` regex rebuilt on the *real* Salish Sea Pilot idioms ("shallows/drops to X … at zero tide") with fathom/foot→metre conversion. (2) A focused single-field LLM proposer (`ingest/depth_propose.py`) that owns the entrance-vs-anchoring judgment. (3) A `run_backfill_depths` CLI command that walks the vault, proposes → confirms → writes, preserving every other curated field. The LLM owns the semantics; the regex only proves the number is in the prose.

**Tech Stack:** Python 3, Anthropic SDK (forced structured tool use, prompt-cached instructions), dataclasses + PyYAML frontmatter, pytest.

**Design spec:** `docs/superpowers/specs/2026-06-18-backfill-controlling-depth-design.md`

---

## File structure

- `src/pilotbook_mcp/ingest/confirm.py` — rebuild regex idioms + unit conversion + tolerance (Task 1)
- `src/pilotbook_mcp/ingest/depth_propose.py` — **new**; focused LLM proposer (Task 2)
- `src/pilotbook_mcp/ingest/cli.py` — `run_backfill_depths` + subparser (Task 3)
- Tests: `tests/ingest/test_confirm.py` (edits), `tests/ingest/test_depth_propose.py` (new), `tests/ingest/test_cli.py` (additions)

Run the suite with `uv run pytest` from the repo root.

### Deviation from spec (intentional, safety-driven)

The spec listed a broad `depths?\s+(to|of)\s+<DEPTH>` pattern. The plan **omits** it: that
bare pattern would match interior anchoring depths ("depths of 8 m inside"), which (a)
breaks the existing `test_entrance_anchoring_depth_is_not_grabbed` safety test and (b)
would let the ingest-time regex-only fallback in `confirm_controlling_depth` record an
anchoring depth as a controlling depth. Instead we use shoaling/approach **verbs**
(`shallows/shoals/drops/falls to`, `drawing`) which capture the dominant real idiom while
staying entrance-specific. Recall lost this way is safe — those anchorages stay `unknown`.
The backfill also never invokes the regex-only fallback (it only confirms an actual LLM
proposal — see Task 3), so the fallback stays purely an ingest-time concern.

---

## Task 1: Rebuild the confirm regex on real idioms + unit conversion

**Files:**
- Modify: `src/pilotbook_mcp/ingest/confirm.py`
- Test: `tests/ingest/test_confirm.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/ingest/test_confirm.py`:

```python
def test_finds_shallows_to_phrasing():
    assert find_controlling_depths("the entrance shallows to 1.1 metres at zero tide") == [1.1]


def test_finds_drops_to_fathoms_converted():
    # 0.2 fathoms * 1.8288 = 0.36576 -> 0.37
    assert find_controlling_depths("depths in the entrance drop to 0.2 fathoms at zero tide") == [0.37]


def test_finds_drawing_more_than_phrasing():
    assert find_controlling_depths("sailboats drawing more than 2 m should enter on a rising tide") == [2.0]


def test_finds_bar_carries_feet_converted():
    # 6 feet * 0.3048 = 1.8288 -> 1.83
    assert find_controlling_depths("the bar carries 6 feet") == [1.83]


def test_confirm_keeps_within_widened_tolerance():
    # LLM read "about one foot" as 0.3; prose figure is 0.2 fathoms (~0.37). 0.07 <= 0.15 -> keep.
    a = Anchorage(name="X", source="S", controlling_depth_m=0.3,
                  prose="depths in the entrance drop to 0.2 fathoms (about one foot) at zero tide")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m == 0.3
    assert note is None
```

Then **update** the now-obsolete metres-only test. Replace the existing
`test_feet_and_fathoms_do_not_match` with:

```python
def test_feet_and_fathoms_now_convert_to_metres():
    # Unit conversion is intentional now (the author mixes units).
    assert find_controlling_depths("drawing 6 feet or less") == [1.83]
    assert find_controlling_depths("the bar carries 1 fathom") == [1.83]
```

(Leave `test_bar_dries_is_not_read_as_depth`, `test_entrance_anchoring_depth_is_not_grabbed`,
and the existing metre tests unchanged — they must still pass.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_confirm.py -v`
Expected: the new tests FAIL (e.g. `shallows to` returns `[]`; feet/fathom return `[]`).

- [ ] **Step 3: Rebuild the regex + add unit conversion**

In `src/pilotbook_mcp/ingest/confirm.py`, replace the `_DEPTH`/`_PATTERNS`/`_TOLERANCE_M`
block (lines 16–28) and `find_controlling_depths` (lines 31–37) with:

```python
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(metres?|meters?|fathoms?|feet|foot|ft|m)"  # longest-first so "metres" != "m"+"etres"
_DEPTH = rf"{_NUM}\s*{_UNIT}\b"
# Match shoaling/approach idioms that denote depth OF WATER on the way in. The LLM owns the
# entrance-vs-anchoring judgment (see depth_propose.py); these patterns only prove the
# proposed number is literally in the prose. Deliberately NOT matched: "bar dries X m"
# (X above datum — no water), and bare "depths of X" (would grab interior anchoring depths).
_PATTERNS = [
    re.compile(rf"drawing\s+{_DEPTH}\s+or\s+less", re.I),
    re.compile(rf"drawing\s+more\s+than\s+{_DEPTH}", re.I),
    re.compile(rf"(?:shallows?|shoals?|drops?|falls?)\s+to\s+{_DEPTH}", re.I),
    re.compile(rf"controlling\s+depth\s+(?:of\s+)?{_DEPTH}", re.I),
    re.compile(rf"bar\s+carries\s+{_DEPTH}", re.I),
    re.compile(rf"entrance[^.\n]{{0,30}}?(?:sill|bar|shoal|least\s+depth)\s+(?:of\s+)?{_DEPTH}", re.I),
]
_TOLERANCE_M = 0.15  # widened from 0.05 to absorb fathom/foot conversion rounding

_FACTOR = {
    "m": 1.0, "metre": 1.0, "metres": 1.0, "meter": 1.0, "meters": 1.0,
    "fathom": 1.8288, "fathoms": 1.8288,
    "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
}


def find_controlling_depths(prose: str | None) -> list[float]:
    """Every approach/entrance depth figure the known idioms yield, converted to metres."""
    out: list[float] = []
    for pat in _PATTERNS:
        for m in pat.finditer(prose or ""):
            num, unit = m.groups()  # each pattern captures exactly (number, unit)
            factor = _FACTOR.get(unit.lower())
            if factor is not None:
                out.append(round(float(num) * factor, 2))
    return out
```

Leave `confirm_controlling_depth` (lines 40–60) unchanged — it already reads
`_TOLERANCE_M` and `find_controlling_depths`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_confirm.py -v`
Expected: PASS (all — new idiom/conversion tests, the updated feet/fathom test, and the
unchanged safety tests including `bar dries → []` and `entrance anchoring-depth → []`).

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/confirm.py tests/ingest/test_confirm.py
git commit -m "feat: rebuild controlling-depth regex on real idioms + unit conversion"
```

---

## Task 2: Focused LLM proposer

**Files:**
- Create: `src/pilotbook_mcp/ingest/depth_propose.py`
- Test: `tests/ingest/test_depth_propose.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_depth_propose.py`:

```python
from pilotbook_mcp.ingest.depth_propose import (
    PROPOSE_TOOL, build_propose_prompt, propose_controlling_depth,
)


class _ToolBlock:
    def __init__(self, input):
        self.type = "tool_use"
        self.name = "propose_controlling_depth"
        self.input = input


class _Resp:
    def __init__(self, input):
        self.content = [_ToolBlock(input)]


class _FakeMessages:
    def __init__(self, input):
        self.input = input
        self.last = None

    def create(self, **kwargs):
        self.last = kwargs
        return _Resp(self.input)


class _FakeClient:
    def __init__(self, input):
        self.messages = _FakeMessages(input)


def test_prompt_and_schema_are_cached_and_well_formed():
    assert build_propose_prompt()[0]["cache_control"] == {"type": "ephemeral"}
    assert PROPOSE_TOOL["name"] == "propose_controlling_depth"
    assert PROPOSE_TOOL["cache_control"] == {"type": "ephemeral"}
    assert PROPOSE_TOOL["input_schema"]["required"] == ["has_controlling_depth"]


def test_proposes_value_when_entrance_depth_present():
    client = _FakeClient({"has_controlling_depth": True, "controlling_depth_m": 1.1})
    v = propose_controlling_depth("entrance shallows to 1.1 m at zero tide",
                                  client=client, model="claude-sonnet-4-6")
    assert v == 1.1
    # the prose was sent and the tool forced
    assert "shallows" in client.messages.last["messages"][0]["content"]
    assert client.messages.last["tool_choice"] == {"type": "tool", "name": "propose_controlling_depth"}


def test_returns_none_when_no_entrance_depth():
    client = _FakeClient({"has_controlling_depth": False})
    assert propose_controlling_depth("anchor in 8 m over mud", client=client, model="m") is None


def test_returns_none_when_flag_true_but_value_missing():
    client = _FakeClient({"has_controlling_depth": True})  # model forgot the number
    assert propose_controlling_depth("entrance is shallow", client=client, model="m") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingest/test_depth_propose.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pilotbook_mcp.ingest.depth_propose'`

- [ ] **Step 3: Write the implementation**

Create `src/pilotbook_mcp/ingest/depth_propose.py`:

```python
"""Focused LLM proposer for an anchorage's controlling (entrance/approach) depth.

Separate from the big record_anchorage extractor: its only job is the entrance-vs-anchoring
judgment that regex does poorly. It reads one anchorage's prose and returns the least depth
ON THE APPROACH in metres, or None. The deterministic confirm pass then proves that number
is literally in the prose before it is kept (see ingest/confirm.py).
"""

from __future__ import annotations

_INSTRUCTIONS = """\
You are given the prose description of ONE anchorage from a cruising guide. Report the
CONTROLLING DEPTH: the charted LEAST depth of water on the APPROACH or ENTRANCE that a
vessel must cross to get in (a bar, sill, shoal, or narrows). This is NOT the depth you
anchor in once inside.

Call `propose_controlling_depth`.
- has_controlling_depth = true ONLY when the prose states an approach/entrance least depth.
  Report controlling_depth_m in METRES (convert feet ×0.3048, fathoms ×1.8288).
  Entrance phrasings: "the entrance shallows to 1.1 metres at zero tide";
  "depths in the entrance drop to 0.2 fathoms at zero tide"; "drawing more than 2 m should
  enter on a rising tide" (report 2); "the bar carries 1.5 m".
- has_controlling_depth = false when:
  * the depth given is where you ANCHOR, not the approach — "anchor in 5–6 metres at zero
    tide", "depths of 5–7 metres inside the lagoon" (these are interior/anchoring depths);
  * the entrance is described only qualitatively — "dries near half tide", "shallow
    approach, shoal-draft only" — with no usable metre/foot/fathom figure;
  * no approach depth is mentioned at all.
When in doubt, set false — a missing value is safe (verified locally); a wrong one is not.
"""

PROPOSE_TOOL = {
    "name": "propose_controlling_depth",
    "description": "Report this anchorage's entrance/approach controlling least depth.",
    "input_schema": {
        "type": "object",
        "properties": {
            "has_controlling_depth": {"type": "boolean",
                "description": "true only if the prose states an approach/entrance least depth"},
            "controlling_depth_m": {"type": "number",
                "description": "the approach/entrance least depth in METRES (convert feet/fathoms); "
                               "omit when has_controlling_depth is false"},
        },
        "required": ["has_controlling_depth"],
    },
    "cache_control": {"type": "ephemeral"},
}


def build_propose_prompt() -> list[dict]:
    """System blocks (cached — identical across every record)."""
    return [{"type": "text", "text": _INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}]


def propose_controlling_depth(prose: str, *, client, model: str = "claude-sonnet-4-6") -> float | None:
    """Ask the model for the entrance/approach controlling depth in metres, or None.

    Never raises on model-output shape — returns None if no usable tool call came back.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=300,
        system=build_propose_prompt(),
        tools=[PROPOSE_TOOL],
        tool_choice={"type": "tool", "name": "propose_controlling_depth"},
        messages=[{"role": "user", "content": prose}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "propose_controlling_depth":
            data = dict(block.input)
            if data.get("has_controlling_depth") and isinstance(data.get("controlling_depth_m"), (int, float)):
                return float(data["controlling_depth_m"])
            return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_depth_propose.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/depth_propose.py tests/ingest/test_depth_propose.py
git commit -m "feat: focused LLM proposer for controlling_depth_m"
```

---

## Task 3: `backfill-depths` CLI command

**Files:**
- Modify: `src/pilotbook_mcp/ingest/cli.py`
- Test: `tests/ingest/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ingest/test_cli.py` (this file already constructs temp vaults and monkeypatches
`cli._make_client` / ingest helpers — match its existing style; the imports below are
self-contained so they work regardless):

```python
from pathlib import Path

from pilotbook_mcp.ingest import cli as cli_mod
from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.vault import Vault


class _DepthResp:
    def __init__(self, payload):
        class _Block:
            type = "tool_use"
            name = "propose_controlling_depth"
            def __init__(self, p): self.input = p
        self.content = [_Block(payload)]


class _DepthMessages:
    def create(self, **kwargs):
        prose = kwargs["messages"][0]["content"]
        if "shallows to" in prose:
            return _DepthResp({"has_controlling_depth": True, "controlling_depth_m": 1.5})
        return _DepthResp({"has_controlling_depth": False})


class _DepthClient:
    messages = _DepthMessages()


def _write(root: Path, name: str, prose: str, controlling=None):
    a = Anchorage(name=name, source="TestPilot — Region 2025", lat=48.5, lon=-123.4,
                  controlling_depth_m=controlling, prose=prose)
    book = root / "anchorages" / "testpilot-region-2025"
    book.mkdir(parents=True, exist_ok=True)
    (book / f"{name.lower().replace(' ', '-')}.md").write_text(a.to_markdown(), encoding="utf-8")


def _make_backfill_vault(tmp_path) -> Path:
    root = tmp_path / "vault"
    _write(root, "Entrance Cove", "The entrance shallows to 1.5 m at zero tide.")
    _write(root, "Deep Bay", "Anchor in 8 m over mud. Good holding.")
    _write(root, "Already Set", "The entrance shallows to 1.5 m.", controlling=2.0)
    return root


def test_backfill_dry_run_writes_nothing(tmp_path, monkeypatch):
    root = _make_backfill_vault(tmp_path)
    monkeypatch.setattr(cli_mod, "_make_client", lambda: _DepthClient())
    cli_mod.run_backfill_depths(all_books=True, vault=str(root), apply=False)
    v = Vault.load(root)
    assert v.get("Entrance Cove").controlling_depth_m is None  # dry run did not write


def test_backfill_apply_populates_only_confirmed(tmp_path, monkeypatch):
    root = _make_backfill_vault(tmp_path)
    monkeypatch.setattr(cli_mod, "_make_client", lambda: _DepthClient())
    cli_mod.run_backfill_depths(all_books=True, vault=str(root), apply=True)
    v = Vault.load(root)
    assert v.get("Entrance Cove").controlling_depth_m == 1.5   # proposed + confirmed
    assert v.get("Deep Bay").controlling_depth_m is None       # LLM said no entrance depth
    assert v.get("Already Set").controlling_depth_m == 2.0     # skipped (already set)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingest/test_cli.py::test_backfill_apply_populates_only_confirmed -v`
Expected: FAIL — `AttributeError: module 'pilotbook_mcp.ingest.cli' has no attribute 'run_backfill_depths'`

- [ ] **Step 3: Implement the command**

In `src/pilotbook_mcp/ingest/cli.py`, add the import next to the other ingest imports
(after the `confirm` import added in the prior feature):

```python
from pilotbook_mcp.ingest.depth_propose import propose_controlling_depth
```

Add this function (e.g. after `run_audit`):

```python
def run_backfill_depths(source: str | None = None, all_books: bool = False,
                        vault: str | None = None, apply: bool = False,
                        model: str = "claude-sonnet-4-6") -> None:
    """Backfill controlling_depth_m: LLM proposes from prose, regex confirms, only
    confirmed values are written. Touches no other field. Resumable (skips set records)."""
    if not source and not all_books:
        print("Specify --source <book> or --all.")
        return
    v = Vault.load(Path(vault) if vault else None)
    records = v.anchorages
    if source:
        book = slugify(source)
        records = [a for a in records if slugify(a.source) == book]
    if not records:
        print(f"No anchorages for the requested scope in {v.root.resolve()}.")
        return

    client = _make_client()
    populated: list[str] = []
    dropped: list[str] = []
    skipped = unknown = errored = 0
    for a in records:
        if a.controlling_depth_m is not None:
            skipped += 1
            continue
        try:
            proposed = propose_controlling_depth(a.prose, client=client, model=model)
        except Exception as exc:  # one bad record must not abort the batch
            errored += 1
            logger.warning("depth proposal failed on %s: %s", a.name, exc)
            continue
        if proposed is None:
            unknown += 1
            continue
        a.controlling_depth_m = proposed
        note = confirm_controlling_depth(a)   # drops to None if not literally in prose
        if a.controlling_depth_m is not None:
            populated.append(f"{a.name} → {a.controlling_depth_m} m")
            if apply:
                write_anchorage(v.root, a)
        else:
            dropped.append(note or f"{a.name}: proposed {proposed} m, dropped")

    mode = "Applied" if apply else "DRY RUN"
    print(f"{mode}: {len(populated)} populated, {len(dropped)} dropped-unconfirmed, "
          f"{unknown} unknown, {skipped} already set, {errored} errored. Vault: {v.root.resolve()}")
    for line in populated:
        print(f"  populated: {line}")
    for line in dropped:
        print(f"  dropped:   {line}")
    if not apply and (populated or dropped):
        print("Re-run with --apply to write.")
```

Then wire the subparser in `main()`. After the `clean-prose` subparser block, add:

```python
    p_bf = sub.add_parser("backfill-depths",
                          help="LLM-propose + regex-confirm controlling_depth_m on existing records")
    p_bf.add_argument("--source", default=None, help="limit to one book (e.g. \"SalishSeaPilot — Gulf Islands 2025\")")
    p_bf.add_argument("--all", dest="all_books", action="store_true", help="all books in the vault")
    p_bf.add_argument("--vault", default=None)
    p_bf.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
```

And in the dispatch chain at the bottom of `main()`, add:

```python
    elif args.cmd == "backfill-depths":
        run_backfill_depths(source=args.source, all_books=args.all_books,
                            vault=args.vault, apply=args.apply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_cli.py -v`
Expected: PASS (both new backfill tests + existing CLI tests unchanged)

- [ ] **Step 5: Verify the module imports + full suite**

Run: `uv run python -c "import pilotbook_mcp.ingest.cli"` → exit 0, no output.
Run: `uv run pytest -q` → all green (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/pilotbook_mcp/ingest/cli.py tests/ingest/test_cli.py
git commit -m "feat: backfill-depths CLI command (LLM-propose + regex-confirm)"
```

---

## Final verification (code)

- [ ] `uv run pytest -q` — entire suite green.
- [ ] `uv run python -c "import pilotbook_mcp.ingest.cli, pilotbook_mcp.ingest.depth_propose, pilotbook_mcp.ingest.confirm"` — all import.
- [ ] `uv run pilotbook backfill-depths --help` — the subcommand and its flags render.

## Operational run (NOT a code task — uses the live API on Bryan's key)

This is run after the code is merged. The vault lives at
`/Users/clarkbw/src/sailingnaturali/pilotbook-vault`; the key is in `~/.hermes/.env`.

1. Load the key and point at the vault:
   ```bash
   set -a; source ~/.hermes/.env; set +a
   export PILOTBOOK_VAULT_PATH=/Users/clarkbw/src/sailingnaturali/pilotbook-vault
   ```
2. **Dry-run per book**, eyeball the populated/dropped report before writing:
   ```bash
   uv run pilotbook backfill-depths --source "SalishSeaPilot — Gulf Islands 2025"
   ```
3. When the report looks right, **apply**:
   ```bash
   uv run pilotbook backfill-depths --source "SalishSeaPilot — Gulf Islands 2025" --apply
   ```
4. Repeat per book (or `--all` once confident). The command is resumable — re-running skips
   already-populated records.
5. The pilotbook-vault is a separate git repo; review the diff and commit the populated
   records there.

Publishing the npm release + redeploying the Pi MCP remain the separate **outbound** step.

## Notes for the implementer

- `tests/ingest/test_cli.py` already builds temp vaults and monkeypatches `cli._make_client`
  and ingest helpers. The test code above is self-contained (its own fake client + vault
  writer), but match the file's import/style conventions where they overlap.
- `write_anchorage(root, a)` serialises via `Anchorage.to_markdown`, which drops
  None/empty fields — so writing back a record preserves `source_pdf`, `prose`, and every
  curated field while adding `controlling_depth_m`. Confirm this by reloading in the test.
- The backfill deliberately **does not** call `confirm_controlling_depth` when the LLM
  proposes None — that avoids the regex-only fallback overriding the model's "no entrance
  depth" judgment. Only an actual proposal is confirmed.
