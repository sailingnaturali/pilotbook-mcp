#!/usr/bin/env python
"""Pre-fetch the [search] embedding model so the test suite runs offline.

Exit 0 when the model is ready (or the search extra isn't installed on this
Python, so the non-search matrix leg still passes); exit 1 on a fetch failure
so the CI caller can retry through a transient HuggingFace outage.
"""

import sys


def main() -> int:
    try:
        from vault_search import Embedder
    except ImportError:
        print("vault_search not installed on this Python; nothing to pre-fetch")
        return 0
    try:
        Embedder().encode(["warmup"])
    except Exception as exc:  # noqa: BLE001 - any fetch/load failure is retryable here
        print(f"embedding model fetch failed: {exc}", file=sys.stderr)
        return 1
    print("embedding model ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
