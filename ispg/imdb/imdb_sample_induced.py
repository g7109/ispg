#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sample a small induced subgraph from processed IMDB graph-style CSVs.

- Detect vertex files: header is just "id"
- Detect edge files: header starts with "src|dst" or "src,dst"
- Seed vertices: label "title" (from title.csv)
- Sampling:
    1. Randomly sample a ratio of title IDs (default 0.00035 ~= 0.035%)
    2. For all edge files whose src/dst label includes "title", collect 1-hop neighbors
    3. Build induced subgraph on the union of sampled titles and their neighbors
- Output:
    - New CSVs under output_dir, with same filenames as the originals
"""

import argparse
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Set


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


def detect_sep(header: str) -> str:
    """Detect field separator from header line."""
    if "|" in header:
        return "|"
    if "," in header:
        return ","
    # fallback
    return "|"


def classify_csv(path: Path) -> Tuple[str, str, List[str]]:
    """Classify CSV as 'vertex', 'edge' or 'other' based on header."""
    with path.open("r", encoding="latin-1", errors="replace") as f:
        header = f.readline().rstrip("\n\r")

    sep = detect_sep(header)
    cols = header.split(sep)

    # vertex: only one column 'id'
    if len(cols) == 1 and cols[0] == "id":
        return "vertex", sep, cols

    # edge: starts with src, dst
    if len(cols) >= 2 and cols[0] == "src" and cols[1] == "dst":
        return "edge", sep, cols

    return "other", sep, cols


def infer_edge_labels(path: Path) -> Tuple[str, str]:
    """
    Infer src/dst vertex labels from edge filename.

    Example:
        title_movieCompanies_companyName.csv
        -> src_label = "title"
        -> dst_label = "companyName"
    """
    stem = path.stem  # e.g., title_movieCompanies_companyName
    parts = stem.split("_")
    if len(parts) >= 3:
        src_label = parts[0]
        dst_label = parts[-1]
    else:
        # Fallback: unknown; won't be very useful
        src_label = "src"
        dst_label = "dst"
    return src_label, dst_label


def sample_title_ids(
    title_path: Path, sep: str, ratio: float, rng: random.Random
) -> Set[str]:
    """Sample a subset of title IDs with given ratio."""
    ids: List[str] = []
    with title_path.open("r", encoding="latin-1", errors="replace") as f:
        _header = f.readline()
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            parts = line.split(sep)
            if not parts:
                continue
            ids.append(parts[0])

    n = len(ids)
    if n == 0:
        raise RuntimeError(f"No title IDs found in {title_path}")

    k = max(1, int(round(n * ratio)))
    if k > n:
        k = n

    print(f"[INFO] Total title vertices: {n}")
    print(f"[INFO] Sampling ratio: {ratio:.6f}, sampled count: {k}")

    sampled = set(rng.sample(ids, k))
    return sampled


def main() -> None:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Sample induced subgraph from IMDB processed CSVs."
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=str(repo_root / "datasets/imdb/imdb"),
        help="Directory containing processed IMDB CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(repo_root / "ispg/imdb/imdb_small"),
        help="Directory to write sampled subgraph CSVs.",
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=0.00035,
        help="Sampling ratio on title vertices (e.g., 0.00035 ~= 0.035%%).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    rng = random.Random(args.seed)

    if not input_dir.is_dir():
        raise SystemExit(f"Input dir not found: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Scan and classify all CSV files
    vertex_files: Dict[str, Tuple[Path, str, List[str]]] = {}
    edge_files: List[Tuple[Path, str, List[str]]] = []
    other_files: List[Tuple[Path, str, List[str]]] = []

    print(f"[INFO] Scanning CSVs under {input_dir}")
    for path in sorted(input_dir.glob("*.csv")):
        role, sep, cols = classify_csv(path)
        if role == "vertex":
            label = path.stem
            vertex_files[label] = (path, sep, cols)
            print(f"[VERTEX] label={label}, file={path.name}")
        elif role == "edge":
            edge_files.append((path, sep, cols))
            print(f"[EDGE]   file={path.name}")
        else:
            other_files.append((path, sep, cols))
            print(f"[SKIP]   (other) file={path.name}")

    if "title" not in vertex_files:
        raise SystemExit("Could not find vertex file for label 'title'.")

    # 2) Sample title IDs
    title_path, title_sep, _ = vertex_files["title"]
    sampled_titles = sample_title_ids(title_path, title_sep, args.ratio, rng)

    # 3) Collect 1-hop neighbors around sampled titles
    kept_vertices: Dict[str, Set[str]] = defaultdict(set)
    kept_vertices["title"].update(sampled_titles)

    print("[INFO] Collecting 1-hop neighbors from edge files touching 'title'...")

    for edge_path, sep, cols in edge_files:
        src_label, dst_label = infer_edge_labels(edge_path)

        # Only expand via edges that touch the 'title' label
        if src_label != "title" and dst_label != "title":
            continue

        print(f"  [EDGE-NEIGH] {edge_path.name} (src={src_label}, dst={dst_label})")

        with edge_path.open("r", encoding="latin-1", errors="replace") as f:
            _header = f.readline()
            for line in f:
                line = line.rstrip("\n\r")
                if not line:
                    continue
                parts = line.split(sep)
                if len(parts) < 2:
                    continue
                src, dst = parts[0], parts[1]

                if src_label == "title" and src in sampled_titles:
                    kept_vertices[src_label].add(src)
                    kept_vertices[dst_label].add(dst)
                elif dst_label == "title" and dst in sampled_titles:
                    kept_vertices[dst_label].add(dst)
                    kept_vertices[src_label].add(src)

    # Print kept vertex counts by label
    print("[INFO] Kept vertex counts by label:")
    for label, ids in kept_vertices.items():
        print(f"  - {label}: {len(ids)}")

    # 4) Write vertex files (only labels with kept vertices)
    print(f"[INFO] Writing sampled vertex CSVs to {output_dir}")
    for label, (path, sep, cols) in vertex_files.items():
        keep_ids = kept_vertices.get(label)
        if not keep_ids:
            # No vertices kept for this label in the induced subgraph
            continue

        out_path = output_dir / path.name
        print(f"  [WRITE VERTEX] {label} -> {out_path.name} ({len(keep_ids)} ids)")

        with path.open("r", encoding="latin-1", errors="replace") as fin, \
             out_path.open("w", encoding="latin-1", errors="replace") as fout:
            header = fin.readline().rstrip("\n\r")
            fout.write(header + "\n")
            for line in fin:
                line_stripped = line.rstrip("\n\r")
                if not line_stripped:
                    continue
                parts = line_stripped.split(sep)
                if not parts:
                    continue
                vid = parts[0]
                if vid in keep_ids:
                    fout.write(line)

    # 5) Write edge files: keep only edges whose endpoints are both kept (induced subgraph)
    print(f"[INFO] Writing sampled edge CSVs to {output_dir}")
    for edge_path, sep, cols in edge_files:
        src_label, dst_label = infer_edge_labels(edge_path)
        src_keep = kept_vertices.get(src_label)
        dst_keep = kept_vertices.get(dst_label)

        if not src_keep or not dst_keep:
            # If either endpoint label is empty, this edge type becomes empty in the subgraph
            continue

        out_path = output_dir / edge_path.name
        kept_edge_count = 0

        with edge_path.open("r", encoding="latin-1", errors="replace") as fin, \
             out_path.open("w", encoding="latin-1", errors="replace") as fout:
            header = fin.readline().rstrip("\n\r")
            fout.write(header + "\n")
            for line in fin:
                line_stripped = line.rstrip("\n\r")
                if not line_stripped:
                    continue
                parts = line_stripped.split(sep)
                if len(parts) < 2:
                    continue
                src, dst = parts[0], parts[1]
                if src in src_keep and dst in dst_keep:
                    fout.write(line)
                    kept_edge_count += 1

        if kept_edge_count > 0:
            print(
                f"  [WRITE EDGE] {edge_path.name} "
                f"({src_label}->{dst_label}), kept edges: {kept_edge_count}"
            )
        else:
            # Delete empty output files to avoid schema confusion
            out_path.unlink(missing_ok=True)

    print("[INFO] Done. Sampled induced subgraph written to:", output_dir)


if __name__ == "__main__":
    main()
