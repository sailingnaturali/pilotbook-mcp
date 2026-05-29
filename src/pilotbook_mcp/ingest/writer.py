"""Write side of ingestion: archive the source PDF, update the manifest, emit .md."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import yaml

from pilotbook_mcp.models import Anchorage


def slugify(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def archive_source(pdf_path: str | Path, source: str, vault: str | Path) -> Path:
    """Copy the original PDF into vault/sources/ under a readable, slugged name."""
    sources_dir = Path(vault) / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    dest = sources_dir / f"{slugify(source)}.pdf"
    shutil.copy2(str(pdf_path), str(dest))
    return dest


def update_manifest(vault: str | Path, entry: dict) -> None:
    manifest = Path(vault) / "manifest.yaml"
    data = {"sources": []}
    if manifest.is_file():
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {"sources": []}
    data.setdefault("sources", []).append(entry)
    manifest.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_anchorage(vault: str | Path, anchorage: Anchorage) -> Path:
    book = slugify(anchorage.source)
    anchor_dir = Path(vault) / "anchorages" / book
    anchor_dir.mkdir(parents=True, exist_ok=True)
    path = anchor_dir / f"{slugify(anchorage.name)}.md"
    path.write_text(anchorage.to_markdown(), encoding="utf-8")
    return path
