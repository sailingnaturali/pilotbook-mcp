from pilotbook_mcp.ingest.segment import COORD_RE, split_on_coordinates


def test_coord_regex_matches_pilot_book_format():
    assert COORD_RE.search("48°21.50'N 123°42.68'W")
    assert not COORD_RE.search("Anchor over mud in 3-5 metres.")


def test_split_groups_text_under_each_coordinate():
    text = (
        "Front matter with no coords.\n"
        "48°21.50'N 123°42.68'W\n"
        "Test Cove. Anchor over mud. Good holding. Exposed to SW.\n"
        "48°22.65'N 123°42.64'W\n"
        "Quiet Bay. Well protected. Mud bottom.\n"
    )
    chunks = split_on_coordinates(text)
    assert len(chunks) == 2
    assert "Test Cove" in chunks[0]
    assert "48°21.50'N" in chunks[0]
    assert "Quiet Bay" in chunks[1]


def test_split_empty_when_no_coords():
    assert split_on_coordinates("no coordinates here at all") == []
