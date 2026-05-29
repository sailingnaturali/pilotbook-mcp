from pilotbook_mcp.ingest.segment import COORD_RE, MARKER_RE, candidate_pages


def test_coord_regex_matches_pilot_book_format():
    assert COORD_RE.search("48°21.50'N 123°42.68'W")
    assert not COORD_RE.search("Anchor over mud in 3-5 metres.")


def test_marker_regex_matches_ebook_anchorage_marker():
    assert MARKER_RE.search("tB9::Oak-Bay-GI")
    assert not MARKER_RE.search("t::Gulf-Islands-cover-GI")


def test_candidate_pages_keeps_coord_or_marker_pages():
    pages = [
        "Cover page, no coords or marker.",
        "tB9::Oak-Bay-GI\nOak Bay. Good holding.",
        "48°21.50'N 123°42.68'W\nTest Cove. Exposed to SW.",
        "Region intro prose with no markers at all.",
    ]
    kept = candidate_pages(pages)
    assert len(kept) == 2
    assert kept[0][0] == 2 and "Oak Bay" in kept[0][1]
    assert kept[1][0] == 3 and "Test Cove" in kept[1][1]
