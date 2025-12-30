#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Generate imdb_graph-only SQL/PGQ plans for JOB q1..q33.

Key constraints (per user request):
- Queries MUST NOT reference imdb_raw tables.
- To intentionally create a worse plan in DuckDB/duckpgq:
  - Put ONLY the chosen "bad" edge(s) into MATCH.
  - Put selective predicates and other edges outside MATCH.
    - Materialize GRAPH_TABLE into a TEMP TABLE to prevent join reordering across MATCH.
        (Also avoids a DuckDB/duckpgq segfault when directly joining GRAPH_TABLE results.)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# Repository root (the directory containing "ispg/")
REPO_ROOT = Path(__file__).resolve()
while REPO_ROOT.name != "ispg" and REPO_ROOT.parent != REPO_ROOT:
    REPO_ROOT = REPO_ROOT.parent
REPO_ROOT = REPO_ROOT.parent if REPO_ROOT.name == "ispg" else Path(__file__).resolve().parents[3]

DB_PATH = REPO_ROOT / "imdb_pgq.duckdb"
OUT_DIR = REPO_ROOT / "ispg/imdb/duckdb_job/sql_pgq_plans"
JOB_PLAN_DIR = REPO_ROOT / "ispg/imdb/job/query_plan"
FILTERS_DIR = REPO_ROOT / "ispg/imdb/job/query_filters"


EDGE_TABLE_TO_LABEL: Dict[str, str] = {
    "title_movieCompanies_companyName": "movieCompanies",
    "title_keywordEdge_keyword": "keywordEdge",
    "title_infoEdge_infoVertex": "infoEdge",
    "title_infoEdge_infoIdxVertex": "infoIdxEdge",
    "title_linkTypeEdge_title": "linkTypeEdge",
    "title_episodeOfEdge_title": "episodeOfEdge",
    "title_akaTitleEdge_akaTitle": "akaTitleEdge",
    "person_akaNameEdge_akaName": "akaNameEdge",
    "castInfoVertex_castInfoEdge_person": "castInfoPersonEdge",
    "castInfoVertex_castInfoEdge_title": "castInfoTitleEdge",
    "castInfoVertex_castInfoEdge_character": "castInfoCharacterEdge",
    "complCastInfoVertex_complCastInfoEdge_title": "complCastTitleEdge",
    "person_personInfoEdge_personInfoVertex": "personInfoEdge",
}


@dataclass(frozen=True)
class PgqPlan:
    query_name: str
    sql: str
    chosen_bad_relation: str
    optimal_first_relation: Optional[str]


def _find_duckdb_cli() -> str:
    cli = shutil.which("duckdb")
    if cli:
        return cli
    fallback = Path.home() / ".duckdb/cli/latest/duckdb"
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError("duckdb CLI not found in PATH and ~/.duckdb/cli/latest/duckdb missing")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_job_query_plan(q: int) -> Tuple[Optional[str], Dict[str, float], List[str]]:
    """Parse ispg/imdb/job/query_plan/qN.

    Returns:
      - optimal_first_relation: first EXPAND relation in the Greedy plan (if found)
      - f_values: relation -> F value from "Single-edge subset F values"
      - expand_relations_in_order: all EXPAND relations in Greedy plan order
    """
    path = JOB_PLAN_DIR / f"q{q}"
    text = path.read_text(encoding="utf-8", errors="ignore")

    expand_relations: List[str] = []
    for m in re.finditer(r"\bStep\s+\d+:\s+op=EXPAND.*?detail=([A-Za-z0-9_]+)", text):
        expand_relations.append(m.group(1))

    f_values: Dict[str, float] = {}
    for m in re.finditer(r"relation=([A-Za-z0-9_]+),\s+F=([0-9.]+)", text):
        rel = m.group(1)
        try:
            f_values[rel] = float(m.group(2))
        except ValueError:
            continue

    optimal_first = expand_relations[0] if expand_relations else None
    return optimal_first, f_values, expand_relations


def choose_bad_relation(optimal_first: Optional[str], f_values: Dict[str, float], expand_order: List[str]) -> str:
    """Pick a relation to put into MATCH so that it differs from the optimal plan when possible."""
    candidates = list(f_values.items())
    if not candidates:
        # Fallback: use the last expand relation if present
        if expand_order:
            return expand_order[-1]
        raise RuntimeError("No edge candidates found to choose a bad relation")

    candidates.sort(key=lambda kv: kv[1], reverse=True)  # largest F = weakest

    if optimal_first is None:
        return candidates[0][0]

    for rel, _f in candidates:
        if rel != optimal_first:
            return rel
    return candidates[0][0]


