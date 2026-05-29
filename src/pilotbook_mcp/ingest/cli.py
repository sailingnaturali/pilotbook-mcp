"""`pilotbook` CLI: ingest a PDF into the vault, review extractions, build an index."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

from pilotbook_mcp.ingest import pdf
from pilotbook_mcp.ingest.extract import extract_record
from pilotbook_mcp.ingest.segment import candidate_pages
from pilotbook_mcp.ingest.writer import archive_source, sha256_file, update_manifest, write_anchorage
from pilotbook_mcp.vault import Vault, vault_path


def _make_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def run_ingest(pdf_path: str, source: str, vault: str | None = None) -> None:
    root = Path(vault) if vault else vault_path()
    pages = pdf.extract_pages(pdf_path)
    if pdf.is_scanned("\n".join(pages), len(pages)):
        pages = pdf.ocr_to_text(pdf_path).split("\x0c")
    page_count = len(pages)

    dest = archive_source(pdf_path, source, root)
    update_manifest(root, {
        "retitled": dest.name, "original": Path(pdf_path).name,
        "sha256": sha256_file(pdf_path),
        "publisher": source.split("—")[0].strip() if "—" in source else None,
        "year": next((int(t) for t in source.split() if t.isdigit() and len(t) == 4), None),
        "pages": page_count, "ingested": _dt.date.today().isoformat(),
    })

    client = _make_client()
    written = low = failed = 0
    for page in candidate_pages(pages):
        try:
            a = extract_record(page, source, client=client, model="claude-sonnet-4-6")
        except Exception as exc:  # one bad page must not abort the batch
            failed += 1
            logger.warning("extraction failed on a page: %s", exc)
            continue
        if a is None:
            continue
        write_anchorage(root, a)
        written += 1
        if a.confidence != "high" or not a.exposed_sectors:
            low += 1
    print(f"Ingested {written} anchorages from {source} "
          f"({low} need review, {failed} pages errored). Vault: {root}")


def run_review(vault: str | None = None) -> None:
    v = Vault.load(Path(vault) if vault else None)
    flagged = [a for a in v.anchorages if a.confidence != "high" or not a.exposed_sectors]
    if not flagged:
        print("No anchorages need review.")
        return
    print(f"{len(flagged)} anchorage(s) need review:")
    for a in flagged:
        reason = "low/medium confidence" if a.confidence != "high" else "no exposed_sectors"
        print(f"  - {a.name} ({a.source}) — {reason}")


def run_index(vault: str | None = None) -> None:
    v = Vault.load(Path(vault) if vault else None)
    idx = [{"name": a.name, "lat": a.lat, "lon": a.lon, "source": a.source,
            "exposed_sectors": a.exposed_sectors} for a in v.anchorages]
    (v.root / "index.json").write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote index.json with {len(idx)} anchorages to {v.root}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="pilotbook")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="ingest a pilot-book PDF into the vault")
    p_ing.add_argument("pdf")
    p_ing.add_argument("--source", required=True, help='e.g. "SalishSeaPilot — Gulf Islands 2025"')
    p_ing.add_argument("--vault", default=None)

    p_rev = sub.add_parser("review", help="list anchorages needing human review")
    p_rev.add_argument("--vault", default=None)

    p_idx = sub.add_parser("index", help="write index.json for the runtime server")
    p_idx.add_argument("--vault", default=None)

    args = parser.parse_args()
    if args.cmd == "ingest":
        run_ingest(args.pdf, source=args.source, vault=args.vault)
    elif args.cmd == "review":
        run_review(args.vault)
    elif args.cmd == "index":
        run_index(args.vault)
