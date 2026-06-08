#!/usr/bin/env python3
"""Generate fixed-hop sub-query filter and pattern JSONs for VarExpand queries.

For each VarExpand(min, max) query, creates one sub-query per hop count k in
[min, max]:  ic-{n}-{k}_filters.json  and  ic-{n}-{k}.json

The VarExpand edge is replaced by k single-hop Knows edges and k-1 intermediate
Person vertices (no filters, selectivity=1.0) are added.

Usage:
    python ispg/ldbc/gen_fixed_hop_subqueries.py
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

FILTER_DIR = Path(__file__).resolve().parent / "query_filters"
PATTERN_DIR = Path(__file__).resolve().parent / "query_pattern"

PERSON_LABEL    = "Person"
PERSON_LABEL_ID = 4
KNOWS_REL_LABEL = "Person_knows_Person"
KNOWS_REL_ID    = 16


# ── per-hop sub-queries to generate ─────────────────────────────────────────
CONFIGS: list[tuple[str, list[int]]] = [
    ("ic-1",  [1, 2, 3]),
    ("ic-3",  [1, 2]),
    ("ic-5",  [1, 2]),
    ("ic-6",  [1, 2]),
    ("ic-9",  [1, 2]),
    ("ic-10", [2]),      # exactly 2-hop; 1-hop sub-query not needed
    ("ic-11", [1, 2]),
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _alias_entry(total_rows: int) -> dict:
    """Filter-JSON alias entry for an unfiltered intermediate Person vertex."""
    return {
        "kind": "vertex",
        "domain": "match",
        "label": PERSON_LABEL,
        "label_id": PERSON_LABEL_ID,
        "relationship_type": None,
        "relationship_key": None,
        "relationship_label": None,
        "relation_id": None,
        "dataset_key": None,
        "combined": {
            "expression": "TRUE",
            "matched_rows": total_rows,
            "total_rows": total_rows,
            "selectivity": 1.0,
        },
        "filters": [],
    }


def _vertex_entry(tag_id: int, alias: str) -> dict:
    """Filter-JSON vertex list entry for an intermediate Person vertex."""
    return {
        "tag_id": tag_id,
        "alias": alias,
        "label": PERSON_LABEL,
        "label_id": PERSON_LABEL_ID,
        "domain": "match",
        "combined_selectivity": 1.0,
    }


def _filter_edge(edge_id: int, s_alias: str, d_alias: str,
                 s_tag: int, d_tag: int) -> dict:
    """Single-hop Knows edge for the filter JSON."""
    return {
        "edge_id": edge_id,
        "alias": None,
        "type": "knows",
        "source_alias": s_alias,
        "target_alias": d_alias,
        "source_tag": s_tag,
        "target_tag": d_tag,
        "relation_id": KNOWS_REL_ID,
        "relation_label": KNOWS_REL_LABEL,
        "schema_source_label": PERSON_LABEL,
        "schema_target_label": PERSON_LABEL,
        "min_hops": 1,
        "max_hops": 1,
        "is_path": False,
        "path_alias": None,
        "is_var_expand": False,
        "is_reversed": False,
        "is_identity": False,
        "origin": "match_edge",
    }


def _pattern_edge(edge_id: int, s_tag: int, d_tag: int) -> dict:
    """Single-hop Knows edge for the pattern JSON."""
    return {
        "edge_id": edge_id,
        "alias": None,
        "type": "knows",
        "relation_id": KNOWS_REL_ID,
        "relation_label": KNOWS_REL_LABEL,
        "schema_source_label": PERSON_LABEL,
        "schema_target_label": PERSON_LABEL,
        "source_tag": s_tag,
        "target_tag": d_tag,
        "min_hops": 1,
        "max_hops": 1,
        "is_var_expand": False,
        "is_reversed": False,
        "is_identity": False,
    }


def _intermediate_aliases(count: int, used: set[str]) -> list[str]:
    """Return `count` fresh alias names for the intermediate Person vertices,
    avoiding any alias already used in the parent query.

    The preferred names are ['m'] (single hop) or ['m1','m2',…]; if one of
    them already occurs in the parent query it is replaced by the next free
    'm<k>' — e.g. ic-9's message alias 'm' would otherwise collide with the
    2-hop intermediate Person vertex, silently merging two distinct vertices.
    """
    preferred = ["m"] if count == 1 else [f"m{i + 1}" for i in range(count)]
    out: list[str] = []
    for name in preferred:
        if name not in used and name not in out:
            out.append(name)
            continue
        k = 1
        while f"m{k}" in used or f"m{k}" in out or f"m{k}" in preferred:
            k += 1
        out.append(f"m{k}")
    return out


# ── main generation logic ────────────────────────────────────────────────────

def generate(query_name: str, hop: int) -> None:
    filt = json.loads((FILTER_DIR / f"{query_name}_filters.json").read_text())
    patt = json.loads((PATTERN_DIR / f"{query_name}.json").read_text())

    # Locate the VarExpand edge in the filter list
    var_idx_f = next(
        i for i, e in enumerate(filt["edges"]) if e.get("is_var_expand")
    )
    var_edge = filt["edges"][var_idx_f]

    src_alias = var_edge["source_alias"]   # "a"
    dst_alias = var_edge["target_alias"]   # "b"
    src_tag   = var_edge["source_tag"]     # 0
    dst_tag   = var_edge["target_tag"]     # 1

    # Allocate new tag_ids for k-1 intermediate vertices
    max_tag   = max(v["tag_id"] for v in filt["vertices"])
    new_tags  = list(range(max_tag + 1, max_tag + hop))   # len = hop-1

    # Allocate new edge_ids for additional hop edges (first hop reuses original id)
    orig_eid  = var_edge["edge_id"]
    max_eid   = max(e["edge_id"] for e in filt["edges"])
    extra_eids = list(range(max_eid + 1, max_eid + hop))  # len = hop-1

    # Build full alias/tag chains — intermediate aliases must not collide with
    # any alias already present in the parent query.
    existing_aliases = {v["alias"] for v in filt["vertices"]}
    int_aliases = _intermediate_aliases(len(new_tags), existing_aliases)
    chain_aliases = [src_alias] + int_aliases + [dst_alias]
    chain_tags    = [src_tag]   + new_tags    + [dst_tag]

    # ── new filter JSON ──────────────────────────────────────────────────────
    nf = copy.deepcopy(filt)
    nf["query"] = f"{query_name}-{hop}"

    person_total = filt["aliases"][src_alias]["combined"]["total_rows"]

    for alias_name, tag in zip(int_aliases, new_tags):
        nf["aliases"][alias_name] = _alias_entry(person_total)
        nf["vertices"].append(_vertex_entry(tag, alias_name))

    # Build replacement Knows edges
    knows_edges = []
    for i in range(hop):
        eid = orig_eid if i == 0 else extra_eids[i - 1]
        knows_edges.append(
            _filter_edge(eid, chain_aliases[i], chain_aliases[i + 1],
                         chain_tags[i], chain_tags[i + 1])
        )

    # Remove the VarExpand entry and prepend the new ones
    nf["edges"] = knows_edges + [
        e for j, e in enumerate(filt["edges"]) if j != var_idx_f
    ]

    # ── new pattern JSON ─────────────────────────────────────────────────────
    np_ = copy.deepcopy(patt)
    np_["query"] = f"{query_name}-{hop}"

    for alias_name, tag in zip(int_aliases, new_tags):
        np_["match"]["vertices"].append({
            "tag_id": tag,
            "alias": alias_name,
            "label": PERSON_LABEL,
            "label_id": PERSON_LABEL_ID,
        })

    # Locate VarExpand in pattern match edges
    var_idx_p = next(
        i for i, e in enumerate(patt["match"]["edges"]) if e.get("is_var_expand")
    )

    patt_knows = []
    for i in range(hop):
        eid = orig_eid if i == 0 else extra_eids[i - 1]
        patt_knows.append(_pattern_edge(eid, chain_tags[i], chain_tags[i + 1]))

    np_["match"]["edges"] = patt_knows + [
        e for j, e in enumerate(patt["match"]["edges"]) if j != var_idx_p
    ]

    if "alias_domains" in np_:
        for alias_name in int_aliases:
            np_["alias_domains"][alias_name] = "match"

    # ── write output ─────────────────────────────────────────────────────────
    sub = f"{query_name}-{hop}"
    (FILTER_DIR / f"{sub}_filters.json").write_text(
        json.dumps(nf, indent=2, ensure_ascii=False)
    )
    (PATTERN_DIR / f"{sub}.json").write_text(
        json.dumps(np_, indent=2, ensure_ascii=False)
    )

    n_mv = len(np_["match"]["vertices"])
    n_me = len(np_["match"]["edges"])
    n_sv = len(np_.get("sql", {}).get("vertices", []))
    n_se = len(np_.get("sql", {}).get("edges", []))
    print(f"  [{sub}] match: {n_mv}v {n_me}e  sql: {n_sv}v {n_se}e")


def main() -> None:
    for query_name, hops in CONFIGS:
        print(f"{query_name}:")
        for h in hops:
            generate(query_name, h)


if __name__ == "__main__":
    main()
