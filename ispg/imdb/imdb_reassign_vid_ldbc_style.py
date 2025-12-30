#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reassign global vertex IDs for IMDB graph-style CSVs in an LDBC-style manner.

All vertices share one global ID space:
    - The first vertex table starts from 0 and increases by row.
    - After finishing one table, the next table continues from the new offset.

- Vertex files: header has a single column `id`
- Edge files: header has at least two columns, with the first two being `src`,`dst`
- Other CSV files: copied as-is

Defaults (overridable via CLI):
    input_dir  = ispg/imdb/imdb_small_bfs
    output_dir = ispg/imdb/imdb_small_bfs_vid
    schema     = ispg/imdb/imdb_small_glogs_schema.json

The schema is only used to determine the vertex label order:
    entities[].label.id ascending order corresponds to label.name.
"""

import argparse
from pathlib import Path
import json
import shutil
from typing import Dict, List, Tuple


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


def classify_csv_header(header_line: str) -> Tuple[str, str, List[str]]:
    """
        Classify CSV type based on the header line:
            - vertex: single column named id
            - edge:   at least two columns, with the first two being src, dst
            - other

        Returns (role, sep, cols)
      role ∈ {"vertex", "edge", "other"}
      sep  ∈ {"|", ",", "," (fallback)}
            cols: list of column names
    """
    header = header_line.rstrip("\n\r")
    if "|" in header:
        sep = "|"
    elif "," in header:
        sep = ","
    else:
        sep = ","  # fallback

    cols = header.split(sep)

    if len(cols) == 1 and cols[0] == "id":
        role = "vertex"
    elif len(cols) >= 2 and cols[0] == "src" and cols[1] == "dst":
        role = "edge"
    else:
        role = "other"
    return role, sep, cols


def infer_edge_end_labels(csv_path: Path) -> Tuple[str, str]:
    """
    Infer endpoint labels from the edge filename:
      e.g.  title_movieCompanies_companyName.csv
            -> src_label = "title"
               dst_label = "companyName"

      castInfoVertex_castInfoEdge_person.csv
            -> src_label = "castInfoVertex"
               dst_label = "person"
    """
    stem = csv_path.stem  # without .csv
    parts = stem.split("_")
    if len(parts) < 3:
        raise ValueError(f"Cannot infer edge endpoint labels from filename: {csv_path.name}")
    src_label = parts[0]
    dst_label = parts[-1]
    return src_label, dst_label


def load_vertex_label_order_from_schema(schema_path: Path) -> List[str]:
    """
    Load the entities order from imdb_glogs_schema.json:

    entities: [
      { "label": { "id": 0, "name": "akaName" }, ... },
      ...
    ]

    Returns a list of label.name sorted by ascending label.id.
    """
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    entities = schema.get("entities", [])
    items = []
    for ent in entities:
        label_obj = ent.get("label", {})
        lid = label_obj.get("id")
        lname = label_obj.get("name")
        if lid is None or lname is None:
            continue
        items.append((lid, lname))

    items.sort(key=lambda x: x[0])
    order = [name for _, name in items]
    return order


def reassign_vertex_ids(
    input_dir: Path,
    output_dir: Path,
    schema_path: Path,
) -> None:
    """
     Main pipeline:
        1) Classify vertex/edge/other CSV files
        2) Process vertex files in schema label order:
            - Assign new global IDs for each (label, old_id)
            - Write the rewritten vertex CSVs
        3) Process edge CSVs:
            - Infer src_label and dst_label from filename
            - Rewrite src,dst using the ID mappings
        4) Copy other files as-is
    """
    print(f"[INFO] Input dir : {input_dir}")
    print(f"[INFO] Output dir: {output_dir}")
    print(f"[INFO] Schema    : {schema_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Scan all CSVs
    all_csvs: List[Path] = sorted(input_dir.glob("*.csv"))
    if not all_csvs:
        raise SystemExit(f"No CSV files found in {input_dir}")

    vertex_files: Dict[str, Path] = {}
    edge_files: List[Path] = []
    other_files: List[Path] = []

    for csv_path in all_csvs:
        with csv_path.open("r", encoding="latin-1", errors="replace") as f:
            header_line = f.readline()
        role, sep, cols = classify_csv_header(header_line)

        if role == "vertex":
            label = csv_path.stem  # e.g. "akaName"
            vertex_files[label] = csv_path
            print(f"[DETECT] Vertex file: {csv_path.name} (label={label}, cols={cols})")
        elif role == "edge":
            edge_files.append(csv_path)
            print(f"[DETECT] Edge file  : {csv_path.name} (cols={cols})")
        else:
            other_files.append(csv_path)
            print(f"[DETECT] Other file : {csv_path.name} (cols={cols})")

    # 2) Load label order from schema
    label_order = load_vertex_label_order_from_schema(schema_path)
    print(f"[INFO] Vertex label order from schema: {label_order}")

    # 3) Assign new global IDs for each (label, old_id)
    #    mapping[label][old_id_str] = new_vid_str
    mapping: Dict[str, Dict[str, str]] = {}
    next_vid = 0

    for label in label_order:
        vpath = vertex_files.get(label)
        if vpath is None:
            print(f"[WARN] Vertex label '{label}' has no CSV file in input_dir; skip.")
            continue

        mapping[label] = {}
        out_vpath = output_dir / vpath.name

        print(f"[VERTEX] Reassign IDs for label={label}, file={vpath.name}")

        with vpath.open("r", encoding="latin-1", errors="replace") as fin, \
                out_vpath.open("w", encoding="latin-1", errors="replace") as fout:

            header_line = fin.readline()
            fout.write(header_line)

            # Detect delimiter
            header = header_line.rstrip("\n\r")
            if "|" in header:
                sep = "|"
            elif "," in header:
                sep = ","
            else:
                sep = ","

            cnt = 0
            for line in fin:
                line_stripped = line.rstrip("\n\r")
                if not line_stripped:
                    continue
                parts = line_stripped.split(sep)
                if not parts:
                    continue
                old_id = parts[0]
                new_id = str(next_vid)

                # Record mapping
                mapping[label][old_id] = new_id

                # Write rewritten ID row
                parts[0] = new_id
                fout.write(sep.join(parts) + "\n")

                next_vid += 1
                cnt += 1

        print(f"    -> assigned {cnt} vertices for label={label}, "
              f"ID range [{next_vid - cnt}, {next_vid - 1}]")

    print(f"[INFO] Total vertices assigned: {next_vid}")

    # 4) Process edge files: rewrite src,dst
    for epath in edge_files:
        src_label, dst_label = infer_edge_end_labels(epath)
        out_epath = output_dir / epath.name

        print(f"[EDGE] Rewriting edge file: {epath.name} "
              f"(src_label={src_label}, dst_label={dst_label})")

        src_map = mapping.get(src_label)
        dst_map = mapping.get(dst_label)
        if src_map is None or dst_map is None:
            raise SystemExit(
                f"[ERROR] Missing vertex mapping for src_label='{src_label}' "
                f"or dst_label='{dst_label}' when processing {epath.name}"
            )

        missing_src = 0
        missing_dst = 0
        total_edges = 0

        with epath.open("r", encoding="latin-1", errors="replace") as fin, \
                out_epath.open("w", encoding="latin-1", errors="replace") as fout:

            header_line = fin.readline()
            fout.write(header_line)

            header = header_line.rstrip("\n\r")
            if "|" in header:
                sep = "|"
            elif "," in header:
                sep = ","
            else:
                sep = ","

            for line in fin:
                line_stripped = line.rstrip("\n\r")
                if not line_stripped:
                    continue
                parts = line_stripped.split(sep)
                if len(parts) < 2:
                    continue

                old_src = parts[0]
                old_dst = parts[1]

                new_src = src_map.get(old_src)
                new_dst = dst_map.get(old_dst)

                if new_src is None:
                    missing_src += 1
                    continue
                if new_dst is None:
                    missing_dst += 1
                    continue

                parts[0] = new_src
                parts[1] = new_dst
                fout.write(sep.join(parts) + "\n")
                total_edges += 1

        if missing_src or missing_dst:
            print(
                f"    -> kept {total_edges} edges, "
                f"skipped {missing_src} with unknown src, {missing_dst} with unknown dst"
            )
        else:
            print(f"    -> kept {total_edges} edges, no missing endpoints")

    # 5) Copy other files
    for opath in other_files:
        out_opath = output_dir / opath.name
        print(f"[COPY ] Other CSV file: {opath.name}")
        shutil.copy2(opath, out_opath)

    print("[INFO] Done. New graph with LDBC-style global IDs is in:", output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reassign global vertex IDs for IMDB CSVs (LDBC-style)."
    )
    repo_root = _repo_root()
    parser.add_argument(
        "--input-dir",
        type=str,
        default=str(repo_root / "ispg/imdb/imdb_small_bfs"),
        help="Input directory containing IMDB graph-style CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(repo_root / "ispg/imdb/imdb_small_bfs_vid"),
        help="Output directory for re-assigned CSVs.",
    )
    parser.add_argument(
        "--schema",
        type=str,
        default=str(repo_root / "ispg/imdb/imdb_small_glogs_schema.json"),
        help="Path to imdb_glogs_schema.json (used only for vertex label order).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    schema_path = Path(args.schema)

    if not input_dir.is_dir():
        raise SystemExit(f"Input dir not found: {input_dir}")
    if not schema_path.is_file():
        raise SystemExit(f"Schema file not found: {schema_path}")

    reassign_vertex_ids(input_dir, output_dir, schema_path)


if __name__ == "__main__":
    main()
