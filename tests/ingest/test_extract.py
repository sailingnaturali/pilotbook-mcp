import json

from pilotbook_mcp.ingest.extract import build_system_prompt, extract_record
from pilotbook_mcp.models import Anchorage



class _FakeMessages:
    def __init__(self, payload): self.payload = payload; self.last = None
    def create(self, **kwargs):
        self.last = kwargs
        class Block: type = "text"; text = json.dumps(self.payload)
        class Resp: content = [Block()]
        return Resp()


class _FakeClient:
    def __init__(self, payload): self.messages = _FakeMessages(payload)


def test_build_system_prompt_marks_cache_control():
    blocks = build_system_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "exposed_sectors" in blocks[0]["text"]


def test_extract_record_parses_model_json_into_anchorage():
    payload = {
        "name": "Test Cove", "lat": 48.51, "lon": -123.40,
        "depth_min_m": 3, "depth_max_m": 5, "bottom": ["mud"], "holding": "good",
        "exposed_sectors": ["SW"], "crowding": "moderate", "confidence": "high",
        "prose": "Test Cove. Anchor over mud. Exposed to SW.",
    }
    client = _FakeClient(payload)
    a = extract_record("48°21.50'N ... Test Cove ...", source="TestPilot — X 2025",
                       client=client, model="claude-sonnet-4-6")
    assert isinstance(a, Anchorage)
    assert a.name == "Test Cove"
    assert a.exposed_sectors == ["SW"]
    assert a.source == "TestPilot — X 2025"   # injected, not from the model
    # the chunk text was sent to the model
    assert "Test Cove" in client.messages.last["messages"][0]["content"]


def test_extract_record_returns_none_for_non_anchorage_page():
    class _NullMessages:
        def create(self, **kwargs):
            class Block: type = "text"; text = "null"
            class Resp: content = [Block()]
            return Resp()
    class _NullClient:
        messages = _NullMessages()
    a = extract_record("SalishSeaPilot cover page", source="X", client=_NullClient(), model="m")
    assert a is None