def _detect_delim(csv_path: Path) -> str:
    with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
        line = f.readline()
    if "|" in line and line.count("|") >= line.count(","):
        return "|"
    return ","


def _load_dim_map(table: str, key_col: str, val_col: str) -> Dict[str, int]:
    """Load a very small raw dimension table (kind_type / role_type) into a map.

    This does NOT violate the constraint that the generated queries cannot use raw data,
    because the map is resolved at generation time and compiled into constants.
    """
    csv_path = REPO_ROOT / "datasets/imdb/imdb_raw" / f"{table}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing raw dim CSV: {csv_path}")
    delim = _detect_delim(csv_path)

        # Use DuckDB read_csv_auto for robustness (explicit names to avoid column0/column1).
    duckdb_cli = _find_duckdb_cli()
    script = f"""
PRAGMA threads=1;
.mode json
SELECT CAST({key_col} AS INTEGER) AS k, {val_col} AS v
FROM read_csv_auto(
    '{csv_path.as_posix()}',
    delim='{delim}',
    header=FALSE,
    ignore_errors=TRUE,
    names=['{key_col}', '{val_col}']
);
"""
    proc = subprocess.run(
        [duckdb_cli, ":memory:"],
        input=script.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))

    rows = json.loads(proc.stdout.decode("utf-8"))
    mapping: Dict[str, int] = {}
    for row in rows:
        try:
            mapping[str(row["v"])]= int(row["k"])
        except Exception:
            continue
    return mapping


KIND_ID: Optional[Dict[str, int]] = None
ROLE_ID: Optional[Dict[str, int]] = None


def _ensure_dim_maps() -> Tuple[Dict[str, int], Dict[str, int]]:
    global KIND_ID, ROLE_ID
    if KIND_ID is None:
        KIND_ID = _load_dim_map("kind_type", "id", "kind")
    if ROLE_ID is None:
        ROLE_ID = _load_dim_map("role_type", "id", "role")
    return KIND_ID, ROLE_ID


def _rewrite_raw_filter_to_graph(expr: str, alias_table: Dict[str, str]) -> str:
    """Rewrite a raw SQL predicate (from qN_filters.json) to imdb_graph predicate.

    This is rule-based for the JOB templates.
    """
    kind_id, role_id = _ensure_dim_maps()

    s = expr.strip()

    # info_type alias: it.info = 'xxx' gets rewritten later based on which info vertex it joins.
    # company_type alias: ct.kind = 'production companies' -> mc.company_type_kind = 'production companies'
    # We'll handle those at the query-builder stage where we know the neighbor aliases.

    # role_type: rt.role = 'actor' -> ci.role_id = <id>
    m = re.fullmatch(r"(?i)\s*(\w+)\.role\s*=\s*'([^']+)'\s*", s)
    if m:
        alias = m.group(1)
        role = m.group(2)
        rid = role_id.get(role)
        if rid is None:
            raise KeyError(f"Unknown role_type.role value: {role}")
        # cast_info alias is typically ci
        # If query uses alias 'ci' for cast_info, we rewrite to ci.role_id.
        return f"ci.role_id = {rid}"

    # kind_type: kt.kind IN (...) or = 'movie' -> t.kind_id IN (...)
    m = re.fullmatch(r"(?is)\s*(\w+)\.kind\s*=\s*'([^']+)'\s*", s)
    if m:
        kind = m.group(2)
        kid = kind_id.get(kind)
        if kid is None:
            raise KeyError(f"Unknown kind_type.kind value: {kind}")
        return f"t.kind_id = {kid}"

    m = re.fullmatch(r"(?is)\s*(\w+)\.kind\s+in\s*\((.+)\)\s*", s)
    if m:
        items = [x.strip().strip("'") for x in m.group(2).split(",")]
        kids = []
        for k in items:
            if not k:
                continue
            kid = kind_id.get(k)
            if kid is None:
                raise KeyError(f"Unknown kind_type.kind value: {k}")
            kids.append(str(kid))
        return f"t.kind_id IN ({', '.join(kids)})"

    # Default: keep as-is; later we will replace raw table aliases with graph aliases.
    return s


