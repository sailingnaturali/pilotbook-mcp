# Draft-Aware Keel-Clearance Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `draft_m` input that annotates each anchorage with a keel-clearance verdict (clear / tight / unsafe_at_datum / unknown) derived from a new `controlling_depth_m` field, without ever reordering results.

**Architecture:** A new structured field on `Anchorage` (`controlling_depth_m`) is populated during ingest by the existing Claude extractor and then confirmed against the prose by a deterministic regex pass. At query time, a pure `keel_clearance()` function turns (controlling depth, draft, margin) into a flag block; `find_anchorages_near` and `assess_anchorage` attach it when `draft_m` is supplied. Ranking stays comfort-only. All clearance is at chart datum with an explicit "add tide" caveat; tide-correction is out of scope.

**Tech Stack:** Python 3, dataclasses, PyYAML (frontmatter), pytest, Anthropic SDK (existing ingest), MCP stdio server.

**Design spec:** `docs/superpowers/specs/2026-06-18-draft-aware-clearance-design.md`

---

## File structure

- `src/pilotbook_mcp/models.py` — add `controlling_depth_m` field (Task 1)
- `src/pilotbook_mcp/clearance.py` — **new**; pure `keel_clearance()` verdict function (Task 2)
- `src/pilotbook_mcp/tools.py` — surface field in `get_anchorage`; thread `draft_m` into `find_anchorages_near` (Tasks 3, 4)
- `src/pilotbook_mcp/assess.py` — attach clearance to ranked candidates (Task 5)
- `src/pilotbook_mcp/server.py` — `draft_m`/`keel_safety_margin_m` in two `inputSchema`s + dispatch wiring (Task 6)
- `src/pilotbook_mcp/ingest/extract.py` — add field to the LLM extract schema + instructions (Task 7)
- `src/pilotbook_mcp/ingest/confirm.py` — **new**; deterministic regex confirm pass (Task 8)
- `src/pilotbook_mcp/ingest/cli.py` — wire confirm into `run_ingest` (Task 9)
- Tests: `tests/test_models.py`, `tests/test_clearance.py` (new), `tests/test_tools.py`, `tests/test_assess.py`, `tests/ingest/test_confirm.py` (new), `tests/ingest/test_extract.py`

Run the suite with `uv run pytest` from the repo root.

---

## Task 1: Add `controlling_depth_m` to the Anchorage model

**Files:**
- Modify: `src/pilotbook_mcp/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_controlling_depth_round_trips():
    a = Anchorage(name="Anderson Cove", source="S", lat=48.37, lon=-123.65,
                  controlling_depth_m=1.8)
    r = Anchorage.from_markdown(a.to_markdown())
    assert r.controlling_depth_m == 1.8


def test_controlling_depth_absent_defaults_none():
    a = Anchorage.from_markdown(
        "---\nname: Bare Bay\nsource: \"X\"\nlat: 48.0\nlon: -123.0\n---\nBody.\n"
    )
    assert a.controlling_depth_m is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_controlling_depth_round_trips -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'controlling_depth_m'`

- [ ] **Step 3: Add the field**

In `src/pilotbook_mcp/models.py`, add directly below the `depth_max_m` line (currently line 22):

```python
    controlling_depth_m: float | None = None  # charted least depth on the approach/entrance (bar, sill, shoal)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (all model tests, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/models.py tests/test_models.py
git commit -m "feat: add controlling_depth_m field to Anchorage"
```

---

## Task 2: Pure keel-clearance verdict function

**Files:**
- Create: `src/pilotbook_mcp/clearance.py`
- Test: `tests/test_clearance.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_clearance.py`:

```python
from pilotbook_mcp.clearance import keel_clearance


def test_clear_when_depth_exceeds_draft_plus_margin():
    v = keel_clearance(controlling_depth_m=4.0, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "clear"
    assert v["controlling_depth_m"] == 4.0
    assert v["draft_m"] == 1.37
    assert "chart datum" in v["note"]


def test_tight_within_margin():
    # 1.37 <= 1.8 < 1.37 + 0.5 (=1.87)
    v = keel_clearance(controlling_depth_m=1.8, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "tight"
    assert "chart datum" in v["note"]


def test_unsafe_when_depth_below_draft():
    v = keel_clearance(controlling_depth_m=1.0, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "unsafe_at_datum"
    assert "rising tide" in v["note"]


def test_unknown_when_depth_missing():
    v = keel_clearance(controlling_depth_m=None, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "unknown"
    assert v["controlling_depth_m"] is None
    assert "not recorded" in v["note"]


def test_boundary_exactly_at_draft_is_tight():
    v = keel_clearance(controlling_depth_m=1.37, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "tight"


def test_boundary_exactly_at_draft_plus_margin_is_clear():
    v = keel_clearance(controlling_depth_m=1.87, draft_m=1.37, margin_m=0.5)
    assert v["state"] == "clear"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_clearance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pilotbook_mcp.clearance'`

