from pilotbook_mcp.ingest.audit import (
    AUDIT_TOOL,
    audit_record,
    build_audit_prompt,
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


def test_build_audit_prompt_cached_and_has_rules():
    blocks = build_audit_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    # the hard-won rule against the protection->exposure inversion is present
    assert "protection/shelter from X" in blocks[0]["text"]


def test_audit_tool_schema():
    assert AUDIT_TOOL["name"] == "audit_exposure"
    assert AUDIT_TOOL["cache_control"] == {"type": "ephemeral"}
    assert AUDIT_TOOL["input_schema"]["required"] == ["agree", "audit_confidence", "reason"]


def test_audit_record_returns_verdict_and_sends_prose():
    payload = {"agree": False, "suggested_sectors": [], "audit_confidence": "high",
               "reason": "protection from west winds → W is protected"}
    client = _FakeClient(payload)
    a = Anchorage(name="Kanish Bay", source="X", lat=50.0, lon=-125.0,
                  exposed_sectors=["W"], prose="Reasonable protection from west winds.")
    res = audit_record(a, client=client, model="claude-sonnet-4-6")
    assert res["agree"] is False
    assert res["suggested_sectors"] == []
    sent = client.messages.last["messages"][0]["content"]
    assert "Kanish Bay" in sent and "protection from west" in sent
    assert "['W']" in sent  # current sectors are shown to the auditor


def test_format_worklist_sorts_by_confidence_and_renders():
    flagged = [
        {"name": "Low One", "current": [], "suggested": ["S"], "audit_confidence": "low", "reason": "maybe"},
        {"name": "High One", "current": ["W"], "suggested": [], "audit_confidence": "high", "reason": "protected from W"},
    ]
    md = format_worklist("SalishSeaPilot — Desolation Sound 2025", flagged)
    assert "2 flagged" in md
    # high-confidence row sorts above low
    assert md.index("High One") < md.index("Low One")
    assert "[] (fully protected)" in md  # empty suggestion rendered
