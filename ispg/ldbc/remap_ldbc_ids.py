#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-process datasets/ldbc/sf0.003 and write results to sf0.003_vid.

1. Vertex tables (person/post/message/comment/forum/organisation/place/tag/tagclass)
    - All vertices share a single global ID space (no overlap across types):
         Person -> a consecutive ID range
         Post   -> continues after Person
         Comment / Forum / Organisation / Place / Tag / TagClass follow
    - post.csv and message.csv share the same "Post" ID mapping.
    - Output vertex tables keep only a single "id" column; all other attributes are dropped.

2. Edge tables (all other CSV files)
    - Detect *.id columns in the header (e.g., Person.id, Post.id)
    - Keep only ID columns; drop timestamps and other attributes
    - Remap each ID column using the corresponding vertex-type mapping

3. Notes
    - Read-only on sf0.003 input; does not modify original files
    - Writes all outputs to sf0.003_vid
    - Automatically ignores legacy id_mapping_*.csv (if present)
"""

import csv
import os
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


ROOT_IN = str(_repo_root() / "datasets/ldbc/sf0.003")
ROOT_OUT = str(_repo_root() / "datasets/ldbc/sf0.003_vid")

# Filename (without .csv) -> vertex label
FILE_BASE_TO_LABEL = {
    "person": "Person",
    "post": "Post",
    "message": "Post",      # Treat message as a Post view; share the same ID mapping
    "comment": "Comment",
    "forum": "Forum",
    "organisation": "Organisation",
    "place": "Place",
    "tag": "Tag",
    "tagclass": "TagClass",
}

# Vertex label processing order (global ID assignment)
LABEL_ORDER = [
    "Person",
    "Post",
    "Comment",
    "Forum",
    "Organisation",
    "Place",
    "Tag",
    "TagClass",
]

# Vertex label -> set of old IDs
label_to_ids = {lbl: set() for lbl in set(FILE_BASE_TO_LABEL.values())}

# Vertex label -> { old_id(str) -> new_id(str) }
label_to_idmap = {}


def ensure_out_dir():
    os.makedirs(ROOT_OUT, exist_ok=True)


def collect_vertex_ids():
    """
    Phase 1: scan all vertex tables under ROOT_IN and collect old IDs per label.
    """
    csv_files = sorted(
        f for f in os.listdir(ROOT_IN)
        if f.lower().endswith(".csv")
    )

    for fname in csv_files:
        # Skip legacy id_mapping_* files.
        if fname.startswith("id_mapping_"):
            continue

        base = fname[:-4]  # strip .csv
        if base not in FILE_BASE_TO_LABEL:
            continue  # Not a vertex table

        label = FILE_BASE_TO_LABEL[base]
        path = os.path.join(ROOT_IN, fname)

        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="|")
            header = next(reader, None)
            if header is None:
                print(f"[{fname}] empty vertex table, skipping")
                continue

            try:
                id_idx = header.index("id")
            except ValueError:
                raise RuntimeError(f"[{fname}] vertex table missing 'id' column")

            for row in reader:
                if not row:
                    continue
                vid = row[id_idx]
                label_to_ids[label].add(vid)

    # Print summary.
    for label, ids in label_to_ids.items():
        print(f"[collect_vertex_ids] label {label}: collected {len(ids)} old ids")


def build_id_mappings():
    """
        Phase 2: build a global old_id -> new_id mapping for all vertex labels.

        Allocation rules:
            - Allocate ID ranges in LABEL_ORDER
            - Within each label, sort by numeric value when possible, otherwise lexicographically
            - New IDs are globally contiguous: 0,1,2,... and do not overlap across labels
    """
    current_offset = 0

    # Process labels in the predefined order.
    for label in LABEL_ORDER:
        ids = label_to_ids.get(label, set())
        if not ids:
            label_to_idmap[label] = {}
            print(
                f"[build_id_mappings] label {label}: no vertices, skipping, "
                f"current offset = {current_offset}"
            )
            continue

        def sort_key(x):
            try:
                return int(x)
            except ValueError:
                return x

        sorted_ids = sorted(ids, key=sort_key)
        id_map = {}
        for old_id in sorted_ids:
            id_map[old_id] = str(current_offset)
            current_offset += 1
        label_to_idmap[label] = id_map

        print(
            f"[build_id_mappings] label {label}: old id count = {len(sorted_ids)}, "
            f"new id range = [{id_map[sorted_ids[0]]}, {current_offset - 1}]"
        )

    # If there are additional labels not covered by LABEL_ORDER, handle them too.
    for label, ids in label_to_ids.items():
        if label in LABEL_ORDER:
            continue
        if not ids:
            label_to_idmap[label] = {}
            continue

        def sort_key(x):
            try:
                return int(x)
            except ValueError:
                return x

        sorted_ids = sorted(ids, key=sort_key)
        id_map = {}
        for old_id in sorted_ids:
            id_map[old_id] = str(current_offset)
            current_offset += 1
        label_to_idmap[label] = id_map

        print(
            f"[build_id_mappings-extra] label {label}: old id count = {len(sorted_ids)}, "
            f"new id range = [{id_map[sorted_ids[0]]}, {current_offset - 1}]"
        )


def remap_vertex_file(fname: str, label: str):
    """
    Phase 3 (part): rewrite one vertex table.
    - read from ROOT_IN and write to ROOT_OUT/fname
    - replace the id column via label_to_idmap[label]
    - output keeps only one column: "id"
    """
    in_path = os.path.join(ROOT_IN, fname)
    out_path = os.path.join(ROOT_OUT, fname)
    id_map = label_to_idmap.get(label, {})

    with open(in_path, "r", encoding="utf-8", newline="") as f_in, \
         open(out_path, "w", encoding="utf-8", newline="") as f_out:
        reader = csv.reader(f_in, delimiter="|")
        writer = csv.writer(f_out, delimiter="|", lineterminator="\n")

        header = next(reader, None)
        if header is None:
            print(f"[{fname}] empty vertex table, writing an empty file")
            writer.writerow(["id"])
            return

        try:
            id_idx = header.index("id")
        except ValueError:
            raise RuntimeError(f"[{fname}] vertex table missing 'id' column")

        # New header keeps only one column.
        writer.writerow(["id"])

        missing = 0
        total = 0
        for row in reader:
            if not row:
                continue
            total += 1
            old_id = row[id_idx]
            new_id = id_map.get(old_id)
            if new_id is None:
                missing += 1
                # Skip rows with unmapped IDs.
                continue
            writer.writerow([new_id])

    print(
        f"[remap_vertex_file] {fname}: total {total} rows, remapped {total - missing} rows, "
        f"dropped {missing} rows (mapping not found)"
    )


def remap_edge_file(fname: str):
    """
    Phase 3 (part): rewrite one edge table.
    - read from ROOT_IN and write to ROOT_OUT/fname
    - detect *.id columns in the header (e.g., Person.id, Post.id)
    - keep only ID columns; drop timestamps and other attributes
    - remap each ID value using label_to_idmap[label]
    """
    in_path = os.path.join(ROOT_IN, fname)
    out_path = os.path.join(ROOT_OUT, fname)

    with open(in_path, "r", encoding="utf-8", newline="") as f_in:
        reader = csv.reader(f_in, delimiter="|")
        header = next(reader, None)
        if header is None:
            print(f"[{fname}] empty edge table, writing an empty file")
            with open(out_path, "w", encoding="utf-8", newline="") as f_out:
                writer = csv.writer(f_out, delimiter="|", lineterminator="\n")
                writer.writerow(header or [])
            return

        # Find all ID columns.
        id_indices = []
        id_labels = []  # Vertex label aligned with id_indices
        for idx, col in enumerate(header):
            col = col.strip()
            if col.endswith(".id"):
                prefix = col.split(".")[0]  # Person.id -> Person
                id_indices.append(idx)
                id_labels.append(prefix)
            elif col == "id":
                # Edge tables normally won't use plain "id", but handle it defensively.
                id_indices.append(idx)
                id_labels.append(None)  # Unknown vertex label

        if len(id_indices) < 2:
            # Fewer than two ID columns: copy the file as-is.
            print(f"[remap_edge_file] {fname}: fewer than 2 id columns, copying as-is")
            with open(out_path, "w", encoding="utf-8", newline="") as f_out:
                writer = csv.writer(f_out, delimiter="|", lineterminator="\n")
                writer.writerow(header)
                for row in reader:
                    writer.writerow(row)
            return

        with open(out_path, "w", encoding="utf-8", newline="") as f_out:
            writer = csv.writer(f_out, delimiter="|", lineterminator="\n")

            # New header: keep only ID column names.
            new_header = [header[i] for i in id_indices]
            writer.writerow(new_header)

            total = 0
            written = 0
            skipped_missing = 0
            for row in reader:
                if not row:
                    continue
                total += 1
                new_row = []
                skip_row = False

                for idx, lbl in zip(id_indices, id_labels):
                    val = row[idx]

                    if lbl is None:
                        # Unknown vertex type: keep as-is.
                        new_row.append(val)
                        continue

                    # Merge "Message" into "Post" (defensive).
                    if lbl == "Message":
                        lbl_key = "Post"
                    else:
                        lbl_key = lbl

                    id_map = label_to_idmap.get(lbl_key)
                    if not id_map:
                        # No mapping for this label: keep as-is.
                        new_row.append(val)
                        continue

                    new_val = id_map.get(val)
                    if new_val is None:
                        # Endpoint not mapped -> edge points to a dropped vertex; drop the whole edge row.
                        skip_row = True
                        skipped_missing += 1
                        break
                    new_row.append(new_val)

                if skip_row:
                    continue

                writer.writerow(new_row)
                written += 1

    print(
        f"[remap_edge_file] {fname}: total {total} rows, kept {written} rows, "
        f"dropped {skipped_missing} rows (endpoint mapping not found)"
    )


def main():
    ensure_out_dir()

    # 1. Collect old IDs from vertex tables.
    collect_vertex_ids()

    # 2. Build global old_id -> new_id mapping.
    build_id_mappings()

    # 3. Traverse ROOT_IN and rewrite vertex/edge tables to ROOT_OUT.
    csv_files = sorted(
        f for f in os.listdir(ROOT_IN)
        if f.lower().endswith(".csv")
    )

    # 3.1 Vertex tables: keep only id and rewrite.
    for fname in csv_files:
        if fname.startswith("id_mapping_"):
            continue
        base = fname[:-4]
        if base in FILE_BASE_TO_LABEL:
            label = FILE_BASE_TO_LABEL[base]
            remap_vertex_file(fname, label)

    # 3.2 Edge tables: rewrite ID columns; drop timestamps/attributes.
    for fname in csv_files:
        if fname.startswith("id_mapping_"):
            continue
        base = fname[:-4]
        if base in FILE_BASE_TO_LABEL:
            continue  # Vertex table already handled
        remap_edge_file(fname)

    print("Global ID remap and pruning finished. Output dir:", ROOT_OUT)


if __name__ == "__main__":
    main()
