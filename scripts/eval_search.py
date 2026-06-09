"""Score keyword/vector/hybrid retrievers for the pilot vault.

Usage: uv run python scripts/eval_search.py <golden.yaml> <vault_dir>

The pilot vault uses ``name`` as its per-anchorage identifier (vault_search.eval
uses ``number``, which matches the colregs vault schema). This script replicates
the same eval logic against ``name`` so the results are correct for this corpus.
"""

import sys
from pathlib import Path

import yaml
import vault_search as vs
from vault_search.search import rrf_fuse

from pilotbook_mcp.search import PILOT


def _labels(index: vs.Index, rowids: list[int]) -> list[str]:
    """Return the ``name`` metadata field for each row — pilot vault's label key."""
    return [index.get_chunk(r).metadata.get("name", "") for r in rowids]


def _retrievers(index: vs.Index, emb: vs.Embedder, query: str, pool: int = 20):
    bm = index.bm25(query, n=pool)
    vec = index.knn(emb.encode([query])[0], n=pool)
    hybrid = [rid for rid, _ in rrf_fuse([bm, vec])]
    return {"keyword": bm, "vector": vec, "hybrid": hybrid}


def recall_at_k(labels: list[str], expect: set[str], k: int) -> float:
    return 1.0 if expect & set(labels[:k]) else 0.0


def reciprocal_rank(labels: list[str], expect: set[str]) -> float:
    for i, label in enumerate(labels, start=1):
        if label in expect:
            return 1.0 / i
    return 0.0


def main() -> None:
    golden, vault = Path(sys.argv[1]), Path(sys.argv[2])
    db = Path("/tmp/pilot-eval.db")

    emb = vs.Embedder()
    chunks = vs.chunk_vault(vault, PILOT)
    vs.build_index(db, chunks, emb)

    queries = yaml.safe_load(golden.read_text())["queries"]
    names = ["keyword", "vector", "hybrid"]
    agg = {n: {"r1": 0.0, "r3": 0.0, "r5": 0.0, "mrr": 0.0} for n in names}

    with vs.Index.open(db) as index:
        for q in queries:
            expect = set(str(x) for x in q["expect"])
            rets = _retrievers(index, emb, q["query"])
            for n in names:
                labels = _labels(index, rets[n])
                agg[n]["r1"] += recall_at_k(labels, expect, 1)
                agg[n]["r3"] += recall_at_k(labels, expect, 3)
                agg[n]["r5"] += recall_at_k(labels, expect, 5)
                agg[n]["mrr"] += reciprocal_rank(labels, expect)

    total = len(queries)
    print(f"\n{'retriever':<10} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'MRR':>6}")
    for n in names:
        m = {k: v / total for k, v in agg[n].items()}
        print(f"{n:<10} {m['r1']:>6.2f} {m['r3']:>6.2f} {m['r5']:>6.2f} {m['mrr']:>6.2f}")


if __name__ == "__main__":
    main()
