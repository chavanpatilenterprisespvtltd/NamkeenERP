from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    schema_target: str
    migration_policy: str


def load_release_info(root: Path | None = None) -> ReleaseInfo:
    base = root or Path(__file__).resolve().parents[1]
    manifest = base / "config" / "release_manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return ReleaseInfo(
        version=str(data["release"]),
        schema_target=str(data["schema_target"]),
        migration_policy=str(data["migration_policy"]),
    )
