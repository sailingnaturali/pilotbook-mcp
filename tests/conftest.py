import pytest

from pilotbook_mcp import search as S


@pytest.fixture(scope="session")
def model_available():
    """Gate tests that build a real semantic index on the embedding model.

    The [search] tests need fastembed's BAAI/bge-small-en-v1.5, which is
    downloaded from HuggingFace on first use. Skip (don't fail) when the extra
    is absent or the model can't be fetched — e.g. HuggingFace is unreachable
    from a CI runner. A genuine load bug (anything other than a download/
    availability failure) still raises and fails the test, so this never masks
    a real regression. A successful call also warms the model cache once for
    the whole session.
    """
    if not S.HAS_SEARCH:
        pytest.skip("[search] extra not installed")
    try:
        S._vs.Embedder().encode(["warmup"])
    except Exception as exc:  # noqa: BLE001 - classify, then skip or re-raise
        msg = str(exc).lower()
        if ("from any source" in msg or "could not load model" in msg
                or "download" in msg):
            pytest.skip(f"embedding model unavailable offline ({exc})")
        raise
    return True
