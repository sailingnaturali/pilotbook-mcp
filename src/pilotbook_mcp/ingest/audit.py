"""LLM exposure auditor — a curation aid that re-reads an anchorage's prose and
judges its `exposed_sectors`, separate from extraction.

Design (v2): rather than ask the model for a free-form "is this right?" verdict — which
let it invert "protection from X" into exposure — it must classify, from the prose ONLY,
which sectors are `protected_from` and which are `exposed_to`, with a verbatim `evidence`
quote. The suggestion is `exposed_to`; agreement with the current record is computed in
CODE (set equality), not judged by the model. This makes the inversion error structurally
hard and gives every flag a quote a human can verify at a glance.

Calibration still holds: flags have good recall; suggestions are a starting point, not
truth. Refine `_AUDIT_INSTRUCTIONS` as new misread patterns surface.
"""

from __future__ import annotations

from pilotbook_mcp.models import Anchorage

_8POINT = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

_AUDIT_INSTRUCTIONS = """You audit one anchorage's wind/swell EXPOSURE against its pilot-book prose.
`exposed_sectors` = the 8-point compass directions the anchorage is OPEN TO — wind or swell FROM
those directions makes it uncomfortable.

Read the prose for THIS anchorage and report two lists, derived ONLY from what the text explicitly says:
- protected_from: sectors the prose says are sheltered. Triggers: "protection/shelter from X",
  "protected from X", "good in X winds", "in the lee of ... from X".
- exposed_to: sectors the prose says wind or swell ENTERS from. Triggers: "open to X", "exposed to X",
  "X winds/swell enter/reach/roll in", "little/no/limited protection from X" (NEGATION), "good in all
  but X" / "all but X" (= exposed to X), and CONDITIONAL LEE — "better/some protection from X can be
  found in the lee of / behind <feature>", "X winds, though tucked behind <feature> is comfortable"
  (the main anchorage IS exposed to X; the feature only partly shelters → put X in exposed_to).

Hard rules — past audits failed exactly here:
1. "protection/shelter from X" means X is PROTECTED. Put X in protected_from. NEVER put it in exposed_to.
   Worked example: "good protection from SE winds" -> protected_from:["SE"], exposed_to:[]. NOT exposed_to:["SE"].
2. A compass word used only to LOCATE anchoring ("anchor along the SE shore", "depths off the NE shore",
   "moorings near the head") is neither protected nor exposed — ignore it.
3. The prose often describes several lettered sub-spots (q, r, s) or nearby/overflow anchorages.
   exposed_to is the UNION of exposures across the sub-spots OF THIS anchorage; ignore wholly separate anchorages.
4. "protection in most/all winds", "secure in most conditions", "well-protected" — these name NO direction.
   exposed_to is []. Do not guess a direction.
5. Discomfort from current, eddies, tide, boat-wake or ferry-wake is NOT wind exposure — it adds nothing to exposed_to.
6. If the prose names no exposure direction, exposed_to is [] and evidence is "". Do not infer exposure from
   geography, the anchorage's orientation, or vibes — only from explicit words.
7. UNDIRECTED exposure — if the prose says the anchorage is broadly exposed but names NO usable compass
   direction ("open to weather", "open to wind and sea", general "exposed", "rolly", "strong inflow/outflow
   winds", "acceptable/only in settled conditions"), set undirected_exposure=true. Still fill exposed_to with
   only the directions (if any) that ARE explicitly named. Do NOT conclude the anchorage is fully protected.
   Otherwise set undirected_exposure=false.

evidence: quote the exact prose phrase(s) that set exposed_to or undirected_exposure, or "" if none.
Call audit_exposure."""