- [ ] **Step 3: Write minimal implementation**

Create `src/pilotbook_mcp/clearance.py`:

```python
"""Pure keel-clearance verdict: draft vs charted controlling (entrance) depth.

Flag only — never reorders. All depths are at chart datum (lowest tide); the note
always tells the reader to add tide height. Tide-correction is a deferred follow-on.
"""

from __future__ import annotations

_DATUM = "add tide height before trusting"


def keel_clearance(controlling_depth_m: float | None, draft_m: float,
                   margin_m: float = 0.5) -> dict:
    """Verdict block for one anchorage given the vessel's draft.

    States:
      unknown          — no recorded controlling depth
      clear            — depth >= draft + margin
      tight            — draft <= depth < draft + margin
      unsafe_at_datum  — depth < draft (at chart datum; a rising tide may open it)
    """
    if controlling_depth_m is None:
        return {"state": "unknown", "controlling_depth_m": None, "draft_m": draft_m,
                "note": "Entrance depth not recorded; verify locally."}
    d = controlling_depth_m
    if d >= draft_m + margin_m:
        state = "clear"
        note = f"{d} m at chart datum vs {draft_m} m draft — {_DATUM}."
    elif d >= draft_m:
        state = "tight"
        note = f"Marginal: {d} m at chart datum vs {draft_m} m draft — {_DATUM}."
    else:
        state = "unsafe_at_datum"
        note = (f"{d} m at chart datum is below {draft_m} m draft — "
                "at chart datum; a rising tide may open it.")
    return {"state": state, "controlling_depth_m": d, "draft_m": draft_m, "note": note}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clearance.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/clearance.py tests/test_clearance.py
git commit -m "feat: pure keel_clearance verdict function"
```

---

## Task 3: Surface `controlling_depth_m` in `get_anchorage`

**Files:**
- Modify: `src/pilotbook_mcp/tools.py:28-44`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools.py` (the existing tests build a `Vault` fixture; reuse the `vault` fixture already used by other tests in that file — if uncertain, check the top of `tests/test_tools.py` and `tests/conftest.py` for the fixture name):

```python
def test_get_anchorage_includes_controlling_depth(vault):
    # telegraph-harbour fixture has no controlling depth -> key present, value None
    res = tools.get_anchorage(vault, name="Telegraph Harbour")
    assert res["found"] is True
    assert "controlling_depth_m" in res["anchorage"]
    assert res["anchorage"]["controlling_depth_m"] is None
```

(If `tests/test_tools.py` imports tools differently, match its existing import — likely `from pilotbook_mcp import tools`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py::test_get_anchorage_includes_controlling_depth -v`
Expected: FAIL — `KeyError: 'controlling_depth_m'`

- [ ] **Step 3: Add the field to the record dict**

In `src/pilotbook_mcp/tools.py`, in `get_anchorage`, add `controlling_depth_m` to the record dict next to the existing depth fields (line 35):

```python
        "lat": a.lat, "lon": a.lon, "depth_min_m": a.depth_min_m, "depth_max_m": a.depth_max_m,
        "controlling_depth_m": a.controlling_depth_m,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/tools.py tests/test_tools.py
git commit -m "feat: expose controlling_depth_m in get_anchorage"
```

---

## Task 4: Thread `draft_m` into `find_anchorages_near`

**Files:**
- Modify: `src/pilotbook_mcp/tools.py:10-25`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools.py`:

```python
def test_find_near_omits_clearance_without_draft(vault):
    res = tools.find_anchorages_near(vault, lat=48.60, lon=-123.40, radius_nm=50)
    assert res["anchorages"]
    assert "keel_clearance" not in res["anchorages"][0]


def test_find_near_attaches_clearance_with_draft(vault):
    res = tools.find_anchorages_near(vault, lat=48.60, lon=-123.40, radius_nm=50,
                                     draft_m=1.37)
    a = res["anchorages"][0]
    assert "keel_clearance" in a
    # telegraph-harbour fixture has no controlling depth -> unknown
    assert a["keel_clearance"]["state"] == "unknown"