def build_graph_query_from_filters(q: int, bad_relation: str) -> PgqPlan:
    """Compile qN_filters.json into a graph-only SQL/PGQ query with a single bad relation in MATCH."""
    optimal_first, _fvals, expand_order = parse_job_query_plan(q)

    filters_json = _read_json(FILTERS_DIR / f"q{q}_filters.json")
    aliases: Dict[str, Any] = filters_json.get("aliases", {})
    edges: List[Dict[str, Any]] = filters_json.get("edges", [])

    alias_table: Dict[str, str] = {a: (info.get("table") or "").lower() for a, info in aliases.items()}

    # Identify key raw aliases
    title_aliases = [a for a, t in alias_table.items() if t == "title"]
    if not title_aliases:
        raise RuntimeError(f"q{q}: no title alias found")
    # Prefer t / t1
    t_alias = "t" if "t" in title_aliases else title_aliases[0]

    # Heuristic: assign canonical graph aliases for important tables
    company_name_aliases = [a for a, t in alias_table.items() if t == "company_name"]
    keyword_aliases = [a for a, t in alias_table.items() if t == "keyword"]
    mi_idx_aliases = [a for a, t in alias_table.items() if t == "movie_info_idx"]
    mi_aliases = [a for a, t in alias_table.items() if t == "movie_info"]
    cast_info_aliases = [a for a, t in alias_table.items() if t == "cast_info"]
    name_aliases = [a for a, t in alias_table.items() if t == "name"]
    aka_name_aliases = [a for a, t in alias_table.items() if t == "aka_name"]
    aka_title_aliases = [a for a, t in alias_table.items() if t == "aka_title"]
    char_name_aliases = [a for a, t in alias_table.items() if t == "char_name"]
    complete_cast_aliases = [a for a, t in alias_table.items() if t == "complete_cast"]
    person_info_aliases = [a for a, t in alias_table.items() if t == "person_info"]
    movie_link_aliases = [a for a, t in alias_table.items() if t == "movie_link"]
    
    cn_alias = company_name_aliases[0] if company_name_aliases else "cn"
    k_alias = keyword_aliases[0] if keyword_aliases else "k"
    mi_idx_alias = mi_idx_aliases[0] if mi_idx_aliases else "mi_idx"
    mi_alias = mi_aliases[0] if mi_aliases else "mi"
    ci_alias = cast_info_aliases[0] if cast_info_aliases else "ci"
    n_alias = name_aliases[0] if name_aliases else "n"
    an_alias = aka_name_aliases[0] if aka_name_aliases else "an"
    at_alias = aka_title_aliases[0] if aka_title_aliases else "at"
    chn_alias = char_name_aliases[0] if char_name_aliases else "chn"
    cc_alias = complete_cast_aliases[0] if complete_cast_aliases else "cc"
    pi_alias = person_info_aliases[0] if person_info_aliases else "pi"
    ml_alias = movie_link_aliases[0] if movie_link_aliases else "ml"

    # Build MATCH pattern for bad_relation
    if bad_relation not in EDGE_TABLE_TO_LABEL:
        raise KeyError(f"Unsupported bad_relation: {bad_relation}")
    bad_label = EDGE_TABLE_TO_LABEL[bad_relation]

    # Determine endpoints + edge alias for the chosen relation.
    # Use conventional endpoint tables.
    match_lines: List[str] = []
    col_lines: List[str] = []
    bound_vid_cols: Dict[str, str] = {}  # alias -> column name in base CTE
    base_edge_alias: str = "e"

    def add_vid(alias: str, label: str) -> None:
        if alias in bound_vid_cols:
            return
        col = f"{alias}_vid"
        bound_vid_cols[alias] = col
        col_lines.append(f"    {alias}.vid AS {col}")

    if bad_relation == "title_movieCompanies_companyName":
        base_edge_alias = "mc"
        match_lines.append(f"    ({t_alias}:title)-[{base_edge_alias}:{bad_label}]->({cn_alias}:companyName)")
        add_vid(t_alias, "title")
        add_vid(cn_alias, "companyName")
        col_lines.append(f"    {base_edge_alias}.company_type_kind AS {base_edge_alias}_company_type_kind")
        col_lines.append(f"    {base_edge_alias}.note AS {base_edge_alias}_note")
    elif bad_relation == "title_keywordEdge_keyword":
        base_edge_alias = "ke"
        match_lines.append(f"    ({t_alias}:title)-[{base_edge_alias}:{bad_label}]->({k_alias}:keyword)")
        add_vid(t_alias, "title")
        add_vid(k_alias, "keyword")
        col_lines.append(f"    {k_alias}.keyword AS {k_alias}_keyword")
    elif bad_relation == "title_infoEdge_infoIdxVertex":
        base_edge_alias = "ie"
        match_lines.append(f"    ({t_alias}:title)-[{base_edge_alias}:{bad_label}]->({mi_idx_alias}:infoIdxVertex)")
        add_vid(t_alias, "title")
        add_vid(mi_idx_alias, "infoIdxVertex")
        col_lines.append(f"    {mi_idx_alias}.info_type_info AS {mi_idx_alias}_info_type_info")
        col_lines.append(f"    {mi_idx_alias}.info_value AS {mi_idx_alias}_info_value")
        col_lines.append(f"    {mi_idx_alias}.note AS {mi_idx_alias}_note")
    elif bad_relation == "title_infoEdge_infoVertex":
        base_edge_alias = "ie"
        match_lines.append(f"    ({t_alias}:title)-[{base_edge_alias}:{bad_label}]->({mi_alias}:infoVertex)")
        add_vid(t_alias, "title")
        add_vid(mi_alias, "infoVertex")
        col_lines.append(f"    {mi_alias}.info_type_info AS {mi_alias}_info_type_info")
        col_lines.append(f"    {mi_alias}.info_value AS {mi_alias}_info_value")
        col_lines.append(f"    {mi_alias}.note AS {mi_alias}_note")
    elif bad_relation == "title_linkTypeEdge_title":
        # Require 2 title aliases; if only one exists, synthesize t2.
        t2_alias = "t2" if "t2" in title_aliases else ("t1" if "t1" in title_aliases and t_alias != "t1" else "t2")
        base_edge_alias = "ml"
        match_lines.append(f"    ({t_alias}:title)-[{base_edge_alias}:{bad_label}]->({t2_alias}:title)")
        add_vid(t_alias, "title")
        add_vid(t2_alias, "title")
        col_lines.append(f"    {base_edge_alias}.link AS {base_edge_alias}_link")
    elif bad_relation == "castInfoVertex_castInfoEdge_title":
        base_edge_alias = "cit"
        match_lines.append(f"    ({ci_alias}:castInfoVertex)-[{base_edge_alias}:{bad_label}]->({t_alias}:title)")
        add_vid(ci_alias, "castInfoVertex")
        add_vid(t_alias, "title")
        col_lines.append(f"    {ci_alias}.role_id AS {ci_alias}_role_id")
        col_lines.append(f"    {ci_alias}.note AS {ci_alias}_note")
    elif bad_relation == "castInfoVertex_castInfoEdge_character":
        base_edge_alias = "cic"
        match_lines.append(f"    ({ci_alias}:castInfoVertex)-[{base_edge_alias}:{bad_label}]->({chn_alias}:character)")
        add_vid(ci_alias, "castInfoVertex")
        add_vid(chn_alias, "character")
        col_lines.append(f"    {ci_alias}.role_id AS {ci_alias}_role_id")
        col_lines.append(f"    {ci_alias}.note AS {ci_alias}_note")
    elif bad_relation == "castInfoVertex_castInfoEdge_person":
        base_edge_alias = "cip"
        match_lines.append(f"    ({ci_alias}:castInfoVertex)-[{base_edge_alias}:{bad_label}]->({n_alias}:person)")
        add_vid(ci_alias, "castInfoVertex")
        add_vid(n_alias, "person")
        col_lines.append(f"    {n_alias}.name AS {n_alias}_name")
        col_lines.append(f"    {n_alias}.gender AS {n_alias}_gender")
        col_lines.append(f"    {ci_alias}.role_id AS {ci_alias}_role_id")
        col_lines.append(f"    {ci_alias}.note AS {ci_alias}_note")
    elif bad_relation == "person_akaNameEdge_akaName":
        base_edge_alias = "pa"
        match_lines.append(f"    ({n_alias}:person)-[{base_edge_alias}:{bad_label}]->({an_alias}:akaName)")
        add_vid(n_alias, "person")
        add_vid(an_alias, "akaName")
        col_lines.append(f"    {an_alias}.name AS {an_alias}_name")
    elif bad_relation == "title_akaTitleEdge_akaTitle":
        base_edge_alias = "ta"
        match_lines.append(f"    ({t_alias}:title)-[{base_edge_alias}:{bad_label}]->({at_alias}:akaTitle)")
        add_vid(t_alias, "title")
        add_vid(at_alias, "akaTitle")
        col_lines.append(f"    {at_alias}.title AS {at_alias}_title")
    elif bad_relation == "complCastInfoVertex_complCastInfoEdge_title":
        base_edge_alias = "cct"
        match_lines.append(f"    ({cc_alias}:complCastInfoVertex)-[{base_edge_alias}:{bad_label}]->({t_alias}:title)")
        add_vid(cc_alias, "complCastInfoVertex")
        add_vid(t_alias, "title")
        col_lines.append(f"    {cc_alias}.subject_kind AS {cc_alias}_subject_kind")
        col_lines.append(f"    {cc_alias}.status_kind AS {cc_alias}_status_kind")
    elif bad_relation == "person_personInfoEdge_personInfoVertex":
        base_edge_alias = "ppi"
        match_lines.append(f"    ({n_alias}:person)-[{base_edge_alias}:{bad_label}]->({pi_alias}:personInfoVertex)")
        add_vid(n_alias, "person")
        add_vid(pi_alias, "personInfoVertex")
        col_lines.append(f"    {pi_alias}.info_type_info AS {pi_alias}_info_type_info")
        col_lines.append(f"    {pi_alias}.info_value AS {pi_alias}_info_value")
        col_lines.append(f"    {pi_alias}.note AS {pi_alias}_note")
    else:
        raise KeyError(f"Unhandled bad relation mapping: {bad_relation}")

    match_sql = ",\n".join(match_lines)
    cols_sql = ",\n".join(col_lines)

    base_from = f"""(
  SELECT *
  FROM GRAPH_TABLE (
    G
    MATCH
{match_sql}
    COLUMNS (
{cols_sql}
    )
  )
) AS base"""

    # Outer FROM + joins: we cover remaining relationships using relational joins on imdb_graph tables.
    from_lines: List[str] = [f"FROM {base_from}"]
    where_terms: List[str] = []

    movie_companies_in_match = bad_relation == "title_movieCompanies_companyName"
    title_vid = (
        f"base.{bound_vid_cols[t_alias]}" if t_alias in bound_vid_cols else f"{t_alias}.vid"
    )

    # Always join title if we need properties/filters on it.
    if t_alias in bound_vid_cols:
        from_lines.append(f"JOIN title {t_alias} ON {t_alias}.vid = base.{bound_vid_cols[t_alias]}")

    if company_name_aliases and cn_alias in bound_vid_cols:
        from_lines.append(f"JOIN companyName {cn_alias} ON {cn_alias}.vid = base.{bound_vid_cols[cn_alias]}")

    if keyword_aliases and k_alias in bound_vid_cols:
        from_lines.append(f"JOIN keyword {k_alias} ON {k_alias}.vid = base.{bound_vid_cols[k_alias]}")

    if cast_info_aliases and ci_alias in bound_vid_cols:
        from_lines.append(f"JOIN castInfoVertex {ci_alias} ON {ci_alias}.vid = base.{bound_vid_cols[ci_alias]}")

    if name_aliases and n_alias in bound_vid_cols:
        from_lines.append(f"JOIN person {n_alias} ON {n_alias}.vid = base.{bound_vid_cols[n_alias]}")

    if aka_name_aliases and an_alias in bound_vid_cols:
        from_lines.append(f"JOIN akaName {an_alias} ON {an_alias}.vid = base.{bound_vid_cols[an_alias]}")

    if aka_title_aliases and at_alias in bound_vid_cols:
        from_lines.append(f"JOIN akaTitle {at_alias} ON {at_alias}.vid = base.{bound_vid_cols[at_alias]}")

    if char_name_aliases and chn_alias in bound_vid_cols:
        from_lines.append(f"JOIN character {chn_alias} ON {chn_alias}.vid = base.{bound_vid_cols[chn_alias]}")

    if complete_cast_aliases and cc_alias in bound_vid_cols:
        from_lines.append(f"JOIN complCastInfoVertex {cc_alias} ON {cc_alias}.vid = base.{bound_vid_cols[cc_alias]}")

    if person_info_aliases and pi_alias in bound_vid_cols:
        from_lines.append(f"JOIN personInfoVertex {pi_alias} ON {pi_alias}.vid = base.{bound_vid_cols[pi_alias]}")

    if mi_idx_aliases and mi_idx_alias in bound_vid_cols:
        from_lines.append(f"JOIN infoIdxVertex {mi_idx_alias} ON {mi_idx_alias}.vid = base.{bound_vid_cols[mi_idx_alias]}")

    if mi_aliases and mi_alias in bound_vid_cols:
        from_lines.append(f"JOIN infoVertex {mi_alias} ON {mi_alias}.vid = base.{bound_vid_cols[mi_alias]}")

    # Add other edges not in MATCH: we use the presence of raw tables to decide needed joins.
    # movie_companies => title_movieCompanies_companyName
    if "movie_companies" in alias_table.values() and bad_relation != "title_movieCompanies_companyName":
        from_lines.append(
            f"JOIN title_movieCompanies_companyName mc ON mc.src_vid = {title_vid}"
        )
        if company_name_aliases:
            from_lines.append(f"JOIN companyName {cn_alias} ON {cn_alias}.vid = mc.dst_vid")

    # movie_keyword => title_keywordEdge_keyword + keyword
    if "movie_keyword" in alias_table.values() and bad_relation != "title_keywordEdge_keyword":
        from_lines.append(f"JOIN title_keywordEdge_keyword ke ON ke.src_vid = {title_vid}")
        if keyword_aliases:
            from_lines.append(f"JOIN keyword {k_alias} ON {k_alias}.vid = ke.dst_vid")

    # movie_info_idx => title_infoEdge_infoIdxVertex + infoIdxVertex
    if "movie_info_idx" in alias_table.values() and bad_relation != "title_infoEdge_infoIdxVertex":
        from_lines.append(f"JOIN title_infoEdge_infoIdxVertex e_mi_idx ON e_mi_idx.src_vid = {title_vid}")
        from_lines.append(f"JOIN infoIdxVertex {mi_idx_alias} ON {mi_idx_alias}.vid = e_mi_idx.dst_vid")

    # movie_info => title_infoEdge_infoVertex + infoVertex
    if "movie_info" in alias_table.values() and bad_relation != "title_infoEdge_infoVertex":
        from_lines.append(f"JOIN title_infoEdge_infoVertex e_mi ON e_mi.src_vid = {title_vid}")
        from_lines.append(f"JOIN infoVertex {mi_alias} ON {mi_alias}.vid = e_mi.dst_vid")

    # cast_info => castInfoVertex_castInfoEdge_* edges
    if "cast_info" in alias_table.values():
        if bad_relation != "castInfoVertex_castInfoEdge_title" and "title" in alias_table.values():
            from_lines.append(f"JOIN castInfoVertex_castInfoEdge_title e_ci_t ON e_ci_t.src_vid = {ci_alias}.vid")
            from_lines.append(f"JOIN title {t_alias} ON {t_alias}.vid = e_ci_t.dst_vid")
        if "name" in alias_table.values() and bad_relation != "castInfoVertex_castInfoEdge_person":
            from_lines.append(f"JOIN castInfoVertex_castInfoEdge_person e_ci_p ON e_ci_p.src_vid = {ci_alias}.vid")
            from_lines.append(f"JOIN person {n_alias} ON {n_alias}.vid = e_ci_p.dst_vid")
        if "char_name" in alias_table.values() and bad_relation != "castInfoVertex_castInfoEdge_character":
            from_lines.append(f"JOIN castInfoVertex_castInfoEdge_character e_ci_c ON e_ci_c.src_vid = {ci_alias}.vid")
            from_lines.append(f"JOIN character {chn_alias} ON {chn_alias}.vid = e_ci_c.dst_vid")

    # aka_name
    if "aka_name" in alias_table.values() and bad_relation != "person_akaNameEdge_akaName":
        from_lines.append(f"JOIN person_akaNameEdge_akaName e_p_an ON e_p_an.src_vid = {n_alias}.vid")
        from_lines.append(f"JOIN akaName {an_alias} ON {an_alias}.vid = e_p_an.dst_vid")

    # aka_title
    if "aka_title" in alias_table.values() and bad_relation != "title_akaTitleEdge_akaTitle":
        from_lines.append(f"JOIN title_akaTitleEdge_akaTitle e_t_at ON e_t_at.src_vid = {t_alias}.vid")
        from_lines.append(f"JOIN akaTitle {at_alias} ON {at_alias}.vid = e_t_at.dst_vid")

    # complete_cast
    if "complete_cast" in alias_table.values() and bad_relation != "complCastInfoVertex_complCastInfoEdge_title":
        from_lines.append(f"JOIN complCastInfoVertex_complCastInfoEdge_title e_cc_t ON e_cc_t.src_vid = {cc_alias}.vid")
        from_lines.append(f"JOIN title {t_alias} ON {t_alias}.vid = e_cc_t.dst_vid")

    # person_info
    if "person_info" in alias_table.values() and bad_relation != "person_personInfoEdge_personInfoVertex":
        from_lines.append(f"JOIN person_personInfoEdge_personInfoVertex e_p_pi ON e_p_pi.src_vid = {n_alias}.vid")
        from_lines.append(f"JOIN personInfoVertex {pi_alias} ON {pi_alias}.vid = e_p_pi.dst_vid")

    # movie_link
    if "movie_link" in alias_table.values() and bad_relation != "title_linkTypeEdge_title":
        # Ensure we have a second title alias in FROM.
        t2_alias = "t2" if any(a == "t2" for a in title_aliases) else "t2"
        from_lines.append(f"JOIN title_linkTypeEdge_title {ml_alias} ON {ml_alias}.src_vid = {title_vid}")
        from_lines.append(f"JOIN title {t2_alias} ON {t2_alias}.vid = {ml_alias}.dst_vid")

    # Build WHERE predicates (rewrite raw filters)
    for alias, info in aliases.items():
        table = (info.get("table") or "").lower()
        for fil in (info.get("filters") or []):
            raw_expr = fil.get("expression")
            if not raw_expr:
                continue

            # movie_companies filters: mc.note / mc.* need to refer to either base columns (if in MATCH)
            # or the relational edge table alias mc (if joined outside MATCH).
            if table == "movie_companies":
                expr = raw_expr
                if movie_companies_in_match:
                    expr = re.sub(r"(?i)\bmc\.note\b", "base.mc_note", expr)
                    expr = re.sub(r"(?i)\bmc\.company_type_kind\b", "base.mc_company_type_kind", expr)
                # When movieCompanies is not in MATCH, we join edge table alias mc and can use mc.note directly.
                where_terms.append(expr)
                continue

            # company_type.kind -> mc.company_type_kind (mc refers to movieCompanies edge)
            if table == "company_type":
                # Replace <alias>.kind with mc.company_type_kind
                target = "base.mc_company_type_kind" if movie_companies_in_match else "mc.company_type_kind"
                expr = re.sub(rf"(?i)\b{re.escape(alias)}\.kind\b", target, raw_expr)
                where_terms.append(expr)
                continue

            # info_type.info -> map to corresponding info vertex (infoIdxVertex/infoVertex/personInfoVertex)
            if table == "info_type":
                # find neighbor table via edges
                neighbor = None
                for e in edges:
                    if e.get("left_alias") == alias:
                        neighbor = e.get("right_alias")
                        break
                    if e.get("right_alias") == alias:
                        neighbor = e.get("left_alias")
                        break
                if neighbor is None:
                    raise RuntimeError(f"q{q}: cannot resolve info_type alias neighbor")
                nb_table = alias_table.get(neighbor, "")
                if nb_table == "movie_info_idx":
                    target = f"{mi_idx_alias}.info_type_info"
                elif nb_table == "movie_info":
                    target = f"{mi_alias}.info_type_info"
                elif nb_table == "person_info":
                    target = f"{pi_alias}.info_type_info"
                else:
                    # default to infoVertex
                    target = f"{mi_alias}.info_type_info"
                expr = re.sub(rf"(?i)\b{re.escape(alias)}\.info\b", target, raw_expr)
                where_terms.append(expr)
                continue

            # link_type.link -> movie_link edge attribute link
            if table == "link_type":
                expr = re.sub(rf"(?i)\b{re.escape(alias)}\.link\b", f"{ml_alias}.link", raw_expr)
                where_terms.append(expr)
                continue

            # comp_cast_type.kind -> complCastInfoVertex subject_kind/status_kind
            if table == "comp_cast_type":
                # Heuristic: cct1 -> subject, cct2 -> status
                col = "subject_kind" if re.search(r"\b1\b", alias) else "status_kind"
                expr = re.sub(rf"(?i)\b{re.escape(alias)}\.kind\b", f"{cc_alias}.{col}", raw_expr)
                where_terms.append(expr)
                continue

            # kind_type / role_type are rewritten to id filters
            expr = _rewrite_raw_filter_to_graph(raw_expr, alias_table)

            # movie_info / movie_info_idx: mi.info / mi_idx.info refer to info_value in graph.
            if table == "movie_info":
                expr = re.sub(rf"(?i)\b{re.escape(alias)}\.info\b", f"{mi_alias}.info_value", expr)
            if table == "movie_info_idx":
                expr = re.sub(rf"(?i)\b{re.escape(alias)}\.info\b", f"{mi_idx_alias}.info_value", expr)

            # For common aliases, just keep expression; raw table names already match our chosen aliases.
            where_terms.append(expr)

    # Also add any residual conditions (rare in templates)
    for rc in filters_json.get("residual_conditions", []) or []:
        where_terms.append(str(rc))

    where_sql = "\n  AND ".join(where_terms) if where_terms else "TRUE"

    query_sql = "\n".join(
        [
            "SELECT COUNT(*) AS cnt",
            *from_lines,
            "WHERE",
            f"  {where_sql}",
            ";",
        ]
    )

    return PgqPlan(
        query_name=f"q{q}",
        sql=query_sql,
        chosen_bad_relation=bad_relation,
        optimal_first_relation=optimal_first,
    )


