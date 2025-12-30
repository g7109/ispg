#!/usr/bin/env python3
"""Build a graph catalog for the LDBC SF1 dataset.

This script scans CSV files under the dataset's `dynamic/` and `static/` directories,
infers node tables and relationship tables, and outputs a JSON catalog used by
the compiler and optimizer.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional


# -------------------------------------------------------------
# Naming and formatting utilities
# -------------------------------------------------------------

PARTITION_SUFFIX = re.compile(r"_\d+_\d+$")

LABEL_OVERRIDES: Dict[str, str] = {
    "organisation": "Organisation",
    "organization": "Organisation",
    "person": "Person",
    "place": "Place",
    "comment": "Comment",
    "post": "Post",
    "forum": "Forum",
    "message": "Message",
    "tag": "Tag",
    "tagclass": "TagClass",
    "company": "Company",
}


def strip_partition_suffix(stem: str) -> str:
    return PARTITION_SUFFIX.sub("", stem)


def to_label(token: str) -> str:
    lower = token.lower()
    if lower in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[lower]
    return token[:1].upper() + token[1:]


def to_relationship_name(tokens: Iterable[str]) -> str:
    parts = list(tokens)
    if not parts:
        return ""
    return "".join(part[:1].upper() + part[1:] for part in parts)


def detect_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        first_line = fh.readline()
    pipe = first_line.count("|")
    comma = first_line.count(",")
    if pipe >= comma:
        return "|"
    return ","


def read_header(path: Path, delimiter: str) -> List[str]:
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        header = fh.readline().rstrip("\n\r")
    columns = header.split(delimiter)
    seen: Dict[str, int] = {}
    normalized: List[str] = []
    for col in columns:
        key = col.strip()
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count:
            normalized.append(f"{key}__{count}")
        else:
            normalized.append(key)
    return normalized


# -------------------------------------------------------------
# Data structures
# -------------------------------------------------------------

@dataclass
class NodeEntry:
    label: str
    csv: str
    delimiter: str
    id_column: Optional[str]
    properties: List[str]


@dataclass
class EdgeEndpoint:
    label: str
    column: str


@dataclass
class EdgeEntry:
    type: str
    csv: str
    delimiter: str
    source: EdgeEndpoint
    target: EdgeEndpoint
    properties: List[str]


@dataclass
class Catalog:
    nodes: Dict[str, NodeEntry]
    relationships: Dict[str, EdgeEntry]

    def to_dict(self) -> Dict[str, object]:
        return {
            "nodes": {label: asdict(entry) for label, entry in self.nodes.items()},
            "relationships": {rtype: asdict(entry) for rtype, entry in self.relationships.items()},
        }


# -------------------------------------------------------------
# Parsing logic
# -------------------------------------------------------------

NODE_KEY_CANDIDATES = ("id", "Id", "ID")


def infer_node_id(columns: List[str]) -> Optional[str]:
    for key in NODE_KEY_CANDIDATES:
        if key in columns:
            return key
    # Some CSVs may use the `Label.id` naming convention.
    for col in columns:
        if col.endswith(".id"):
            return col
    return None


def build_catalog(dataset_root: Path) -> Catalog:
    nodes: Dict[str, NodeEntry] = {}
    relationships: Dict[str, EdgeEntry] = {}

    search_dirs = [dataset_root / "dynamic", dataset_root / "static"]
    for root in search_dirs:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.csv")):
            stem = strip_partition_suffix(path.stem)
            if not stem:
                continue
            parts = stem.split("_")
            delimiter = detect_delimiter(path)
            header = read_header(path, delimiter)
            rel_path = path.relative_to(dataset_root).as_posix()

            if len(parts) == 1:
                label = to_label(parts[0])
                if label in nodes:
                    # Keep only one (smallest) partition for each label.
                    continue
                nodes[label] = NodeEntry(
                    label=label,
                    csv=rel_path,
                    delimiter=delimiter,
                    id_column=infer_node_id(header),
                    properties=header,
                )
                continue

            if len(parts) >= 3:
                src_token = parts[0]
                dst_token = parts[-1]
                rel_tokens = parts[1:-1]
                source_label = to_label(src_token)
                target_label = to_label(dst_token)
                rel_type = to_relationship_name(rel_tokens)
                source_col = header[0] if header else ""
                target_col = header[1] if len(header) > 1 else ""
                relationships[stem] = EdgeEntry(
                    type=rel_type,
                    csv=rel_path,
                    delimiter=delimiter,
                    source=EdgeEndpoint(label=source_label, column=source_col),
                    target=EdgeEndpoint(label=target_label, column=target_col),
                    properties=header,
                )
                continue

    return Catalog(nodes=nodes, relationships=relationships)


# -------------------------------------------------------------
# CLI entrypoint
# -------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an LDBC graph catalog JSON")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("datasets/ldbc/sf1"),
        help="LDBC SF1 dataset root directory (default: datasets/ldbc/sf1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ispg/ldbc/ldbc_graph_catalog.json"),
        help="Output JSON path (default: ispg/ldbc/ldbc_graph_catalog.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_root = args.dataset.resolve()
    if not dataset_root.exists():
        raise SystemExit(f"Dataset directory does not exist: {dataset_root}")

    catalog = build_catalog(dataset_root)
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(catalog.to_dict(), fh, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote {output_path}")


if __name__ == "__main__":
    main()