```

(Adjust lat/lon/radius if the fixture vault's anchorages sit elsewhere — Telegraph Harbour is at 48.60, -123.40 in `tests/fixtures/vault/anchorages/telegraph-harbour.md`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py::test_find_near_attaches_clearance_with_draft -v`
Expected: FAIL — `TypeError: find_anchorages_near() got an unexpected keyword argument 'draft_m'`

- [ ] **Step 3: Implement**

In `src/pilotbook_mcp/tools.py`, add the import at the top:

```python
from pilotbook_mcp.clearance import keel_clearance
```

Replace `find_anchorages_near` with:

```python
def find_anchorages_near(vault: Vault, lat: float, lon: float, radius_nm: float = 10.0,
                         draft_m: float | None = None,
                         keel_safety_margin_m: float = 0.5) -> dict:
    hits = within_radius(vault.anchorages, lat, lon, radius_nm)
    out = []
    for a, dist in hits:
        entry = {
            "name": a.name,
            "distance_nm": round(dist, 2),
            "lat": a.lat,
            "lon": a.lon,
            "exposed_sectors": a.exposed_sectors,
            "holding": a.holding,
            "crowding": a.crowding,
        }
        if draft_m is not None:
            entry["keel_clearance"] = keel_clearance(
                a.controlling_depth_m, draft_m, keel_safety_margin_m)
        out.append(entry)
    return {"anchorages": out}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS (including the without-draft test confirming output is unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/tools.py tests/test_tools.py
git commit -m "feat: optional draft_m keel_clearance on find_anchorages_near"
```

---

## Task 5: Attach clearance to `assess_anchorage` candidates

