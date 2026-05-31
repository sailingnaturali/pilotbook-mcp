"""`pilotbook` CLI: ingest a PDF into the vault, review extractions, build an index."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

from pilotbook_mcp.ingest import pdf
from pilotbook_mcp.ingest.audit import audit_record, disagrees, format_worklist
from pilotbook_mcp.ingest.extract import extract_record
from pilotbook_mcp.ingest.segment import candidate_pages
from pilotbook_mcp.ingest.writer import archive_source, sha256_file, slugify, update_manifest, write_anchorage
from pilotbook_mcp.models import Anchorage
from pilotbook_mcp.vault import Vault, vault_path


def _covered_pages(root: Path, source: str) -> set[int]:
    """PDF page numbers already ingested for this source — lets ingest resume."""
    book_dir = root / "anchorages" / slugify(source)
    covered: set[int] = set()
    if book_dir.is_dir():
        for md in book_dir.glob("*.md"):
            a = Anchorage.from_markdown(md.read_text(encoding="utf-8"))
            m = re.search(r"#page=(\d+)", a.source_pdf or "")
            if m:
                covered.add(int(m.group(1)))
    return covered


def _valid_coords(lat, lon) -> bool:
    if lat is None or lon is None:
        return True  # coordless anchorage is allowed — just won't be geo-searchable
    return -90 <= lat <= 90 and -180 <= lon <= 180


def _make_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def run_ingest(pdf_path: str, source: str, vault: str | None = None, force: bool = False) -> None:
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

    if force:
        # Clear this book's existing records so re-extraction can't leave stale
        # duplicates behind when the model names an anchorage slightly differently.
        book_dir = root / "anchorages" / slugify(source)
        if book_dir.is_dir():
            shutil.rmtree(book_dir)
    covered = set() if force else _covered_pages(root, source)
    client = _make_client()
    written = low = failed = skipped = 0
    for page_no, page in candidate_pages(pages):
        if page_no in covered:
            skipped += 1
            continue
        try:
            a = extract_record(page, source, client=client, model="claude-sonnet-4-6")
        except Exception as exc:  # one bad page must not abort the batch
            failed += 1
            logger.warning("extraction failed on page %d: %s", page_no, exc)
            continue
        if a is None:
            continue
        if not _valid_coords(a.lat, a.lon):
            failed += 1
            logger.warning("skipping %s: invalid coordinates (%s, %s)", a.name, a.lat, a.lon)
            continue
        a.source_pdf = f"../sources/{dest.name}#page={page_no}"
        write_anchorage(root, a)
        written += 1
        if a.confidence != "high" or not a.exposed_sectors:
            low += 1
    print(f"Ingested {written} new anchorages from {source} "
          f"({skipped} pages already done, {low} need review, {failed} errored). Vault: {root.resolve()}")


def run_review(vault: str | None = None) -> None:
    v = Vault.load(Path(vault) if vault else None)
    if not v.anchorages:
        print(f"No anchorages found in {v.root.resolve()} — is PILOTBOOK_VAULT_PATH set correctly?")
        return
    # An empty exposed_sectors means "exposed to nothing" — but only `confidence: high`
    # confirms that's a real reading (fully enclosed) vs. "couldn't tell". So:
    #   empty + high       -> confirmed fully protected (NOT flagged)
    #   empty + low/medium -> exposure undetermined (flag)
    #   has sectors + low/medium -> sectors uncertain (flag)
    undetermined = [a for a in v.anchorages if not a.exposed_sectors and a.confidence != "high"]
    low_conf = [a for a in v.anchorages if a.exposed_sectors and a.confidence != "high"]
    if not undetermined and not low_conf:
        print("No anchorages need review.")
        return
    if undetermined:
        print(f"{len(undetermined)} anchorage(s) with undetermined exposure (no exposed_sectors, "
              f"unconfirmed — set `confidence: high` if fully protected, or add exposed_sectors):")
        for a in sorted(undetermined, key=lambda x: x.name):
            print(f"  - {a.name} ({a.source})")
    if low_conf:
        if undetermined:
            print("")
        print(f"{len(low_conf)} anchorage(s) low/medium confidence in exposed_sectors:")
        for a in sorted(low_conf, key=lambda x: x.name):
            print(f"  - {a.name} ({a.source})")


def _anchorage_rel_path(a) -> str:
    return f"anchorages/{slugify(a.source)}/{slugify(a.name)}.md"


def _clean_region(region: str | None) -> str:
    return (region or "Uncategorized").strip().strip("[]").strip() or "Uncategorized"


def run_index(vault: str | None = None) -> None:
    v = Vault.load(Path(vault) if vault else None)
    if not v.anchorages:
        print(f"No anchorages found in {v.root.resolve()} — is PILOTBOOK_VAULT_PATH set? (nothing indexed)")
        return

    # Machine index for the runtime server.
    idx = [{"name": a.name, "lat": a.lat, "lon": a.lon, "source": a.source,
            "region": _clean_region(a.region), "exposed_sectors": a.exposed_sectors,
            "path": _anchorage_rel_path(a)} for a in v.anchorages]
    (v.root / "index.json").write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human-browsable index grouped by region.
    groups: dict[str, list] = {}
    for a in v.anchorages:
        groups.setdefault(_clean_region(a.region), []).append(a)
    lines = ["# Anchorage Index", "",
             f"_Generated by `pilotbook index`. {len(v.anchorages)} anchorages across "
             f"{len(v.sources())} book(s)._", ""]
    for region in sorted(groups):
        lines.append(f"## {region}")
        lines.append("")
        for a in sorted(groups[region], key=lambda x: x.name):
            page = f", p.{a.source_page}" if a.source_page else ""
            exp = "/".join(a.exposed_sectors) if a.exposed_sectors else "—"
            lines.append(f"- [{a.name}]({_anchorage_rel_path(a)}) — {a.source}{page} · exposed: {exp}")
        lines.append("")
    (v.root / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote index.json + INDEX.md ({len(idx)} anchorages) to {v.root}")


def run_audit(source: str, vault: str | None = None, model: str = "claude-sonnet-4-6") -> None:
    """LLM-audit one book's exposed_sectors against its prose; write a triage worklist."""
    v = Vault.load(Path(vault) if vault else None)
    book = slugify(source)
    records = [a for a in v.anchorages if slugify(a.source) == book]
    if not records:
        print(f"No anchorages for source {source!r} in {v.root.resolve()} — check --source / PILOTBOOK_VAULT_PATH.")
        return
    client = _make_client()
    flagged, errored = [], 0
    for a in records:
        try:
            res = audit_record(a, client=client, model=model)
        except Exception as exc:  # one bad record must not abort the audit
            errored += 1
            logger.warning("audit failed on %s: %s", a.name, exc)
            continue
        if res and disagrees(a.exposed_sectors, res):
            flagged.append({"name": a.name, "current": a.exposed_sectors,
                            "suggested": res.get("exposed_to") or [],
                            "protected_from": res.get("protected_from") or [],
                            "evidence": res.get("evidence") or "",
                            "audit_confidence": res.get("audit_confidence")})
    audits_dir = v.root / "audits"
    audits_dir.mkdir(exist_ok=True)
    path = audits_dir / f"{book}.audit.md"
    path.write_text(format_worklist(source, flagged), encoding="utf-8")
    print(f"Audited {len(records)} records for {source} — {len(flagged)} flagged, {errored} errored. "
          f"Worklist: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="pilotbook")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="ingest a pilot-book PDF into the vault")
    p_ing.add_argument("pdf")
    p_ing.add_argument("--source", required=True, help='e.g. "SalishSeaPilot — Gulf Islands 2025"')
    p_ing.add_argument("--vault", default=None)
    p_ing.add_argument("--force", action="store_true",
                       help="re-extract every page, ignoring already-ingested coverage")

    p_rev = sub.add_parser("review", help="list anchorages needing human review")
    p_rev.add_argument("--vault", default=None)

    p_idx = sub.add_parser("index", help="write index.json for the runtime server")
    p_idx.add_argument("--vault", default=None)

    p_aud = sub.add_parser("audit", help="LLM-audit a book's exposed_sectors against its prose")
    p_aud.add_argument("--source", required=True, help='e.g. "SalishSeaPilot — Desolation Sound 2025"')
    p_aud.add_argument("--vault", default=None)
    p_aud.add_argument("--model", default="claude-sonnet-4-6")

    args = parser.parse_args()
    if args.cmd == "ingest":
        run_ingest(args.pdf, source=args.source, vault=args.vault, force=args.force)
    elif args.cmd == "review":
        run_review(args.vault)
    elif args.cmd == "index":
        run_index(args.vault)
    elif args.cmd == "audit":
        run_audit(args.source, vault=args.vault, model=args.model)
