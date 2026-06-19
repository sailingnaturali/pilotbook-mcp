from pilotbook_mcp.ingest.confirm import quote_confirms


def test_quote_confirms_real_prose_with_parenthetical():
    prose = ("Entrance to Anderson Cove is narrow and shallow, but vessels drawing "
             "1.8 metres (six feet) or less can enter with careful attention.")
    assert quote_confirms(prose, "drawing 1.8 metres (six feet) or less") is True


def test_quote_confirms_is_whitespace_and_case_insensitive():
    prose = "The entrance\n  shallows   to 1.1 METRES at zero tide."
    assert quote_confirms(prose, "shallows to 1.1 metres") is True


def test_quote_confirms_spelled_out_number():
    prose = "keels that draw two metres or more should enter at higher tide"
    assert quote_confirms(prose, "draw two metres or more") is True


def test_quote_confirms_bare_m_abbreviation():
    # bare "m" is the most common depth abbreviation in the prose
    prose = "The entrance shallows to 1.5 m at zero tide."
    assert quote_confirms(prose, "shallows to 1.5 m") is True


def test_quote_confirms_no_space_unit_form():
    # run-together "1.5m" / "2m" forms appear in chart-derived text
    assert quote_confirms("sailboats drawing more than 2m enter on a rising tide",
                          "drawing more than 2m") is True


def test_unit_token_does_not_match_letter_words():
    # "calm" ends in m, "draft" contains ft — neither is a measurement token
    assert quote_confirms("the bay is calm and the draft is deep", "the bay is calm") is False


def test_quote_not_in_prose_is_rejected():
    assert quote_confirms("a quiet bay with good holding", "drawing 2 metres or less") is False


def test_quote_without_depth_unit_is_rejected():
    prose = "the entrance is shallow and tricky to navigate"
    assert quote_confirms(prose, "the entrance is shallow") is False


def test_empty_evidence_is_rejected():
    assert quote_confirms("vessels drawing 1.8 metres or less", "") is False
