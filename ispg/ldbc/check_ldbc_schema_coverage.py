#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check which CSV files under LDBC sf0.003_vid are covered by ldbc_glogs_schema.json,
and which entity/relation types are missing.

- Vertex table classification
    * header has exactly one column "id" -> vertex table
    * filename (without .csv) is treated as the base entity name, e.g., person/post/comment/forum/place
    * mapped to an entity label name: Person/Post/Comment/Forum/Place/TagClass/Organisation/...
    * if the label is not present in schema['entities'][*].label.name, it's considered "missing"

- Edge table classification
    * header contains at least two columns like "Xxx.id" (or "id") -> edge table
    * filename (without .csv) is treated as the base relation name, e.g., person_knows_person
    * mapped to a relation label like "Person_knows_Person", "Post_hasCreator_Person"
    * if the label is not present in schema['relations'][*].label.name, it's considered "missing"

Output:
    Prints only missing entities/relations. You can copy the output to extend the schema.
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


SCHEMA_PATH = str(_repo_root() / "ispg/ldbc/ldbc_glogs_schema.json")
DATA_DIR = str(_repo_root() / "datasets/ldbc/sf0.003_vid")


# ---------- Helper: load existing entity/relation labels from schema ----------

def load_schema(schema_path):
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    entity_labels = {e["label"]["name"] for e in schema.get("entities", [])}
    relation_labels = {r["label"]["name"] for r in schema.get("relations", [])}

    print("== Schema overview ==")
    print(f"Entity type count: {len(entity_labels)}")
    print(", ".join(sorted(entity_labels)))
    print(f"\nRelation type count: {len(relation_labels)}")
    print(", ".join(sorted(relation_labels)))
    print("\n======================\n")

    return entity_labels, relation_labels


# ---------- Name mapping: filename -> entity/relation label ----------

ENTITY_TOKEN_MAP = {
    "person": "Person",
    "post": "Post",
    "message": "Message",      # Treat message as an independent entity to help detect missing schema entries
    "comment": "Comment",
    "forum": "Forum",
    "organisation": "Organisation",
    "organization": "Organisation",  # Defensive alias
    "place": "Place",
    "city": "City",
    "country": "Country",
    "continent": "Continent",
    "tag": "Tag",
    "tagclass": "TagClass",
    "university": "University",
    "company": "Company",
}

def entity_label_from_basename(base: str) -> str:
    base_lower = base.lower()
    if base_lower in ENTITY_TOKEN_MAP:
        return ENTITY_TOKEN_MAP[base_lower]
    # Default: capitalize first letter.
    if not base:
        return base
    return base[0].upper() + base[1:]


def relation_label_from_basename(base: str) -> str:
    """
    Examples:
    - person_knows_person       -> Person_knows_Person
    - post_hasCreator_person    -> Post_hasCreator_Person
    - comment_replyOf_message   -> Comment_replyOf_Message
    - place_isPartOf_place      -> Place_isPartOf_Place
    """
    parts = base.split("_")
    if len(parts) < 3:
        # Non-standard format: best-effort capitalization.
        return base[0].upper() + base[1:] if base else base

    first = entity_label_from_basename(parts[0])
    last = entity_label_from_basename(parts[-1])
    middle_parts = parts[1:-1]  # Middle relation tokens kept as-is (hasCreator / isLocatedIn / ...)

    return "_".join([first] + middle_parts + [last])


# ---------- Classify CSV as vertex/edge table ----------

def classify_csv(path):
    """
    Returns ('vertex', header) / ('edge', header) / ('unknown', header)
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader, None)
        if header is None:
            return "unknown", []

    header = [h.strip() for h in header]
    # Vertex table: single id column.
    if len(header) == 1 and header[0] == "id":
        return "vertex", header

    # Edge table: at least two *.id (or id) columns.
    id_cols = [h for h in header if h.endswith(".id") or h == "id"]
    if len(id_cols) >= 2:
        return "edge", header

    return "unknown", header


# ---------- Main logic ----------

def main():
    entity_labels, relation_labels = load_schema(SCHEMA_PATH)

    missing_entities = []   # (file, label)
    missing_relations = []  # (file, label)
    covered_entities = []   # Optional: record covered items
    covered_relations = []

    csv_files = sorted(
        f for f in os.listdir(DATA_DIR)
        if f.lower().endswith(".csv")
    )

    print(f"Scanning directory: {DATA_DIR}")
    print(f"Found {len(csv_files)} CSV files\n")

    for fname in csv_files:
        # Defensive: skip id_mapping_* files.
        if fname.startswith("id_mapping_"):
            continue

        full_path = os.path.join(DATA_DIR, fname)
        base = fname[:-4]  # strip .csv

        kind, header = classify_csv(full_path)

        if kind == "vertex":
            label = entity_label_from_basename(base)
            if label in entity_labels:
                covered_entities.append((fname, label))
            else:
                missing_entities.append((fname, label))

        elif kind == "edge":
            label = relation_label_from_basename(base)
            if label in relation_labels:
                covered_relations.append((fname, label))
            else:
                missing_relations.append((fname, label))
        else:
            # Neither a vertex table nor a standard edge table.
            print(f"[WARN] Unclassifiable CSV: {fname}, header={header}")

    # -------- Print missing only --------
    print("===== Missing entity types (file -> inferred entity label) =====")
    if not missing_entities:
        print("(no missing entities)")
    else:
        for fname, label in missing_entities:
            print(f"{fname}  ->  {label}")

    print("\n===== Missing relation types (file -> inferred relation label) =====")
    if not missing_relations:
        print("(no missing relations)")
    else:
        for fname, label in missing_relations:
            print(f"{fname}  ->  {label}")

    # If you also want to print covered items, uncomment below:
    # print("\n===== Covered entity types (file -> entity label) =====")
    # for fname, label in covered_entities:
    #     print(f"{fname}  ->  {label}")
    #
    # print("\n===== Covered relation types (file -> relation label) =====")
    # for fname, label in covered_relations:
    #     print(f"{fname}  ->  {label}")


if __name__ == "__main__":
    main()
