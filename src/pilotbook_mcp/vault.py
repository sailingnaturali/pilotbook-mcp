"""Load a markdown anchorage vault and its source manifest from disk."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
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
    _by_name: dict[str, Anchorage] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, root: Path | None = None) -> "Vault":
        root = Path(root) if root is not None else vault_path()
        anchorages: list[Anchorage] = []
        by_name: dict[str, Anchorage] = {}
        anchor_dir = root / "anchorages"
        if anchor_dir.is_dir():
            for md in sorted(anchor_dir.rglob("*.md")):
                # Per-file guard (R3): one malformed frontmatter must not blank
                # all 673 anchorages — skip it, warn, keep serving the rest
                # (the ingest CLI already guards per-page; the runtime matches).
                try:
                    a = Anchorage.from_markdown(md.read_text(encoding="utf-8"))
                except (ValueError, yaml.YAMLError, OSError) as exc:
                    print(f"pilotbook-mcp: skipping {md.relative_to(root)}: {exc}",
                          file=sys.stderr)
                    continue
                key = a.name.strip().casefold()
                if key in by_name:
                    print(f"pilotbook-mcp: duplicate anchorage name "
                          f"{a.name!r} ({md.relative_to(root)}) — "
                          "name lookups resolve to the first one loaded",
                          file=sys.stderr)
                else:
                    by_name[key] = a
                anchorages.append(a)
        return cls(root=root, anchorages=anchorages, _by_name=by_name)

    def get(self, name: str) -> Anchorage | None:
        return self._by_name.get(name.strip().casefold())

    def sources(self) -> list[dict]:
        manifest = self.root / "manifest.yaml"
        if not manifest.is_file():
            return []
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        return data.get("sources", [])
