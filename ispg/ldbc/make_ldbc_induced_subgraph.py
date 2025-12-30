#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate an induced subgraph from sf0.1 using Post seed vertices (single-pass version).

- Select a fraction of Post.id from dynamic/post_0_0.csv as seeds
    * fraction ~= sf0.003 / sf0.1 = 0.03, i.e., keep ~3% posts as the "core"
- Expand outward from these posts by scanning relevant edge tables once:
    * allowed: expand from seed Post to Person / Comment / Forum / Tag / Place / Organisation / TagClass
    * allowed: keep edges between already-selected vertices
    * disallowed: use newly discovered Person/Forum/Comment to pull in more new Post/Person
- Each table is visited at most once to avoid multi-round BFS explosion
- All output CSVs are written to ROOT_OUT, and filenames drop the `_0_0` suffix
- Input/output delimiter is '|'
"""

import csv
import os
from pathlib import Path

# ------------------ Paths and sampling ratio ------------------ #

def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


ROOT_IN = str(_repo_root() / "datasets/ldbc/sf0.1")
ROOT_OUT = str(_repo_root() / "datasets/ldbc/sf0.003")

# Source/target scale factors (inferred from directory names)
SRC_SCALE = 0.1
TGT_SCALE = 0.003
POST_FRACTION = TGT_SCALE / SRC_SCALE   # = 0.03, sample ~3% posts as seeds

# ------------------ ID sets for each entity ------------------ #

person_ids = set()
post_ids = set()
comment_ids = set()
forum_ids = set()
org_ids = set()
place_ids = set()
tag_ids = set()
tagclass_ids = set()


# ------------------ Common helpers ------------------ #

def strip_partition_suffix(filename: str) -> str:
    """
    Convert xxx_0_0.csv -> xxx.csv (only changes the last suffix).
    """
    if not filename.lower().endswith(".csv"):
        return filename
    base = filename[:-4]  # strip .csv
    if base.endswith("_0_0"):
        base = base[:-4]
    return base + ".csv"


def ensure_out_dir():
    os.makedirs(ROOT_OUT, exist_ok=True)


def filter_table(rel_path: str, keep_fn):
    """
        Generic "visit a table" helper:
        - read from ROOT_IN/rel_path
        - call keep_fn(row, header) per row to decide whether to keep it
            keep_fn may also update ID sets (person_ids / post_ids / ...)
        - write to ROOT_OUT with the `_0_0` suffix removed from filename
        - print kept row count
    """
    in_path = os.path.join(ROOT_IN, rel_path)
    filename = os.path.basename(rel_path)
    out_name = strip_partition_suffix(filename)
    out_path = os.path.join(ROOT_OUT, out_name)

    if not os.path.exists(in_path):
        print(f"[{rel_path}] file not found, skipping")
        return

    kept_rows = []

    with open(in_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader, None)
        if header is None:
            print(f"[{rel_path}] empty file, skipping")
            return

        for row in reader:
            if not row:
                continue
            if keep_fn(row, header):
                kept_rows.append(row)

    ensure_out_dir()
    with open(out_path, "w", encoding="utf-8", newline="") as f_out:
        writer = csv.writer(f_out, delimiter="|", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(kept_rows)

    print(f"[{rel_path} -> {out_name}] kept rows: {len(kept_rows)}")


# ------------------ 1. Choose Post seeds ------------------ #

def read_seed_posts():
    """
    Pick seed posts from dynamic/post_0_0.csv by fraction.
    seed_count = floor(total_rows * POST_FRACTION), at least 1.
    """
    global post_ids
    path = os.path.join(ROOT_IN, "dynamic", "post_0_0.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")

    # First pass: count total posts.
    total_rows = 0
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader, None)
        if header is None:
            raise RuntimeError("post_0_0.csv is empty")
        for _ in reader:
            total_rows += 1

    if total_rows == 0:
        raise RuntimeError("post_0_0.csv has no data rows")

    # Compute seed fraction from sf0.1 -> sf0.003.
    target_seeds = int(total_rows * POST_FRACTION)
    if target_seeds < 1:
        target_seeds = 1

    print(
        f"[dynamic/post_0_0.csv] total posts: {total_rows}, "
        f"target seed count (by fraction): {target_seeds}"
    )

    # Second pass: take the first target_seeds post.id as seeds.
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        header = next(reader, None)
        try:
            id_idx = header.index("id")
        except ValueError:
            raise RuntimeError("post_0_0.csv does not contain column 'id'")

        for row in reader:
            if not row:
                continue
            post_ids.add(row[id_idx])
            if len(post_ids) >= target_seeds:
                break

    print(f"[dynamic/post_0_0.csv] selected seed Post vertices: {len(post_ids)}")


# ------------------ 2. Process edge tables ------------------ #
# Design rule: avoid uncontrolled expansion.
# - allowed: expand from seed Post to Person / Tag / Place / Forum / ...
# - allowed: keep edges among already-selected Person/Comment/Post/Forum/Tag/...
# - disallowed: use newly discovered Person/Forum/Comment to pull in more new Post/Person
# Each process_xxx function is called once by main(), i.e., "visit this table once".


def process_post_hasCreator_person():
    def keep(row, header):
        # Post.id|Person.id
        mid = row[0]
        pid = row[1]
        if mid in post_ids:
            person_ids.add(pid)  # Introduce Person only via seed Post
            return True
        return False

    filter_table("dynamic/post_hasCreator_person_0_0.csv", keep)


def process_post_isLocatedIn_place():
    def keep(row, header):
        # Post.id|Place.id
        mid = row[0]
        place_id = row[1]
        if mid in post_ids:
            place_ids.add(place_id)
            return True
        return False

    filter_table("dynamic/post_isLocatedIn_place_0_0.csv", keep)


def process_post_hasTag_tag():
    def keep(row, header):
        # Post.id|Tag.id
        mid = row[0]
        tid = row[1]
        if mid in post_ids:
            tag_ids.add(tid)
            return True
        return False

    filter_table("dynamic/post_hasTag_tag_0_0.csv", keep)


def process_person_knows():
    def keep(row, header):
        # Person.id|Person.id|creationDate
        src = row[0]
        dst = row[1]
        # Keep only friend edges where both endpoints are already in person_ids (do not introduce new Person).
        return (src in person_ids) and (dst in person_ids)

    filter_table("dynamic/person_knows_person_0_0.csv", keep)


def process_person_isLocatedIn():
    def keep(row, header):
        # Person.id|Place.id
        pid = row[0]
        place_id = row[1]
        if pid in person_ids:
            place_ids.add(place_id)
            return True
        return False

    filter_table("dynamic/person_isLocatedIn_place_0_0.csv", keep)


def process_person_hasInterest():
    def keep(row, header):
        # Person.id|Tag.id
        pid = row[0]
        tid = row[1]
        if pid in person_ids:
            tag_ids.add(tid)
            return True
        return False

    filter_table("dynamic/person_hasInterest_tag_0_0.csv", keep)


def process_person_studyAt():
    def keep(row, header):
        # Person.id|Organisation.id|classYear
        pid = row[0]
        oid = row[1]
        if pid in person_ids:
            org_ids.add(oid)
            return True
        return False

    filter_table("dynamic/person_studyAt_organisation_0_0.csv", keep)


def process_person_workAt():
    def keep(row, header):
        # Person.id|Organisation.id|workFrom
        pid = row[0]
        oid = row[1]
        if pid in person_ids:
            org_ids.add(oid)
            return True
        return False

    filter_table("dynamic/person_workAt_organisation_0_0.csv", keep)


def process_person_likes_post():
    def keep(row, header):
        # Person.id|Post.id|creationDate
        pid = row[0]
        mid = row[1]
        # Keep only rows where Person is already selected and the liked Post is already selected; do not introduce new Post.
        if pid in person_ids and mid in post_ids:
            return True
        return False

    filter_table("dynamic/person_likes_post_0_0.csv", keep)


def process_person_likes_message():
    def keep(row, header):
        # Person.id|Post.id|creationDate
        pid = row[0]
        mid = row[1]
        if pid in person_ids and mid in post_ids:
            return True
        return False

    filter_table("dynamic/person_likes_message_0_0.csv", keep)


def process_person_likes_comment():
    def keep(row, header):
        # Person.id|Comment.id|creationDate
        pid = row[0]
        cid = row[1]
        if pid in person_ids:
            comment_ids.add(cid)   # Allow introducing some Comment via likes
            return True
        return False

    filter_table("dynamic/person_likes_comment_0_0.csv", keep)


def process_forum_hasMember():
    def keep(row, header):
        # Forum.id|Person.id|joinDate
        fid = row[0]
        pid = row[1]
        # Introduce Forum only from existing person_ids; do not expand Person.
        if pid in person_ids:
            forum_ids.add(fid)
            return True
        return False

    filter_table("dynamic/forum_hasMember_person_0_0.csv", keep)


def process_forum_hasModerator():
    def keep(row, header):
        # Forum.id|Person.id
        fid = row[0]
        pid = row[1]
        if pid in person_ids:
            forum_ids.add(fid)
            return True
        return False

    filter_table("dynamic/forum_hasModerator_person_0_0.csv", keep)


def process_forum_containerOf_post():
    def keep(row, header):
        # Forum.id|Post.id
        fid = row[0]
        mid = row[1]
        # Keep edges only between selected Forum and selected Post; do not introduce more Post.
        return (fid in forum_ids) and (mid in post_ids)

    filter_table("dynamic/forum_containerOf_post_0_0.csv", keep)


def process_forum_hasTag_tag():
    def keep(row, header):
        # Forum.id|Tag.id
        fid = row[0]
        tid = row[1]
        if fid in forum_ids:
            tag_ids.add(tid)
            return True
        return False

    filter_table("dynamic/forum_hasTag_tag_0_0.csv", keep)


def process_comment_hasCreator_person():
    def keep(row, header):
        # Comment.id|Person.id
        cid = row[0]
        pid = row[1]
        # Keep edges only between selected Comment and selected Person; do not introduce new Person via Comment.
        return (cid in comment_ids) and (pid in person_ids)

    filter_table("dynamic/comment_hasCreator_person_0_0.csv", keep)


def process_comment_isLocatedIn_place():
    def keep(row, header):
        # Comment.id|Place.id
        cid = row[0]
        place_id = row[1]
        if cid in comment_ids:
            place_ids.add(place_id)
            return True
        return False

    filter_table("dynamic/comment_isLocatedIn_place_0_0.csv", keep)


def process_comment_hasTag_tag():
    def keep(row, header):
        # Comment.id|Tag.id
        cid = row[0]
        tid = row[1]
        if cid in comment_ids:
            tag_ids.add(tid)
            return True
        return False

    filter_table("dynamic/comment_hasTag_tag_0_0.csv", keep)


def process_comment_replyOf_post():
    def keep(row, header):
        # Comment.id|Post.id
        cid = row[0]
        mid = row[1]
        # Keep edges only between selected Comment and selected Post.
        return (cid in comment_ids) and (mid in post_ids)

    filter_table("dynamic/comment_replyOf_post_0_0.csv", keep)


def process_comment_replyOf_comment():
    def keep(row, header):
        # Comment.id|Comment.id
        src = row[0]
        dst = row[1]
        # Keep edges only within selected Comment set.
        return (src in comment_ids) and (dst in comment_ids)

    filter_table("dynamic/comment_replyOf_comment_0_0.csv", keep)


def process_comment_replyOf_message():
    def keep(row, header):
        # Comment.id|Comment.id or Comment.id|Post.id (depends on the concrete schema)
        cid = row[0]
        mid = row[1]
        return (cid in comment_ids) and (mid in post_ids)

    filter_table("dynamic/comment_replyOf_message_0_0.csv", keep)


def process_message_hasCreator_person():
    def keep(row, header):
        # Post.id|Person.id (treat Message as a Post view)
        mid = row[0]
        pid = row[1]
        # Keep mappings only for selected Post and selected Person; do not introduce new Post/Person.
        return (mid in post_ids) and (pid in person_ids)

    filter_table("dynamic/message_hasCreator_person_0_0.csv", keep)


def process_message_isLocatedIn_place():
    def keep(row, header):
        # Post.id|Place.id
        mid = row[0]
        place_id = row[1]
        if mid in post_ids:
            place_ids.add(place_id)
            return True
        return False

    filter_table("dynamic/message_isLocatedIn_place_0_0.csv", keep)


def process_message_hasTag_tag():
    def keep(row, header):
        # Post.id|Tag.id
        mid = row[0]
        tid = row[1]
        if mid in post_ids:
            tag_ids.add(tid)
            return True
        return False

    filter_table("dynamic/message_hasTag_tag_0_0.csv", keep)


def process_organisation_isLocatedIn_place():
    def keep(row, header):
        # Organisation.id|Place.id
        oid = row[0]
        place_id = row[1]
        if oid in org_ids:
            place_ids.add(place_id)
            return True
        return False

    filter_table("static/organisation_isLocatedIn_place_0_0.csv", keep)


def process_place_isPartOf_place():
    def keep(row, header):
        # Place.id|Place.id
        src = row[0]
        dst = row[1]
        if src in place_ids:
            place_ids.add(dst)
            return True
        return False

    filter_table("static/place_isPartOf_place_0_0.csv", keep)


def process_tag_hasType_tagclass():
    def keep(row, header):
        # Tag.id|TagClass.id
        tid = row[0]
        tcid = row[1]
        if tid in tag_ids:
            tagclass_ids.add(tcid)
            return True
        return False

    filter_table("static/tag_hasType_tagclass_0_0.csv", keep)


def process_tagclass_isSubclassOf_tagclass():
    def keep(row, header):
        # TagClass.id|TagClass.id
        src = row[0]
        dst = row[1]
        if src in tagclass_ids:
            tagclass_ids.add(dst)
            return True
        return False

    filter_table("static/tagclass_isSubclassOf_tagclass_0_0.csv", keep)


# ------------------ 3. Write entity tables (filtered by ID sets) ------------------ #

def write_post_table():
    def keep(row, header):
        mid = row[0]
        return mid in post_ids

    filter_table("dynamic/post_0_0.csv", keep)


def write_message_table():
    def keep(row, header):
        mid = row[0]
        return mid in post_ids

    filter_table("dynamic/message_0_0.csv", keep)


def write_person_table():
    def keep(row, header):
        pid = row[0]
        return pid in person_ids

    filter_table("dynamic/person_0_0.csv", keep)


def write_comment_table():
    def keep(row, header):
        cid = row[0]
        return cid in comment_ids

    filter_table("dynamic/comment_0_0.csv", keep)


def write_forum_table():
    def keep(row, header):
        fid = row[0]
        return fid in forum_ids

    filter_table("dynamic/forum_0_0.csv", keep)


def write_organisation_table():
    def keep(row, header):
        oid = row[0]
        return oid in org_ids

    filter_table("static/organisation_0_0.csv", keep)


def write_place_table():
    def keep(row, header):
        place_id = row[0]
        return place_id in place_ids

    filter_table("static/place_0_0.csv", keep)


def write_tag_table():
    def keep(row, header):
        tid = row[0]
        return tid in tag_ids

    filter_table("static/tag_0_0.csv", keep)


def write_tagclass_table():
    def keep(row, header):
        tcid = row[0]
        return tcid in tagclass_ids

    filter_table("static/tagclass_0_0.csv", keep)


# ------------------ main ------------------ #

def main():
    ensure_out_dir()

    # 1. Choose Post seeds
    read_seed_posts()

    # 2. Single-pass expansion (each table visited once)
    # 2.1 Expand from Post
    process_post_hasCreator_person()
    process_post_isLocatedIn_place()
    process_post_hasTag_tag()

    # 2.2 Relations of selected Person
    process_person_knows()
    process_person_isLocatedIn()
    process_person_hasInterest()
    process_person_studyAt()
    process_person_workAt()
    process_person_likes_post()
    process_person_likes_message()
    process_person_likes_comment()

    # 2.3 Forum-related
    process_forum_hasMember()
    process_forum_hasModerator()
    process_forum_containerOf_post()
    process_forum_hasTag_tag()

    # 2.4 Comment-related
    process_comment_hasCreator_person()
    process_comment_isLocatedIn_place()
    process_comment_hasTag_tag()
    process_comment_replyOf_post()
    process_comment_replyOf_comment()
    process_comment_replyOf_message()

    # 2.5 Message view (only fill Tag / Place / Person connections)
    process_message_hasCreator_person()
    process_message_isLocatedIn_place()
    process_message_hasTag_tag()

    # 2.6 Higher-order relations: Organisation / Place / TagClass
    process_organisation_isLocatedIn_place()
    process_place_isPartOf_place()
    process_tag_hasType_tagclass()
    process_tagclass_isSubclassOf_tagclass()

    # 3. Write entity tables (filtered by ID sets)
    write_post_table()
    write_message_table()
    write_person_table()
    write_comment_table()
    write_forum_table()
    write_organisation_table()
    write_place_table()
    write_tag_table()
    write_tagclass_table()

    print("Induced subgraph generation finished. Output dir:", ROOT_OUT)


if __name__ == "__main__":
    main()
