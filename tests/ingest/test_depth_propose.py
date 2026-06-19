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
    assert "evidence" in PROPOSE_TOOL["input_schema"]["properties"]


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
