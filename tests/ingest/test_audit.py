from pilotbook_mcp.ingest.audit import (
    AUDIT_TOOL,
    audit_record,
    build_audit_prompt,
    disagrees,
    format_worklist,
)
from pilotbook_mcp.models import Anchorage


class _ToolBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "audit_exposure"
        self.input = payload


class _Resp:
    def __init__(self, payload):
        self.content = [_ToolBlock(payload)]


class _FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.last = None

    def create(self, **kwargs):
        self.last = kwargs
        return _Resp(self.payload)


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def test_build_audit_prompt_cached_and_has_anti_inversion_rule():
    blocks = build_audit_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    # the worked example against the protection->exposure inversion must be present
    assert "NEVER put it in exposed_to" in blocks[0]["text"]


def test_audit_tool_schema_is_structured():
    assert AUDIT_TOOL["name"] == "audit_exposure"
    assert AUDIT_TOOL["cache_control"] == {"type": "ephemeral"}
    assert AUDIT_TOOL["input_schema"]["required"] == [
        "protected_from", "exposed_to", "undirected_exposure", "evidence", "audit_confidence"]


def test_audit_record_returns_classification_and_sends_prose():
    payload = {"protected_from": ["W"], "exposed_to": [], "evidence": "",
               "audit_confidence": "high"}
    client = _FakeClient(payload)
    a = Anchorage(name="Kanish Bay", source="X", lat=50.0, lon=-125.0,
                  exposed_sectors=["W"], prose="Reasonable protection from west winds.")
    res = audit_record(a, client=client, model="claude-sonnet-4-6")
    assert res["protected_from"] == ["W"]
    assert res["exposed_to"] == []
    sent = client.messages.last["messages"][0]["content"]
    assert "Kanish Bay" in sent and "protection from west" in sent
    assert "['W']" in sent  # current sectors are shown to the auditor


def test_disagrees_compares_current_to_exposed_to_in_code():
    # current [W] vs prose-derived exposed_to [] -> disagree (the Kanish case)
    assert disagrees(["W"], {"exposed_to": []}) is True
    # current [] vs exposed_to [] -> agree (the Deepwater fix: protection from SE -> [])
    assert disagrees([], {"exposed_to": []}) is False
    # order-insensitive
    assert disagrees(["S", "W"], {"exposed_to": ["W", "S"]}) is False
    assert disagrees(None, {"exposed_to": ["S"]}) is True


def test_disagrees_undirected_exposure():
    # "open to weather" (no compass) + record already has sectors -> NOT flagged
    assert disagrees(["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                     {"exposed_to": [], "undirected_exposure": True}) is False
    # undirected exposure but record claims fully protected ([]) -> flag it
    assert disagrees([], {"exposed_to": [], "undirected_exposure": True}) is True
    # undirected BUT a direction is also named -> compare normally (don't suppress real fixes)
    assert disagrees(["S"], {"exposed_to": ["S", "SW"], "undirected_exposure": True}) is True
    assert disagrees(["S"], {"exposed_to": ["S"], "undirected_exposure": True}) is False


def test_format_worklist_sorts_by_confidence_and_shows_evidence():
    flagged = [
        {"name": "Low One", "current": [], "suggested": ["S"], "protected_from": [],
         "evidence": "open to the south", "audit_confidence": "low"},
        {"name": "High One", "current": ["W"], "suggested": [], "protected_from": ["W"],
         "evidence": "", "audit_confidence": "high"},
    ]
    md = format_worklist("SalishSeaPilot — Desolation Sound 2025", flagged)
    assert "2 flagged" in md
    assert md.index("High One") < md.index("Low One")   # high sorts first
    assert "[] (fully protected)" in md                  # empty suggestion rendered
    assert "open to the south" in md                     # evidence quote shown
