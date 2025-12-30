#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sample an induced subgraph from processed IMDB graph CSVs using
label-level multi-hop BFS.

- Vertex files: header is "id"
- Edge files: header starts with "src,dst" or "src|dst"
- Start from label "title":
    1) Randomly sample a small ratio of title IDs as seeds.
    2) Build a label graph from edge filenames, each edge CSV is
       processed at most once.
    3) Multi-hop BFS on labels: whenever a label already has some
       kept vertex IDs, we use the corresponding edge file(s) to
       pull neighbor vertex IDs into the other label.
    4) Repeat until no edge file can propagate new IDs.
- Finally, write an induced subgraph over all labels that have
  non-empty kept IDs.

This matches the strategy:
    - Use all table labels as the search space
    - Do not re-expand labels that were already reached in the previous hop
    - Only expand to labels that are not covered yet
    - Scan each edge CSV at most once
"""

import argparse
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Set


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


# ---------- Utilities ----------

def detect_sep(header: str) -> str:
    """Detect field separator from header line."""
    if "|" in header:
        return "|"
    if "," in header:
        return ","
    # fallback
    return "|"


def classify_csv(path: Path) -> Tuple[str, str, List[str]]:
    """
    Classify a CSV file by its header.
    Returns ("vertex" / "edge" / "other", sep, columns).
    """
    with path.open("r", encoding="latin-1", errors="replace") as f:
        header = f.readline().rstrip("\n\r")

    sep = detect_sep(header)
    cols = header.split(sep)

    # Vertex: single column 'id'
    if len(cols) == 1 and cols[0] == "id":
        return "vertex", sep, cols

    # Edge: first two columns are src,dst
    if len(cols) >= 2 and cols[0] == "src" and cols[1] == "dst":
        return "edge", sep, cols

    return "other", sep, cols


def infer_edge_labels(path: Path) -> Tuple[str, str]:
    """
    Infer src/dst vertex labels from an edge filename.

    For example:
        title_movieCompanies_companyName.csv
        -> src_label = "title"
        -> dst_label = "companyName"

        castInfoVertex_castInfoEdge_person.csv
        -> src_label = "castInfoVertex"
        -> dst_label = "person"
    """
    stem = path.stem  # e.g., title_movieCompanies_companyName
    parts = stem.split("_")
    if len(parts) >= 3:
        src_label = parts[0]
        dst_label = parts[-1]
    else:
        src_label = "src"
        dst_label = "dst"
    return src_label, dst_label


def sample_title_ids(
    title_path: Path, sep: str, ratio: float, rng: random.Random
) -> Set[str]:
    """Sample title IDs from title.csv as seeds according to the given ratio."""
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
    print(f"[INFO] Sampling ratio on title: {ratio:.6f}, sampled count: {k}")

    sampled = set(rng.sample(ids, k))
    return sampled


# ---------- Main logic ----------

def main() -> None:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Sample induced subgraph from IMDB with label-level BFS."
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
        default=str(repo_root / "ispg/imdb/imdb_small_bfs"),
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

    # 1) Scan and classify all CSVs
    vertex_files: Dict[str, Tuple[Path, str, List[str]]] = {}
    edge_files: List[Dict] = []
    other_files: List[Tuple[Path, str, List[str]]] = []

    print(f"[INFO] Scanning CSVs under {input_dir}")
    for path in sorted(input_dir.glob("*.csv")):
        role, sep, cols = classify_csv(path)
        if role == "vertex":
            label = path.stem
            vertex_files[label] = (path, sep, cols)
            print(f"[VERTEX] label={label}, file={path.name}")
        elif role == "edge":
            src_label, dst_label = infer_edge_labels(path)
            edge_files.append(
                {
                    "path": path,
                    "sep": sep,
                    "cols": cols,
                    "src_label": src_label,
                    "dst_label": dst_label,
                }
            )
            print(
                f"[EDGE]   file={path.name}, "
                f"src_label={src_label}, dst_label={dst_label}"
            )
        else:
            other_files.append((path, sep, cols))
            print(f"[SKIP]   (other) file={path.name}")

    if "title" not in vertex_files:
        raise SystemExit("Could not find vertex file for label 'title'.")

    # 2) Sample seeds from title
    title_path, title_sep, _ = vertex_files["title"]
    kept_ids: Dict[str, Set[str]] = defaultdict(set)
    sampled_titles = sample_title_ids(title_path, title_sep, args.ratio, rng)
    kept_ids["title"].update(sampled_titles)

    # Covered labels (labels with non-empty kept vertex IDs)
    covered_labels: Set[str] = set()
    if kept_ids["title"]:
        covered_labels.add("title")

    # 3) Label-level BFS: scan each edge file at most once
    print("[INFO] Start label-level BFS over edge files...")
    pending_edges = list(edge_files)
    iteration = 0

    while True:
        iteration += 1
        progress = False
        next_pending_edges = []

        print(f"[INFO] BFS iteration {iteration}, pending edges: {len(pending_edges)}")

        for ed in pending_edges:
            path = ed["path"]
            sep = ed["sep"]
            src_label = ed["src_label"]
            dst_label = ed["dst_label"]

            src_known = src_label in covered_labels and len(kept_ids[src_label]) > 0
            dst_known = dst_label in covered_labels and len(kept_ids[dst_label]) > 0

            # If neither endpoint has any kept IDs yet, defer this edge to the next round
            if not src_known and not dst_known:
                next_pending_edges.append(ed)
                continue

            # At least one endpoint already has kept IDs; use it to pull neighbor IDs
            print(
                f"  [BFS-EDGE] processing {path.name} "
                f"(src_label={src_label}, dst_label={dst_label})"
            )

            new_src_ids: Set[str] = set()
            new_dst_ids: Set[str] = set()

            with path.open("r", encoding="latin-1", errors="replace") as fin:
                _header = fin.readline()
                for line in fin:
                    line = line.rstrip("\n\r")
                    if not line:
                        continue
                    parts = line.split(sep)
                    if len(parts) < 2:
                        continue
                    src, dst = parts[0], parts[1]

                    # If src_label is covered and src is kept, then keep dst in dst_label
                    if src_label in covered_labels and src in kept_ids[src_label]:
                        if dst not in kept_ids[dst_label]:
                            new_dst_ids.add(dst)

                    # If dst_label is covered and dst is kept, then keep src in src_label
                    if dst_label in covered_labels and dst in kept_ids[dst_label]:
                        if src not in kept_ids[src_label]:
                            new_src_ids.add(src)

            if new_src_ids or new_dst_ids:
                progress = True
                if new_src_ids:
                    kept_ids[src_label].update(new_src_ids)
                    covered_labels.add(src_label)
                    print(
                        f"    [+] {src_label}: added {len(new_src_ids)} vertices "
                        f"(total={len(kept_ids[src_label])})"
                    )
                if new_dst_ids:
                    kept_ids[dst_label].update(new_dst_ids)
                    covered_labels.add(dst_label)
                    print(
                        f"    [+] {dst_label}: added {len(new_dst_ids)} vertices "
                        f"(total={len(kept_ids[dst_label])})"
                    )
                # This edge has already propagated new IDs; do not scan it again
            else:
                # This edge cannot propagate any new IDs with current knowledge.
                # Re-scanning later will not help either, so we drop it.
                pass

        pending_edges = next_pending_edges

        if not progress:
            print("[INFO] BFS converged, no more new vertices can be added.")
            break

        if not pending_edges:
            print("[INFO] All edge files processed.")
            break

    print("[INFO] Kept vertex counts by label after BFS:")
    for label in sorted(covered_labels):
        print(f"  - {label}: {len(kept_ids[label])}")

    # 4) Write vertex CSVs: only labels with kept IDs
    print(f"[INFO] Writing sampled vertex CSVs to {output_dir}")
    for label, (path, sep, cols) in vertex_files.items():
        keep = kept_ids.get(label)
        if not keep:
            continue

        out_path = output_dir / path.name
        print(f"  [WRITE VERTEX] {label} -> {out_path.name} ({len(keep)} ids)")

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
                if vid in keep:
                    fout.write(line)

    # 5) Write edge CSVs: induced subgraph (both endpoints are kept)
    print(f"[INFO] Writing sampled edge CSVs to {output_dir}")
    for ed in edge_files:
        path = ed["path"]
        sep = ed["sep"]
        src_label = ed["src_label"]
        dst_label = ed["dst_label"]

        src_keep = kept_ids.get(src_label)
        dst_keep = kept_ids.get(dst_label)
        if not src_keep or not dst_keep:
            continue

        out_path = output_dir / path.name
        kept_edge_count = 0

        with path.open("r", encoding="latin-1", errors="replace") as fin, \
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
                f"  [WRITE EDGE] {path.name} "
                f"({src_label}->{dst_label}), kept edges: {kept_edge_count}"
            )
        else:
            # Delete empty output files
            out_path.unlink(missing_ok=True)

    print("[INFO] Done. Sampled induced subgraph written to:", output_dir)


if __name__ == "__main__":
    main()
