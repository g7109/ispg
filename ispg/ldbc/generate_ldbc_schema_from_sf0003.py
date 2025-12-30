#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-generate a GLogS schema from CSV files under `datasets/ldbc/sf0.003_vid`.

- Vertex entities come from all "vertex tables" (the first header column is `id`,
  and there is no `*.id` column):
    person.csv       -> Person
    post.csv         -> Post
    comment.csv      -> Comment
    forum.csv        -> Forum
    organisation.csv -> Organisation
    place.csv        -> Place
    tag.csv          -> Tag
    tagclass.csv     -> TagClass
    message.csv      -> Message

- Edge relations come from all "edge tables" (the header contains at least two
  `*.id` or `id` columns):
    person_knows_person.csv          -> Person_knows_Person
    post_hasCreator_person.csv       -> Post_hasCreator_Person
    post_isLocatedIn_place.csv       -> Post_isLocatedIn_Place
    ...

Additionally, it *forces* the following 5 message-related relations (if the
corresponding CSV files exist):
    Comment_replyOf_Message
    Message_hasCreator_Person
    Message_hasTag_Tag
    Message_isLocatedIn_Place
    Person_likes_Message
"""

import os
import csv
import json
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


# Use sf0.003_vid as the source.
DATA_DIR = str(_repo_root() / "datasets/ldbc/sf0.003_vid")

# Schema output path.
SCHEMA_OUT = str(_repo_root() / "ispg/ldbc/ldbc_glogs_schema_from_sf0003.json")


# ---------- Naming mapping: filename token -> entity label ----------

ENTITY_NAME_MAP = {
    "person": "Person",
    "post": "Post",
    "comment": "Comment",
    "forum": "Forum",
    "organisation": "Organisation",
    "organization": "Organisation",
    "place": "Place",
    "tag": "Tag",
    "tagclass": "TagClass",
    "message": "Message",
}

def entity_label_from_basename(base: str) -> str:
    key = base.lower()
    if key in ENTITY_NAME_MAP:
        return ENTITY_NAME_MAP[key]
    if not base:
        return base
    return base[0].upper() + base[1:]


def relation_label_from_basename(base: str, src_label: str, dst_label: str) -> str:
    """
    Examples:
      base = "person_knows_person"
      src_label = "Person"
      dst_label = "Person"
      -> "Person_knows_Person"

      base = "post_hasCreator_person"
      -> "Post_hasCreator_Person"

      base = "comment_replyOf_message"
      src_label = "Comment"
      dst_label = "Message"
      -> "Comment_replyOf_Message"
    """
    parts = base.split("_")
    if len(parts) < 3:
        return f"{src_label}_{base}_{dst_label}"
    middle = "_".join(parts[1:-1])
    return f"{src_label}_{middle}_{dst_label}"


# ---------- Classify CSV as vertex/edge table ----------

def classify_csv(path):
    """
    Return ('vertex', header) or ('edge', header) or ('unknown', header).

    Rules:
      - vertex table: the first header column is "id" and there is no "*.id" column
      - edge table: the header contains at least two columns ending with ".id" or equal to "id"
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader, None)
        if header is None:
            return "unknown", []

    header = [h.strip() for h in header]
    first = header[0] if header else ""
    has_dot_id = any(h.endswith(".id") for h in header)

    # Vertex table
    if first == "id" and not has_dot_id:
        return "vertex", header

    # Edge table: at least two '*.id' / 'id' columns.
    id_cols = [h for h in header if h.endswith(".id") or h == "id"]
    if len(id_cols) >= 2:
        return "edge", header

    return "unknown", header


