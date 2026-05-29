"""Load a markdown anchorage vault and its source manifest from disk."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from pilotbook_mcp.models import Anchorage


def vault_path() -> Path:
    """Vault directory from PILOTBOOK_VAULT_PATH (default ~/.pilotbook-vault)."""
    return Path(os.environ.get("PILOTBOOK_VAULT_PATH", "~/.pilotbook-vault")).expanduser()


@dataclass
class Vault:
    root: Path
    anchorages: list[Anchorage]

    @classmethod
    def load(cls, root: Path | None = None) -> "Vault":
        root = Path(root) if root is not None else vault_path()
        anchorages: list[Anchorage] = []
        anchor_dir = root / "anchorages"
        if anchor_dir.is_dir():
            for md in sorted(anchor_dir.glob("*.md")):
                anchorages.append(Anchorage.from_markdown(md.read_text(encoding="utf-8")))
        return cls(root=root, anchorages=anchorages)

    def get(self, name: str) -> Anchorage | None:
        target = name.strip().casefold()
        for a in self.anchorages:
            if a.name.casefold() == target:
                return a
        return None

    def sources(self) -> list[dict]:
        manifest = self.root / "manifest.yaml"
        if not manifest.is_file():
            return []
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        return data.get("sources", [])
