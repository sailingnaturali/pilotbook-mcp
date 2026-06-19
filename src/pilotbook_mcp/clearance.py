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
    if controlling_depth_m >= draft_m + margin_m:
        state = "clear"
        note = f"{controlling_depth_m} m at chart datum vs {draft_m} m draft — {_DATUM}."
    elif controlling_depth_m >= draft_m:
        state = "tight"
        note = f"Marginal: {controlling_depth_m} m at chart datum vs {draft_m} m draft — {_DATUM}."
    else:
        state = "unsafe_at_datum"
        note = (f"{controlling_depth_m} m at chart datum is below {draft_m} m draft — "
                "a rising tide may open it.")
    return {"state": state, "controlling_depth_m": controlling_depth_m,
            "draft_m": draft_m, "note": note}
