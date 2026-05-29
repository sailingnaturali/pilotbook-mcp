"""Anchorage record and markdown-frontmatter (de)serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import yaml

_FENCE = "---"


@dataclass
class Anchorage:
    name: str
    source: str
    lat: float
    lon: float
    region: str | None = None
    source_page: int | None = None
    depth_min_m: float | None = None
    depth_max_m: float | None = None
    bottom: list[str] = field(default_factory=list)
    holding: str | None = None           # good | fair | poor | variable
    exposed_sectors: list[str] = field(default_factory=list)
    swing_room: str | None = None        # ample | adequate | limited | tight
    tidal_current: str | None = None     # none | weak | moderate | strong | reversing
    cell_coverage: str | None = None     # good | spotty | none
    crowding: str | None = None          # low | moderate | high
    hazards: list[str] = field(default_factory=list)
    last_updated: str | None = None
    confidence: str | None = None        # high | medium | low
    prose: str = ""

    @classmethod
    def from_markdown(cls, text: str) -> "Anchorage":
        if not text.startswith(_FENCE):
            raise ValueError("markdown must start with a '---' frontmatter fence")
        _, fm, body = text.split(_FENCE, 2)
        data = yaml.safe_load(fm) or {}
        known = {f.name for f in fields(cls)} - {"prose"}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(prose=body.lstrip("\n"), **kwargs)

    def to_markdown(self) -> str:
        data = {k: v for k, v in asdict(self).items() if k != "prose"}
        # Drop None/empty so frontmatter stays clean and round-trips.
        data = {k: v for k, v in data.items() if v not in (None, [], "")}
        fm = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
        return f"{_FENCE}\n{fm}\n{_FENCE}\n{self.prose}"
