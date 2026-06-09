"""Score keyword/vector/hybrid retrievers for the pilot vault.

Usage: uv run python scripts/eval_search.py <golden.yaml> <vault_dir>

The pilot vault keys anchorages on the ``name`` front-matter field, so we pass
label_field="name" (vault_search defaults to "number" for the colregs schema).
"""

import sys
from pathlib import Path

from vault_search.eval import run_eval

from pilotbook_mcp.search import PILOT


def main() -> None:
    golden, vault = Path(sys.argv[1]), Path(sys.argv[2])
    db = Path("/tmp/pilot-eval.db")
    run_eval(golden, vault, PILOT, db, label_field="name")   # prints the table


if __name__ == "__main__":
    main()