def write_plan_file(plan: PgqPlan, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(plan.sql + "\n\n", encoding="utf-8")

    duckdb_cli = _find_duckdb_cli()
    script = """
LOAD duckpgq;
PRAGMA threads=1;
PRAGMA explain_output='physical_only';
.mode line
.maxwidth 1000000

EXPLAIN
""" + plan.sql + "\n"

    proc = subprocess.run(
        [duckdb_cli, str(DB_PATH)],
        input=script.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "DuckDB EXPLAIN failed\n"
            f"query={plan.query_name}\n"
            f"bad_relation={plan.chosen_bad_relation}\n"
            f"cmd: {duckdb_cli} {DB_PATH}\n"
            f"stdout:\n{proc.stdout.decode('utf-8', errors='replace')}\n"
            f"stderr:\n{proc.stderr.decode('utf-8', errors='replace')}"
        )

    with out_path.open("ab") as f:
        f.write(proc.stdout)


def _match_edges_from_sql(sql: str) -> List[str]:
    # Extract edge labels used in MATCH: [x:edgeLabel]
    labels = re.findall(r"\[[^\]]+?:([A-Za-z0-9_]+)\]", sql)
    return labels


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--q", type=int, help="Query id (1..33)")
    parser.add_argument("--all", action="store_true", help="Generate q1..q33")
    parser.add_argument("--from", dest="q_from", type=int, help="Generate from query id (inclusive)")
    parser.add_argument("--to", dest="q_to", type=int, help="Generate to query id (inclusive)")
    args = parser.parse_args(argv)

    qs: List[int]
    if args.all:
        qs = list(range(1, 34))
    elif args.q is not None:
        qs = [args.q]
    elif args.q_from is not None or args.q_to is not None:
        q_from = args.q_from if args.q_from is not None else 1
        q_to = args.q_to if args.q_to is not None else 33
        if q_from < 1 or q_to > 33 or q_from > q_to:
            raise SystemExit("Invalid --from/--to range (must satisfy 1 <= from <= to <= 33)")
        qs = list(range(q_from, q_to + 1))
    else:
        raise SystemExit("Please pass --q N, --from/--to, or --all")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    failures: List[str] = []
    same_as_optimal: List[str] = []

    for q in qs:
        try:
            optimal_first, fvals, expand_order = parse_job_query_plan(q)
            bad_relation = choose_bad_relation(optimal_first, fvals, expand_order)
            plan = build_graph_query_from_filters(q, bad_relation)

            # Sanity check: ensure we didn't accidentally include optimal first relation in MATCH when avoidable.
            match_edge_labels = _match_edges_from_sql(plan.sql)
            if plan.optimal_first_relation:
                optimal_label = EDGE_TABLE_TO_LABEL.get(plan.optimal_first_relation)
                if optimal_label and optimal_label in match_edge_labels:
                    same_as_optimal.append(f"q{q}: MATCH contains optimal edge {optimal_label}")

            out_path = OUT_DIR / f"q{q}.txt"
            write_plan_file(plan, out_path)
            print(
                f"[OK] q{q}: bad_relation={plan.chosen_bad_relation} (optimal_first={plan.optimal_first_relation}) -> {out_path}"
            )
        except Exception as e:
            failures.append(f"q{q}: {e}")

    if same_as_optimal:
        print("\n[WARN] Some queries still include optimal edge(s) in MATCH:")
        for line in same_as_optimal:
            print("  " + line)

    if failures:
        print("\n[FAIL] Some queries failed:")
        for line in failures:
            print("  " + line)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
