"""Shared GLogS estimator and schema types used by both LDBC and IMDB optimizers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class SchemaInfo:
    entity_id_to_name: Dict[int, str]
    entity_name_to_id: Dict[str, int]
    relation_id_to_name: Dict[int, str]
    relation_name_to_id: Dict[str, int] = field(default_factory=dict)


class GLogsEstimator:
    """Thin wrapper around the GLogS pattern_count binary.

    estimate_pattern() writes the pattern dict to a temp file, invokes
    scripts/glogs/estimate.sh, and returns the first numeric token from
    the output (the estimated pattern frequency).  Returns 1.0 on any
    failure when quiet=True (the default).
    """

    def __init__(
        self,
        repo_root: Path,
        catalog_rel: str,
        script_rel: str,
        quiet: bool = True,
    ) -> None:
        self.repo_root = repo_root
        self.catalog_path = repo_root / catalog_rel
        self.script_path = repo_root / script_rel
        self.quiet = quiet

        if not self.catalog_path.exists():
            raise FileNotFoundError(f"GLogS catalog not found: {self.catalog_path}")
        if not self.script_path.exists():
            raise FileNotFoundError(f"GLogS estimate.sh not found: {self.script_path}")

    def estimate_pattern(self, pattern: Dict) -> float:
        tmp_dir = Path(tempfile.gettempdir()) / "ispg"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=str(tmp_dir)
        ) as tmp:
            json.dump(pattern, tmp)
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                [str(self.script_path), str(self.catalog_path), str(tmp_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
            )
            stdout = result.stdout.strip()
            if not stdout:
                raise RuntimeError("GLogS output is empty")
            first_line = stdout.splitlines()[0].strip()
            parts = first_line.replace(",", " ").split()
            if not parts:
                raise RuntimeError(f"Failed to parse GLogS output: {first_line}")
            return float(parts[0])
        except subprocess.CalledProcessError as exc:
            if not self.quiet:
                print(
                    f"[WARN] GLogS invocation failed; using fallback F=1.0. stderr:\n{exc.stderr.strip()}",
                    file=sys.stderr,
                )
            return 1.0
        except RuntimeError as exc:
            if not self.quiet:
                print(f"[WARN] {exc}; using fallback F=1.0", file=sys.stderr)
            return 1.0
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def load_ldbc_schema(repo_root: Path) -> SchemaInfo:
    """Load the LDBC GLogS schema from ispg/ldbc/ldbc_glogs_schema.json."""
    schema_path = repo_root / "ispg" / "ldbc" / "ldbc_glogs_schema.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    entity_id_to_name = {e["label"]["id"]: e["label"]["name"] for e in data["entities"]}
    relation_id_to_name = {r["label"]["id"]: r["label"]["name"] for r in data["relations"]}
    entity_name_to_id = {name: idx for idx, name in entity_id_to_name.items()}
    relation_name_to_id = {name: idx for idx, name in relation_id_to_name.items()}
    return SchemaInfo(
        entity_id_to_name=entity_id_to_name,
        entity_name_to_id=entity_name_to_id,
        relation_id_to_name=relation_id_to_name,
        relation_name_to_id=relation_name_to_id,
    )


def load_imdb_schema(repo_root: Path) -> SchemaInfo:
    """Load the IMDB GLogS schema from ispg/imdb/imdb_small_glogs_schema.json."""
    schema_path = repo_root / "ispg" / "imdb" / "imdb_small_glogs_schema.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    entity_id_to_name = {e["label"]["id"]: e["label"]["name"] for e in data["entities"]}
    relation_id_to_name = {r["label"]["id"]: r["label"]["name"] for r in data["relations"]}
    entity_name_to_id = {name: idx for idx, name in entity_id_to_name.items()}
    return SchemaInfo(
        entity_id_to_name=entity_id_to_name,
        entity_name_to_id=entity_name_to_id,
        relation_id_to_name=relation_id_to_name,
    )
