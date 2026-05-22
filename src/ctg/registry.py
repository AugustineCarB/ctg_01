"""Load and validate the series registry."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ctg.config import REPO_ROOT


@dataclass(frozen=True)
class SeriesEntry:
    id: str
    source: str
    code: str
    notes: str | None = None


def load(path: Path | None = None) -> list[SeriesEntry]:
    path = path or (REPO_ROOT / "registry.yaml")
    raw = yaml.safe_load(path.read_text()) or []
    entries: list[SeriesEntry] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        try:
            e = SeriesEntry(
                id=item["id"],
                source=item["source"],
                code=item["code"],
                notes=item.get("notes"),
            )
        except KeyError as missing:
            raise ValueError(f"registry entry #{i} missing field: {missing}") from None
        expected = f"{e.source.upper()}:{e.code}"
        if e.id != expected:
            raise ValueError(f"registry entry {e.id!r}: id must equal {expected!r}")
        if e.id in seen:
            raise ValueError(f"registry has duplicate id: {e.id}")
        seen.add(e.id)
        entries.append(e)
    return entries
