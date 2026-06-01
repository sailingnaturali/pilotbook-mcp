from pilotbook_mcp.ingest.cleanup import clean_file_text, examples, strip_subspot_letters


def test_strips_subspot_letters_before_capital_or_paren():
    prose = ("q Good protection east of Jane Islet. r Excellent protection. "
             "t There is swing room. q (Deepwater Bay): Good protection from SE.")
    cleaned, n = strip_subspot_letters(prose)
    assert n == 4
    assert cleaned == ("Good protection east of Jane Islet. Excellent protection. "
                       "There is swing room. (Deepwater Bay): Good protection from SE.")


def test_does_not_eat_real_words_a_or_i():
    # "a" and "I" are not in q-z; a single "a" before a capital must survive
    prose = "Anchor in a Vancouver Island cove. I recommend caution."
    cleaned, n = strip_subspot_letters(prose)
    assert n == 0
    assert cleaned == prose


def test_does_not_touch_letters_inside_words_or_numbers():
    prose = "Aqua-blue water. 3 Brown's Bay Resort has fuel. The u-shaped bay is calm."
    cleaned, n = strip_subspot_letters(prose)
    assert n == 0  # 'q' inside Aqua, the number 3, and 'u-' (hyphen not space) all skipped
    assert cleaned == prose


def test_requires_following_capital_or_paren():
    prose = "s safe and secure"  # lowercase after the letter -> not a sub-spot label
    cleaned, n = strip_subspot_letters(prose)
    assert n == 0


def test_clean_file_text_preserves_frontmatter_and_comments():
    text = (
        "---\n"
        "name: Carrington Bay\n"
        'source: "X"\n'
        "exposed_sectors: []   # fully enclosed — keep this comment\n"
        "---\n"
        "q Good protection. r Excellent protection.\n"
    )
    cleaned, n = clean_file_text(text)
    assert n == 2
    assert "# fully enclosed — keep this comment" in cleaned   # frontmatter untouched
    assert "exposed_sectors: []" in cleaned
    assert cleaned.endswith("Good protection. Excellent protection.\n")
    assert "\nq Good" not in cleaned


def test_examples_returns_snippets():
    ex = examples("q (Deepwater Bay): Good protection from SE winds and more text here")
    assert ex and ex[0].startswith("q (Deepwater Bay)")