def main():
    # 1) Scan all CSVs and split into vertex/edge tables.
    csv_paths = []
    for name in os.listdir(DATA_DIR):
        if not name.lower().endswith(".csv"):
            continue
        full = os.path.join(DATA_DIR, name)
        if not os.path.isfile(full):
            continue
        csv_paths.append(full)

    csv_paths.sort()
    print(f"Scanning directory: {DATA_DIR}")
    print(f"Found CSV files: {len(csv_paths)}\n")

    vertex_files = []  # (full_path, base_name, header)
    edge_files = []    # (full_path, base_name, header)
    edge_basenames = set()

    for path in csv_paths:
        fname = os.path.basename(path)
        base = fname[:-4]  # Strip trailing .csv

        kind, header = classify_csv(path)
        if kind == "vertex":
            vertex_files.append((path, base, header))
        elif kind == "edge":
            edge_files.append((path, base, header))
            edge_basenames.add(base)
        else:
            print(f"[WARN] Could not classify CSV: {fname}, header = {header}")

    print("Vertex tables:")
    for _, base, _ in vertex_files:
        print("  -", base + ".csv")
    print("\nEdge tables:")
    for _, base, _ in edge_files:
        print("  -", base + ".csv")

    # 2) Build entity label set.
    entity_label_set = set()
    for _, base, _ in vertex_files:
        entity_label_set.add(entity_label_from_basename(base))

    entity_labels = sorted(entity_label_set)
    entity_name_to_id = {name: i for i, name in enumerate(entity_labels)}

    print("\nEntity types (by id order):")
    for i, name in enumerate(entity_labels):
        print(f"  id={i:2d}, name={name}")

    # 3) Build relation label set (deduplicated).
    relation_specs = {}  # label_name -> (src_label, dst_label)

    for path, base, header in edge_files:
        # Find the first two id columns; infer src/dst labels from their prefixes.
        id_indices = []
        id_prefixes = []
        for idx, col in enumerate(header):
            col = col.strip()
            if col.endswith(".id"):
                prefix = col.split(".")[0]
                id_indices.append(idx)
                id_prefixes.append(prefix)
            elif col == "id":
                id_indices.append(idx)
                id_prefixes.append(None)

        if len(id_indices) < 2:
            print(f"[WARN] Edge table {os.path.basename(path)} has <2 id columns; skipping")
            continue

        src_prefix, dst_prefix = id_prefixes[0], id_prefixes[1]

        if src_prefix is None:
            src_label = entity_label_from_basename(base.split("_")[0])
        else:
            src_label = entity_label_from_basename(src_prefix)

        if dst_prefix is None:
            dst_label = entity_label_from_basename(base.split("_")[-1])
        else:
            dst_label = entity_label_from_basename(dst_prefix)

        if src_label not in entity_name_to_id:
            print(
                f"[WARN] Edge table {os.path.basename(path)}: src entity {src_label} not in entity list; auto-adding"
            )
            entity_name_to_id[src_label] = len(entity_name_to_id)
            entity_labels.append(src_label)

        if dst_label not in entity_name_to_id:
            print(
                f"[WARN] Edge table {os.path.basename(path)}: dst entity {dst_label} not in entity list; auto-adding"
            )
            entity_name_to_id[dst_label] = len(entity_name_to_id)
            entity_labels.append(dst_label)

        rel_label = relation_label_from_basename(base, src_label, dst_label)

        if rel_label in relation_specs:
            old_src, old_dst = relation_specs[rel_label]
            if old_src != src_label or old_dst != dst_label:
                print(
                    f"[WARN] Relation {rel_label} has conflicting src/dst: "
                    f"old=({old_src},{old_dst}), new=({src_label},{dst_label})"
                )
        else:
            relation_specs[rel_label] = (src_label, dst_label)

    # 3.5 Force-add 5 message-related relations (if the corresponding CSV exists).
    # Expected filenames:
    # comment_replyOf_message.csv
    # message_hasCreator_person.csv
    # message_hasTag_tag.csv
    # message_isLocatedIn_place.csv
    # person_likes_message.csv

    def ensure_entity(label_name: str):
        if label_name not in entity_name_to_id:
            entity_name_to_id[label_name] = len(entity_name_to_id)
            entity_labels.append(label_name)

    # Ensure referenced entities exist.
    for name in ["Comment", "Message", "Person", "Tag", "Place"]:
        ensure_entity(name)

    forced_specs = [
        ("comment_replyOf_message", "Comment", "Message"),
        ("message_hasCreator_person", "Message", "Person"),
        ("message_hasTag_tag", "Message", "Tag"),
        ("message_isLocatedIn_place", "Message", "Place"),
        ("person_likes_message", "Person", "Message"),
    ]

    for base, src_label, dst_label in forced_specs:
        if base not in edge_basenames:
            # Skip if the corresponding CSV does not exist.
            continue
        rel_label = relation_label_from_basename(base, src_label, dst_label)
        if rel_label not in relation_specs:
            relation_specs[rel_label] = (src_label, dst_label)
            print(f"[FORCE-ADD] Relation {rel_label} from {base}.csv")

    # relation_labels: sort by name; ids start from 0.
    relation_labels = sorted(relation_specs.keys())
    print("\nRelation types (by id order):")
    for i, name in enumerate(relation_labels):
        src_label, dst_label = relation_specs[name]
        print(f"  id={i:2d}, name={name}, src={src_label}, dst={dst_label}")

    # 4) Assemble schema JSON.
    # Re-order entities by id (according to entity_name_to_id).
    entities = []
    for name, eid in sorted(entity_name_to_id.items(), key=lambda kv: kv[1]):
        entities.append({
            "columns": [],
            "label": {
                "id": eid,
                "name": name,
            }
        })

    relations = []
    for rid, rel_name in enumerate(relation_labels):
        src_label, dst_label = relation_specs[rel_name]
        src_id = entity_name_to_id[src_label]
        dst_id = entity_name_to_id[dst_label]

        relations.append({
            "columns": [],
            "entity_pairs": [{
                "src": {"id": src_id, "name": src_label},
                "dst": {"id": dst_id, "name": dst_label},
            }],
            "label": {
                "id": rid,
                "name": rel_name,
            }
        })

    schema = {
        "entities": entities,
        "relations": relations,
        "is_table_id": True,
        "is_column_id": False,
    }

    # 5) Write schema JSON.
    os.makedirs(os.path.dirname(SCHEMA_OUT), exist_ok=True)
    with open(SCHEMA_OUT, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    print(f"\nGenerated schema file: {SCHEMA_OUT}")
    print(f"Entity count: {len(entities)}, Relation count: {len(relations)}")


if __name__ == "__main__":
    main()