**Files:**
- Modify: `src/pilotbook_mcp/assess.py:59-121`
- Test: `tests/test_assess.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assess.py` (this module's tests are async and monkeypatch `fetch_forecast`; mirror the existing fixture/monkeypatch pattern at the top of the file — reuse whatever `vault` fixture and forecast stub the existing assess tests use):

```python
import pytest


@pytest.mark.asyncio
async def test_assess_attaches_keel_clearance(vault, monkeypatch, _stub_forecast):
    # _stub_forecast: existing helper/fixture that patches marine_forecast.fetch_forecast
    # to return a short usable wind series (see other tests in this file).
    from pilotbook_mcp import assess
    res = await assess.assess_anchorage(vault, lat=48.60, lon=-123.40,
                                        radius_nm=50, hours=6, draft_m=1.37)
    assert res["anchorages"]
    assert "keel_clearance" in res["anchorages"][0]
    assert res["anchorages"][0]["keel_clearance"]["state"] in {
        "clear", "tight", "unsafe_at_datum", "unknown"}
```

If `tests/test_assess.py` has no shared forecast stub, copy the monkeypatch block from the nearest existing async test in that file (it patches `marine_forecast.fetch_forecast`, imported into `assess`). Do **not** invent a new stubbing mechanism.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_assess.py::test_assess_attaches_keel_clearance -v`
Expected: FAIL — `TypeError: assess_anchorage() got an unexpected keyword argument 'draft_m'`

- [ ] **Step 3: Implement**

In `src/pilotbook_mcp/assess.py`, change the signature (line 59-61):

```python
async def assess_anchorage(vault: Vault,
                           lat: float, lon: float, radius_nm: float = 10.0,
                           hours: int = 12, draft_m: float | None = None,
                           keel_safety_margin_m: float = 0.5) -> dict:
```

Pass draft through the `find_anchorages_near` call (line 68):

```python
    near = tools.find_anchorages_near(vault, lat=lat, lon=lon, radius_nm=radius_nm,
                                      draft_m=draft_m,
                                      keel_safety_margin_m=keel_safety_margin_m)
```

Each candidate from `find_anchorages_near` now carries `keel_clearance` when `draft_m`
is set. Attach it to the ranked entries in the success path. After the existing
`for entry in ranked:` loop that sets `lee_shore_shift` (lines 111-113), add a clearance
merge keyed by name:

```python
        clearance_by_name = {c["name"]: c.get("keel_clearance") for c in candidates}
        for entry in ranked:
            kc = clearance_by_name.get(entry.get("name"))
            if kc is not None:
                entry["keel_clearance"] = kc
```

Also attach in the degraded "forecast unavailable" path (the dict comprehension at
lines 94-99) so a draft-aware caller still gets the flag when ranking is impossible:

```python
                "anchorages": [
                    {"name": c["name"],
                     "distance_nm": c.get("distance_nm"),
                     "exposed_sectors": c.get("exposed_sectors", []),
                     **({"keel_clearance": c["keel_clearance"]}
                        if "keel_clearance" in c else {})}
                    for c in candidates
                ],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_assess.py -v`
Expected: PASS (existing ordering tests unchanged; new clearance test passes)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/assess.py tests/test_assess.py
git commit -m "feat: attach keel_clearance to assess_anchorage candidates"
```

---

## Task 6: Expose `draft_m` in the MCP tool schemas + dispatch

**Files:**
- Modify: `src/pilotbook_mcp/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` (reuse the file's existing way of building the tool list / dispatching — likely `from pilotbook_mcp import server` and a `vault` fixture):

```python
def test_find_near_schema_advertises_draft():
    from pilotbook_mcp.server import tool_list
    by_name = {t.name: t for t in tool_list(has_search=False)}
    props = by_name["find_anchorages_near"].inputSchema["properties"]
    assert "draft_m" in props
    assert "keel_safety_margin_m" in props
    aprops = by_name["assess_anchorage"].inputSchema["properties"]
    assert "draft_m" in aprops


def test_dispatch_find_near_passes_draft(vault):
    from pilotbook_mcp.server import dispatch
    res = dispatch(vault, "find_anchorages_near",
                   {"lat": 48.60, "lon": -123.40, "radius_nm": 50, "draft_m": 1.37})
    assert "keel_clearance" in res["anchorages"][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_find_near_schema_advertises_draft -v`
Expected: FAIL — `KeyError: 'draft_m'`

- [ ] **Step 3: Implement**

In `src/pilotbook_mcp/server.py`, add to the `find_anchorages_near` `inputSchema` properties (lines 43-47):

```python
                    "radius_nm": {"type": "number", "description": "Search radius in nautical miles (default 10)."},
                    "draft_m": {"type": "number", "description": "Vessel draft in metres. When given, each result gets a keel_clearance verdict (chart-datum; add tide)."},
                    "keel_safety_margin_m": {"type": "number", "description": "Required under-keel clearance in metres (default 0.5)."},
```

Add the same two properties to the `assess_anchorage` `inputSchema` properties (after the `hours` property, line 98):

```python
                    "hours": {"type": "integer", "description": "Overnight forecast horizon in hours (default 12)."},
                    "draft_m": {"type": "number", "description": "Vessel draft in metres. When given, each candidate gets a keel_clearance verdict (chart-datum; add tide)."},
                    "keel_safety_margin_m": {"type": "number", "description": "Required under-keel clearance in metres (default 0.5)."},
```

Update the `dispatch` branch for `find_anchorages_near` (line 134-137):

```python
    if name == "find_anchorages_near":
        return tools.find_anchorages_near(
            vault, lat=args["lat"], lon=args["lon"], radius_nm=args.get("radius_nm", 10.0),
            draft_m=args.get("draft_m"),
            keel_safety_margin_m=args.get("keel_safety_margin_m", 0.5),
        )
```

Update the `assess_anchorage` call in `_call_tool` (lines 169-173):

```python
            result = await assess_anchorage(
                vault,
                lat=args["lat"], lon=args["lon"],
                radius_nm=args.get("radius_nm", 10.0),
                hours=args.get("hours", 12),
                draft_m=args.get("draft_m"),
                keel_safety_margin_m=args.get("keel_safety_margin_m", 0.5))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/server.py tests/test_server.py
git commit -m "feat: advertise draft_m on find_anchorages_near and assess_anchorage"
```

---

## Task 7: Add `controlling_depth_m` to the LLM extract schema

**Files:**
- Modify: `src/pilotbook_mcp/ingest/extract.py`
- Test: `tests/ingest/test_extract.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ingest/test_extract.py`:

```python
def test_extract_schema_includes_controlling_depth():
    from pilotbook_mcp.ingest.extract import ANCHORAGE_TOOL
    props = ANCHORAGE_TOOL["input_schema"]["properties"]
    assert "controlling_depth_m" in props
    assert props["controlling_depth_m"]["type"] == "number"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingest/test_extract.py::test_extract_schema_includes_controlling_depth -v`
Expected: FAIL — `KeyError: 'controlling_depth_m'`

- [ ] **Step 3: Implement**

In `src/pilotbook_mcp/ingest/extract.py`, add to `ANCHORAGE_TOOL["input_schema"]["properties"]`, directly after the `depth_max_m` entry (line 49):

```python
            "depth_max_m": {"type": "number"},
            "controlling_depth_m": {"type": "number",
                "description": "Charted LEAST depth on the approach/entrance (bar, sill, "
                               "shoal) the vessel must cross to enter — NOT the anchoring "
                               "depth. Omit if the page states no entrance/approach depth."},
```

Add one line to `_INSTRUCTIONS`, after the lat/lon sentence (ends line 25 "...W and S are negative."):

```python
Record `controlling_depth_m` ONLY when the page states a least depth on the approach or
entrance (a bar, sill, or shoal the boat must cross) — e.g. "drawing 1.8 m or less",
"controlling depth 2 m", "the bar carries 1.5 m". Never copy the anchoring depth into it.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_extract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/extract.py tests/ingest/test_extract.py
git commit -m "feat: extract controlling_depth_m from entrance-depth prose"
```

---

## Task 8: Deterministic regex confirm pass

**Files:**
- Create: `src/pilotbook_mcp/ingest/confirm.py`
- Test: `tests/ingest/test_confirm.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingest/test_confirm.py`:

```python
from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.ingest.confirm import find_controlling_depths, confirm_controlling_depth


def test_finds_drawing_phrasing():
    assert find_controlling_depths("vessels drawing 1.8 metres or less can enter") == [1.8]


def test_finds_controlling_depth_phrasing():
    assert find_controlling_depths("the controlling depth of 2 m on the bar") == [2.0]


def test_finds_bar_carries_phrasing():
    assert find_controlling_depths("the bar carries 1.5 m at datum") == [1.5]


def test_llm_value_confirmed_by_prose_is_kept():
    a = Anchorage(name="X", source="S", controlling_depth_m=1.8,
                  prose="drawing 1.8 metres or less")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m == 1.8
    assert note is None


def test_llm_value_unconfirmed_is_dropped_and_audited():
    a = Anchorage(name="X", source="S", controlling_depth_m=3.0,
                  prose="a pretty cove with good holding")  # no entrance depth stated
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m is None
    assert note is not None and "not found" in note


def test_regex_only_figure_is_recorded_and_audited():
    a = Anchorage(name="X", source="S", controlling_depth_m=None,
                  prose="drawing 1.2 metres or less; entrance is shallow")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m == 1.2
    assert note is not None and "review" in note


def test_no_depth_anywhere_stays_none_no_note():
    a = Anchorage(name="X", source="S", controlling_depth_m=None,
                  prose="lovely spot, good holding")
    note = confirm_controlling_depth(a)
    assert a.controlling_depth_m is None
    assert note is None


def test_multiple_figures_takes_shallowest():
    a = Anchorage(name="X", source="S", controlling_depth_m=None,
                  prose="drawing 2.0 metres or less; the bar carries 1.4 m")
    confirm_controlling_depth(a)
    assert a.controlling_depth_m == 1.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ingest/test_confirm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pilotbook_mcp.ingest.confirm'`

- [ ] **Step 3: Write the implementation**

Create `src/pilotbook_mcp/ingest/confirm.py`:

```python
"""Deterministic confirmation of controlling_depth_m against the prose.

The LLM extractor proposes a controlling (entrance) depth; this pass keeps it only if a
literal entrance-depth phrase in the prose agrees. Mismatches are dropped to None and
audited. A figure the regex finds when the LLM left it blank is recorded (most
trustworthy: text-sourced) and audited for review. Keel-safety values never survive on
the model's word alone.
"""

from __future__ import annotations

import re

from pilotbook_mcp.models import Anchorage

_DEPTH = r"(\d+(?:\.\d+)?)\s*(?:m|metres|meters)\b"
_PATTERNS = [
    re.compile(rf"drawing\s+{_DEPTH}\s+or\s+less", re.I),
    re.compile(rf"controlling\s+depth\s+(?:of\s+)?{_DEPTH}", re.I),
    re.compile(rf"bar\s+(?:dries|carries)\s+{_DEPTH}", re.I),
    re.compile(rf"entrance[^.\n]{{0,40}}?{_DEPTH}", re.I),
]
_TOLERANCE_M = 0.05


def find_controlling_depths(prose: str | None) -> list[float]:
    """Every entrance/approach depth figure the known phrasings yield, in metres."""
    out: list[float] = []
    for pat in _PATTERNS:
        for m in pat.finditer(prose or ""):
            out.append(float(m.group(1)))
    return out


def confirm_controlling_depth(anchorage: Anchorage) -> str | None:
    """Validate (and possibly correct) anchorage.controlling_depth_m in place.

    Returns an audit note string when human review is warranted, else None.
    """
    found = find_controlling_depths(anchorage.prose)
    proposed = anchorage.controlling_depth_m
    if proposed is not None:
        if any(abs(proposed - f) <= _TOLERANCE_M for f in found):
            return None  # model and prose agree
        anchorage.controlling_depth_m = None
        return (f"{anchorage.name}: LLM proposed controlling_depth_m={proposed} m, "
                "not found in prose — dropped")
    if found:
        anchorage.controlling_depth_m = min(found)  # shallowest = binding gate
        return (f"{anchorage.name}: regex-sourced controlling_depth_m="
                f"{min(found)} m — review")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingest/test_confirm.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pilotbook_mcp/ingest/confirm.py tests/ingest/test_confirm.py
git commit -m "feat: deterministic confirm pass for controlling_depth_m"
```

---

## Task 9: Wire the confirm pass into `run_ingest`

**Files:**
- Modify: `src/pilotbook_mcp/ingest/cli.py:50-97`
- Test: manual (the ingest CLI hits the Anthropic API; no unit test for the live loop)

- [ ] **Step 1: Add the import**

In `src/pilotbook_mcp/ingest/cli.py`, add next to the other ingest imports (after line 18):

```python
from pilotbook_mcp.ingest.confirm import confirm_controlling_depth
```

- [ ] **Step 2: Call confirm before writing each record**

In `run_ingest`, after the `_valid_coords` guard and before `a.source_pdf = ...`
(currently around line 90-91), add:

```python
        depth_note = confirm_controlling_depth(a)
        if depth_note:
            depth_reviews.append(depth_note)
```

Initialise the accumulator with the other counters (line 74):

```python
    written = low = failed = skipped = 0
    depth_reviews: list[str] = []
```

- [ ] **Step 3: Report depth-review notes in the summary**

Replace the final `print(...)` (lines 96-97) with:

```python
    print(f"Ingested {written} new anchorages from {source} "
          f"({skipped} pages already done, {low} need review, {failed} errored). Vault: {root.resolve()}")
    if depth_reviews:
        print(f"{len(depth_reviews)} controlling-depth note(s) to review:")
        for note in depth_reviews:
            print(f"  - {note}")
```

- [ ] **Step 4: Verify the module imports cleanly**

Run: `uv run python -c "import pilotbook_mcp.ingest.cli"`
Expected: no output, exit 0 (no syntax/import error)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS (all tests green)

- [ ] **Step 6: Commit**

```bash
git add src/pilotbook_mcp/ingest/cli.py
git commit -m "feat: confirm controlling_depth_m during ingest with review notes"
```

---

## Final verification

- [ ] Run `uv run pytest` — entire suite green.
- [ ] Run `uv run python -c "import pilotbook_mcp.server, pilotbook_mcp.assess, pilotbook_mcp.tools, pilotbook_mcp.clearance, pilotbook_mcp.ingest.confirm"` — all modules import.
- [ ] Sanity-check the additive contract: a `find_anchorages_near` / `assess_anchorage` call **without** `draft_m` returns the same shape as before (no `keel_clearance` key).

## Notes for the implementer

- `tests/test_tools.py`, `tests/test_assess.py`, and `tests/test_server.py` already build a `Vault` from `tests/fixtures/vault`. Reuse the existing fixture (check `tests/conftest.py`) rather than constructing a new one. If the exact fixture name differs from `vault`, match what those test files already use.
- `tests/test_assess.py` is async and stubs `marine_forecast.fetch_forecast`. Copy the existing stub pattern from a neighbouring async test — do not introduce a different mocking approach.
- The Telegraph Harbour fixture (`tests/fixtures/vault/anchorages/telegraph-harbour.md`) has no `controlling_depth_m`, so it exercises the `unknown` state. If you want a `clear`/`tight`/`unsafe` fixture, add `controlling_depth_m:` to `tests/fixtures/vault/anchorages/test-cove.md` in the same task that needs it.