AUDIT_TOOL = {
    "name": "audit_exposure",
    "description": "Classify the prose's stated protection/exposure for this anchorage.",
    "input_schema": {
        "type": "object",
        "properties": {
            "protected_from": {"type": "array", "items": {"type": "string", "enum": _8POINT},
                               "description": "sectors the prose explicitly says are sheltered"},
            "exposed_to": {"type": "array", "items": {"type": "string", "enum": _8POINT},
                           "description": "sectors the prose explicitly says weather enters from; "
                                          "this becomes the suggested exposed_sectors"},
            "undirected_exposure": {"type": "boolean",
                                    "description": "true if the prose says the anchorage is broadly "
                                                   "exposed/rolly/open-to-weather WITHOUT a usable compass direction"},
            "evidence": {"type": "string",
                         "description": 'verbatim prose phrase(s) supporting exposed_to/undirected_exposure, or "" if none'},
            "audit_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["protected_from", "exposed_to", "undirected_exposure", "evidence", "audit_confidence"],
    },
    "cache_control": {"type": "ephemeral"},
}


def build_audit_prompt() -> list[dict]:
    """System blocks (cached — identical across every record)."""
    return [{"type": "text", "text": _AUDIT_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}]


def audit_record(anchorage: Anchorage, *, client, model: str = "claude-sonnet-4-6") -> dict | None:
    """Classify an anchorage's exposure from its prose.

    Returns the tool input dict ({protected_from, exposed_to, evidence, audit_confidence})
    or None if no verdict came back. The caller decides agreement by comparing
    `exposed_to` to the record's current `exposed_sectors`.
    """
    user = (f"Anchorage: {anchorage.name}\n"
            f"Current exposed_sectors: {anchorage.exposed_sectors}\n\n"
            f"Prose:\n{anchorage.prose}")
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        system=build_audit_prompt(),
        tools=[AUDIT_TOOL],
        tool_choice={"type": "tool", "name": "audit_exposure"},
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "audit_exposure":
            return dict(block.input)
    return None


def disagrees(current: list[str] | None, verdict: dict) -> bool:
    """True when the verdict contradicts the record's current sectors.

    Normal case: flag when the prose-derived `exposed_to` differs from `current`.
    Undirected exposure ("open to weather", "strong inflow winds" — broadly exposed,
    no compass): the existing sectors are a reasonable stand-in for that, so only flag
    when the record claims full protection (empty) while the prose says it's exposed.
    """
    exposed_to = set(verdict.get("exposed_to") or [])
    if verdict.get("undirected_exposure") and not exposed_to:
        # Broadly exposed, no compass to offer: the existing sectors are a fine stand-in,
        # so only flag when the record wrongly claims full protection (empty).
        return not (current or [])
    return set(current or []) != exposed_to


def format_worklist(source: str, flagged: list[dict]) -> str:
    """Render the auditor's disagreements as a triage markdown table.

    Each flagged dict carries: name, current, suggested (=exposed_to), protected_from,
    evidence, audit_confidence.
    """
    order = {"high": 0, "medium": 1, "low": 2}
    rows = sorted(flagged, key=lambda r: order.get(r.get("audit_confidence"), 3))
    lines = [
        f"# Exposure audit — {source}",
        "",
        "Auto-generated by `pilotbook audit`. The model classifies, from the prose only, which "
        "sectors are protected vs exposed; `suggested` = its `exposed_to`, and the flag is computed "
        "in code (set difference). **Verify each `evidence` quote against the record before applying** "
        "— recall is good, but a quote can still be misread. Empty suggested = fully protected.",
        "",
        f"{len(flagged)} flagged.",
        "",
        "| audit | anchorage | current | suggested | protected_from | evidence |",
        "|-------|-----------|---------|-----------|----------------|----------|",
    ]
    for r in rows:
        sug = r.get("suggested") or []
        if not sug:
            sug = "exposed (undirected)" if r.get("undirected_exposure") else "[] (fully protected)"
        else:
            sug = str(sug)
        prot = r.get("protected_from") or []
        ev = (r.get("evidence") or "").replace("|", "\\|").replace("\n", " ").strip() or "—"
        lines.append(f"| {r.get('audit_confidence','?')} | {r.get('name','?')} | "
                     f"{r.get('current') or []} | {sug} | {prot} | {ev} |")
    lines.append("")
    return "\n".join(lines)
