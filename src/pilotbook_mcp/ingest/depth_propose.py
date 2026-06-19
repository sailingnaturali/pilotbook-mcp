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
  Report controlling_depth_m in METRES (convert feet x0.3048, fathoms x1.8288).
  Entrance phrasings: "the entrance shallows to 1.1 metres at zero tide" (report 1.1);
  "depths in the entrance drop to 0.2 fathoms at zero tide" (0.2 fathoms -> report 0.37);
  "drawing more than 2 m should enter on a rising tide" (report 2); "the bar carries
  6 feet" (6 feet -> report 1.83).
  Also set `evidence` to the exact phrase you read the depth from, quoted verbatim from the prose.
- has_controlling_depth = false when:
  * the figure is a VERTICAL clearance, not depth of water - "bridge clearance 8.5 metres",
    "overhead", "air draft", "mast clearance", "requiring X metres overhead" (these limit
    HEIGHT, not your keel) - NEVER report these as controlling depth;
  * the depth given is where you ANCHOR, not the approach - "anchor in 5-6 metres at zero
    tide", "depths of 5-7 metres inside the lagoon" (these are interior/anchoring depths);
  * the prose only says to "contact"/"call ahead"/"plan entry in advance" WITHOUT stating
    an actual approach depth;
  * the entrance is described only qualitatively - "dries near half tide", "shallow
    approach, shoal-draft only" - with no usable metre/foot/fathom figure;
  * no approach depth is mentioned at all.
When in doubt, set false - a missing value is safe (verified locally); a wrong one is not.
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
            "evidence": {"type": "string",
                "description": "the VERBATIM phrase from the prose that states this depth — "
                               "quote it exactly, do not paraphrase; omit when has_controlling_depth is false"},
        },
        # Only has_controlling_depth is required; a true flag missing controlling_depth_m or
        # evidence is handled in code (returns no proposal) rather than failing validation.
        "required": ["has_controlling_depth"],
    },
    "cache_control": {"type": "ephemeral"},
}


def build_propose_prompt() -> list[dict]:
    """System blocks (cached — identical across every record)."""
    return [{"type": "text", "text": _INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}]


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
                return round(float(depth), 1), evidence  # 0.1 m precision; no 2.4384 noise
            return None, None
    return None, None
