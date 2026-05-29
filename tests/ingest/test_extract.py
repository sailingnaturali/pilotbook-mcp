from pilotbook_mcp.ingest.extract import ANCHORAGE_TOOL, build_system_prompt, extract_record
from pilotbook_mcp.models import Anchorage


class _ToolBlock:
    def __init__(self, input):
        self.type = "tool_use"
        self.name = "record_anchorage"
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


def test_build_system_prompt_marks_cache_control():
    blocks = build_system_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "exposed_sectors" in blocks[0]["text"]


def test_tool_schema_is_cached_and_well_formed():
    assert ANCHORAGE_TOOL["name"] == "record_anchorage"
    assert ANCHORAGE_TOOL["cache_control"] == {"type": "ephemeral"}
    assert ANCHORAGE_TOOL["input_schema"]["required"] == ["is_anchorage"]


def test_extract_record_builds_anchorage_from_tool_call():
    payload = {
        "is_anchorage": True,
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
    assert a.source == "TestPilot — X 2025"     # injected, not from the model
    # the page text was sent, and the tool was forced
    assert "Test Cove" in client.messages.last["messages"][0]["content"]
    assert client.messages.last["tool_choice"] == {"type": "tool", "name": "record_anchorage"}


def test_extract_record_returns_none_for_non_anchorage_page():
    client = _FakeClient({"is_anchorage": False})
    assert extract_record("cover page", source="X", client=client, model="m") is None
