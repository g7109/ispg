#!/usr/bin/env python3
"""JOB query optimizer that blends GLogS estimates with per-alias predicates."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# -----------------------------------------------------
# Constants and helper structures
# -----------------------------------------------------


@dataclass
class SchemaInfo:
    entity_id_to_name: Dict[int, str]
    entity_name_to_id: Dict[str, int]
    relation_id_to_name: Dict[int, str]


@dataclass
class AliasStat:
    alias: str
    table: str
    label: str
    selectivity: float
    filters: List[str] = field(default_factory=list)
    degree: int = 0


TABLE_TO_LABEL_DIRECT: Dict[str, str] = {
    "aka_name": "akaName",
    "aka_title": "akaTitle",
    "cast_info": "castInfoVertex",
    "char_name": "character",
    "company_name": "companyName",
    "complete_cast": "complCastInfoVertex",
    "movie_info": "infoVertex",
    "movie_info_idx": "infoIdxVertex",
    "keyword": "keyword",
    "name": "person",
    "person_info": "personInfoVertex",
    "title": "title",
}


# -----------------------------------------------------
# Minimal physical mapping: SQL tables -> graph semantics
#   - These tables are not vertices in the current GLogS schema.
#   - In the materialized graph they usually correspond to an edge / edge attributes,
#     so filters should be attached to the relation.
# -----------------------------------------------------

NON_VERTEX_TABLE_TO_RELATION: Dict[str, str] = {
    # Edge attributes for title --(movieCompanies)--> companyName
    "movie_companies": "title_movieCompanies_companyName",
    "company_type": "title_movieCompanies_companyName",
    # Join table for title --(keyword)--> keyword (typically no direct filters)
    "movie_keyword": "title_keywordEdge_keyword",
    # Relation / edge attributes for title --(linkType)--> title
    "movie_link": "title_linkTypeEdge_title",
    "link_type": "title_linkTypeEdge_title",
}


# -----------------------------------------------------
# GLogS estimator
# -----------------------------------------------------


class GLogsEstimator:
    def __init__(self, repo_root: Path, catalog_rel: str, script_rel: str, quiet: bool = True) -> None:
        self.repo_root = repo_root
        self.catalog_path = repo_root / catalog_rel
        self.script_path = repo_root / script_rel
        self.quiet = quiet

        if not self.catalog_path.exists():
            raise FileNotFoundError(f"GLogS catalog not found: {self.catalog_path}")
        if not self.script_path.exists():
            raise FileNotFoundError(f"GLogS estimate.sh not found: {self.script_path}")

    def estimate_pattern(self, pattern: Dict) -> float:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(pattern, tmp)
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                [str(self.script_path), str(self.catalog_path), str(tmp_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
            )
            stdout = result.stdout.strip()
            if not stdout:
                raise RuntimeError("GLogS output is empty")

            first_line = stdout.splitlines()[0].strip()
            norm = first_line.replace(",", " ")
            parts = norm.split()
            if not parts:
                raise RuntimeError(f"Failed to parse GLogS output format: {first_line}")
            return float(parts[0])
        except subprocess.CalledProcessError as e:
            if self.quiet:
                return 1.0
            raise RuntimeError(f"GLogS estimation failed, stderr:\n{e.stderr}") from e
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


# -----------------------------------------------------
# Plan structures
# -----------------------------------------------------


@dataclass
class EdgeSpec:
    idx: int
    src_tag: int
    dst_tag: int
    description: str


@dataclass
class PlanStep:
    step_id: int
    op: str
    pattern: str
    cost: float
    detail: str
    from_var: Optional[str] = None
    to_var: Optional[str] = None


@dataclass
class Plan:
    query: str
    root_pattern: str
    root_cost: float
    steps: List[PlanStep]
    total_cost: float


def render_plan(plan: Plan, title: str) -> List[str]:
    lines: List[str] = []
    lines.append(f"=== {title} ({plan.query}) ===")
    lines.append(f"  Root pattern: {plan.root_pattern}")
    lines.append(f"  Total plan cost: {plan.total_cost:.4f}")
    for s in plan.steps:
        if s.op == "VERTEX_SCAN":
            lines.append(
                f"    Step {s.step_id}: op={s.op}, pattern={s.pattern}, cost={s.cost:.4f}, detail={s.detail}"
            )
        elif s.op in {"FILTER", "AGGREGATE"}:
            lines.append(
                f"    Step {s.step_id}: op={s.op}, pattern={s.pattern}, detail={s.detail}"
            )
        else:
            lines.append(
                f"    Step {s.step_id}: op={s.op}, pattern={s.pattern}, cost={s.cost:.4f}, "
                f"from={s.from_var}, to={s.to_var}, detail={s.detail}"
            )
    return lines


# -----------------------------------------------------
# Main optimizer
# -----------------------------------------------------


class JobQueryOptimizer:
    def __init__(
        self,
        query_name: str,
        query_json: Dict,
        pattern_json: Dict,
        schema: SchemaInfo,
        alias_stats: Dict[str, AliasStat],
        label_to_aliases: Dict[str, List[str]],
        alias_neighbors: Dict[str, Set[str]],
        sql_edges: List[Tuple[str, str]],
        estimator: GLogsEstimator,
        cost_scale: float,
    ) -> None:
        self.query_name = query_name
        self.query_json = query_json
        self.pattern_json = pattern_json
        self.schema = schema
        self.alias_stats = alias_stats
        self.label_to_aliases = label_to_aliases
        self.alias_neighbors = alias_neighbors
        self.sql_edges = [(l, r) for l, r in sql_edges if l and r]
        self.estimator = estimator
        self.cost_scale = cost_scale

        self.vertices_json = pattern_json["vertices"]
        self.edges_json = pattern_json["edges"]

        self.tag_to_label: Dict[int, str] = {}
        self.tag_to_alias: Dict[int, str] = {}
        self.vertex_selectivity: Dict[int, float] = {}
        self.vertex_filters: Dict[int, List[str]] = {}
        self.edge_selectivity: Dict[int, float] = {}
        self.edge_filters: Dict[int, List[str]] = {}

        # Physical executability: whether reverse expand (dst -> src) is allowed.
        # Whether it works depends on whether the graph storage supports reverse adjacency.
        self.allow_reverse: bool = True

        # Diagnostics: explain alias binding and non-executable direction/attachment
        self.warnings: List[str] = []
        self.alias_target: Dict[str, str] = {}

        alias_assigned: Dict[str, int] = {}
        label_to_tags: Dict[str, List[int]] = {}

        for vertex in self.vertices_json:
            tag = vertex["tag_id"]
            label_id = vertex["label_id"]
            label_name = self.schema.entity_id_to_name.get(label_id)
            if label_name is None:
                raise KeyError(f"Unknown label_id {label_id} (query={query_name})")

            label_to_tags.setdefault(label_name, []).append(tag)

            candidates = list(self.label_to_aliases.get(label_name, []))
            selected_alias: Optional[str] = None
            if candidates:
                def alias_key(a: str) -> Tuple[float, float, str]:
                    info = self.alias_stats.get(a)
                    if info:
                        return (info.degree, info.selectivity, a)
                    return (math.inf, math.inf, a)

                candidates.sort(key=alias_key)
                for alias in candidates:
                    if alias not in alias_assigned:
                        selected_alias = alias
                        break
                if selected_alias is None:
                    selected_alias = candidates[0]

            self.tag_to_label[tag] = label_name

            if selected_alias and selected_alias in self.alias_stats:
                info = self.alias_stats[selected_alias]
                self.tag_to_alias[tag] = selected_alias
                self.vertex_selectivity[tag] = info.selectivity
                self.vertex_filters[tag] = [f"{selected_alias}: {expr}" for expr in info.filters]
                alias_assigned[selected_alias] = tag
            else:
                alias_name = selected_alias or label_name
                self.tag_to_alias[tag] = alias_name
                self.vertex_selectivity[tag] = 1.0
                self.vertex_filters[tag] = []

        for a, t in alias_assigned.items():
            self.alias_target[a] = f"VERTEX(tag_id={t}, label={self.tag_to_label[t]})"

        self.edges_spec: List[EdgeSpec] = []
        # Do not treat (src_label,dst_label) as a unique key: IMDB can have multi-edges / multiple relations between the same labels.
        self.relation_name_to_edge_idxs: Dict[str, List[int]] = {}
        self.edge_triplet_to_idx: Dict[Tuple[str, str, str], int] = {}
        for idx, edge in enumerate(self.edges_json):
            label_id = edge.get("label_id")
            rel_name = self.schema.relation_id_to_name.get(label_id, f"edge_{label_id}")
            self.edges_spec.append(
                EdgeSpec(
                    idx=idx,
                    src_tag=edge["src"],
                    dst_tag=edge["dst"],
                    description=rel_name,
                )
            )
            src_label = self.tag_to_label.get(edge["src"], "")
            dst_label = self.tag_to_label.get(edge["dst"], "")
            if src_label and dst_label:
                self.edge_triplet_to_idx[(src_label, dst_label, rel_name)] = idx
            self.relation_name_to_edge_idxs.setdefault(rel_name, []).append(idx)
            self.edge_selectivity[idx] = 1.0
            self.edge_filters[idx] = []

        for alias, info in self.alias_stats.items():
            if alias in alias_assigned:
                continue

            # Explicit edge mapping: __EDGE__:relation
            if info.label.startswith("__EDGE__:"):
                rel = info.label.split(":", 1)[1]
                idxs = self.relation_name_to_edge_idxs.get(rel, [])
                if not idxs:
                    self.warnings.append(
                        f"alias {alias} table={info.table} mapped to relation={rel}, but relation not in pattern"
                    )
                    self.alias_target[alias] = f"UNPLACED(edge={rel})"
                    continue
                if len(idxs) > 1:
                    self.warnings.append(
                        f"alias {alias} table={info.table} relation={rel} matches multiple edges {idxs}; using first"
                    )
                target_edge = idxs[0]
                self.edge_selectivity[target_edge] *= info.selectivity
                if info.filters:
                    self.edge_filters[target_edge].extend(f"{alias}: {expr}" for expr in info.filters)
                self.alias_target[alias] = f"EDGE(edge_idx={target_edge}, relation={rel})"
                continue

            fallback_tags = label_to_tags.get(info.label, [])
            if fallback_tags:
                tag = fallback_tags[0]
                self.vertex_selectivity[tag] *= info.selectivity
                if info.filters:
                    self.vertex_filters[tag].extend(
                        f"{alias}: {expr}" for expr in info.filters
                    )
                self.alias_target[alias] = f"VERTEX_FALLBACK(tag_id={tag}, label={self.tag_to_label[tag]})"
                continue

            # Unattributable: avoid attaching to the wrong vertex/edge and producing misleading output
            if info.filters:
                self.warnings.append(
                    f"alias {alias} table={info.table} label={info.label} has filters but cannot be placed"
                )
            self.alias_target[alias] = "UNPLACED"

        self.num_edges = len(self.edges_spec)
        if self.num_edges == 0:
            raise ValueError(f"Query {query_name} has no edges in its pattern; cannot build a plan")
        self.full_mask = (1 << self.num_edges) - 1

        self.vertex_F_struct: Dict[int, float] = {}
        self.vertex_F_eff: Dict[int, float] = {}
        self._init_vertex_costs()

        self.subset_F: Dict[int, float] = {}
        self.subset_cost: Dict[int, float] = {}
        self._precompute_subset_costs()

    # ---- pattern construction ----

    def _pattern_for_mask(self, mask: int) -> Dict:
        used_tags: Set[int] = set()
        edges_sel: List[Dict] = []
        for i, edge in enumerate(self.edges_json):
            if mask & (1 << i):
                edges_sel.append(edge)
                used_tags.add(edge["src"])
                used_tags.add(edge["dst"])
        vertices_sel = [v for v in self.vertices_json if v["tag_id"] in used_tags]
        return {
            "vertices": vertices_sel,
            "edges": edges_sel,
        }

    def _pattern_for_vertex(self, tag_id: int) -> Dict:
        vertices_sel = [v for v in self.vertices_json if v["tag_id"] == tag_id]
        return {
            "vertices": vertices_sel,
            "edges": [],
        }

    # ---- vertex cost ----

    def _init_vertex_costs(self) -> None:
        for tag in self.tag_to_label:
            pattern = self._pattern_for_vertex(tag)
            F_struct = max(self.estimator.estimate_pattern(pattern), 1.0)
            sel = self.vertex_selectivity.get(tag, 1.0)
            F_eff = F_struct * sel
            self.vertex_F_struct[tag] = F_struct
            self.vertex_F_eff[tag] = F_eff

        self.anchor_tag = min(
            self.vertex_F_eff.items(), key=lambda kv: kv[1]
        )[0]

    # ---- subset cost ----

    def _used_tags_for_mask(self, mask: int) -> Set[int]:
        used: Set[int] = set()
        for edge in self.edges_spec:
            if mask & (1 << edge.idx):
                used.add(edge.src_tag)
                used.add(edge.dst_tag)
        return used

    def _precompute_subset_costs(self) -> None:
        for mask in range(1, 1 << self.num_edges):
            pattern = self._pattern_for_mask(mask)
            F_struct = max(self.estimator.estimate_pattern(pattern), 1.0)
            used_tags = self._used_tags_for_mask(mask)
            sel = 1.0
            for tag in used_tags:
                sel *= self.vertex_selectivity.get(tag, 1.0)
            for edge in self.edges_spec:
                if mask & (1 << edge.idx):
                    sel *= self.edge_selectivity.get(edge.idx, 1.0)
            F_eff = F_struct * sel
            self.subset_F[mask] = F_eff
            self.subset_cost[mask] = self.cost_scale * F_eff

    # ---- search ----

    def _candidate_edges(self, mask: int, vertices: Set[int]) -> List[int]:
        cand: List[int] = []
        for edge in self.edges_spec:
            if mask & (1 << edge.idx):
                continue
            if edge.src_tag in vertices:
                cand.append(edge.idx)
            elif self.allow_reverse and edge.dst_tag in vertices:
                cand.append(edge.idx)
        return cand

    def greedy_initial(self) -> Tuple[List[int], float]:
        mask = 0
        vertices: Set[int] = {self.anchor_tag}
        cost_so_far = 0.0
        seq: List[int] = []

        while mask != self.full_mask:
            cand_edges = self._candidate_edges(mask, vertices)
            if not cand_edges:
                break

            best_edge = None
            best_cost = math.inf
            for e_idx in cand_edges:
                new_mask = mask | (1 << e_idx)
                cost = self.subset_cost[new_mask]
                if cost < best_cost:
                    best_cost = cost
                    best_edge = e_idx

            if best_edge is None:
                break

            mask |= (1 << best_edge)
            edge_spec = self.edges_spec[best_edge]
            if edge_spec.src_tag in vertices and edge_spec.dst_tag not in vertices:
                vertices.add(edge_spec.dst_tag)
            elif self.allow_reverse and edge_spec.dst_tag in vertices and edge_spec.src_tag not in vertices:
                vertices.add(edge_spec.src_tag)
            cost_so_far += best_cost
            seq.append(best_edge)

        return seq, cost_so_far

    def _bnb_dfs(
        self,
        mask: int,
        vertices: Set[int],
        cost_so_far: float,
        seq: List[int],
        best: Dict[str, object],
    ) -> None:
        if mask == self.full_mask:
            if cost_so_far < best["cost"]:
                best["cost"] = cost_so_far
                best["seq"] = list(seq)
            return

        cand_edges = self._candidate_edges(mask, vertices)
        if not cand_edges:
            return

        min_next_cost = min(self.subset_cost[mask | (1 << e)] for e in cand_edges)
        optimistic_lb = cost_so_far + min_next_cost
        if optimistic_lb >= best["cost"]:
            return

        for e_idx in cand_edges:
            new_mask = mask | (1 << e_idx)
            new_vertices = set(vertices)
            edge_spec = self.edges_spec[e_idx]
            if edge_spec.src_tag in new_vertices and edge_spec.dst_tag not in new_vertices:
                new_vertices.add(edge_spec.dst_tag)
            elif self.allow_reverse and edge_spec.dst_tag in new_vertices and edge_spec.src_tag not in new_vertices:
                new_vertices.add(edge_spec.src_tag)

            seq.append(e_idx)
            self._bnb_dfs(
                new_mask,
                new_vertices,
                cost_so_far + self.subset_cost[new_mask],
                seq,
                best,
            )
            seq.pop()

    def search_best_seq(self) -> Tuple[List[int], float, List[int], float, int]:
        greedy_seq, greedy_cost = self.greedy_initial()
        best_seq: List[int] = list(greedy_seq)
        best_edge_cost = float("inf")
        best_anchor = self.anchor_tag
        best_total_cost = float("inf")

        for anchor in sorted(self.tag_to_label.keys()):
            best = {"cost": float("inf"), "seq": []}
            self._bnb_dfs(0, {anchor}, 0.0, [], best)
            edge_cost = float(best["cost"])
            if math.isinf(edge_cost):
                continue
            root_cost = self.cost_scale * self.vertex_F_eff[anchor]
            total_cost = root_cost + edge_cost
            if total_cost < best_total_cost:
                best_total_cost = total_cost
                best_edge_cost = edge_cost
                best_anchor = anchor
                best_seq = list(best["seq"])  # type: ignore[arg-type]

        if math.isinf(best_edge_cost):
            best_edge_cost = 0.0

        return greedy_seq, greedy_cost, best_seq, best_edge_cost, best_anchor

    # ---- plan building ----

    def build_plan(
        self,
        seq: List[int],
        root_cost: float,
        edge_cost: float,
        anchor_tag: int,
    ) -> Plan:
        steps: List[PlanStep] = []
        step_id = 1
        visited: Set[int] = {anchor_tag}
        anchor_alias = self.tag_to_alias[anchor_tag]

        steps.append(
            PlanStep(
                step_id=step_id,
                op="VERTEX_SCAN",
                pattern=f"{self.query_name}_anchor[{anchor_alias}]",
                cost=root_cost,
                detail=f"Scan anchor vertex {anchor_alias} ({self.tag_to_label[anchor_tag]})",
            )
        )
        step_id += 1

        for detail in self.vertex_filters.get(anchor_tag, []):
            steps.append(
                PlanStep(
                    step_id=step_id,
                    op="FILTER",
                    pattern=f"{self.query_name}_anchor[{anchor_alias}]",
                    cost=0.0,
                    detail=detail,
                )
            )
            step_id += 1

        mask = 0
        for e_idx in seq:
            mask |= (1 << e_idx)
            edge_spec = self.edges_spec[e_idx]
            reverse = False
            if edge_spec.src_tag in visited:
                from_tag = edge_spec.src_tag
                to_tag = edge_spec.dst_tag
            elif self.allow_reverse and edge_spec.dst_tag in visited:
                reverse = True
                from_tag = edge_spec.dst_tag
                to_tag = edge_spec.src_tag
            else:
                from_tag = edge_spec.src_tag
                to_tag = edge_spec.dst_tag
                self.warnings.append(
                    f"build_plan: edge_idx={e_idx} relation={edge_spec.description} not executable from visited_tags={sorted(visited)}"
                )

            src_alias = self.tag_to_alias[from_tag]
            dst_alias = self.tag_to_alias[to_tag]
            pattern_edges = [str(i) for i in range(self.num_edges) if mask & (1 << i)]
            pattern_name = f"{self.query_name}_Eset[{','.join(pattern_edges)}]"

            steps.append(
                PlanStep(
                    step_id=step_id,
                    op="EXPAND",
                    pattern=pattern_name,
                    cost=self.subset_cost[mask],
                    detail=edge_spec.description + (" [REVERSE]" if reverse else ""),
                    from_var=src_alias,
                    to_var=dst_alias,
                )
            )
            step_id += 1

            newly_visited: List[int] = []
            if to_tag not in visited:
                visited.add(to_tag)
                newly_visited.append(to_tag)

            for tag in newly_visited:
                if tag == anchor_tag:
                    continue
                for detail in self.vertex_filters.get(tag, []):
                    steps.append(
                        PlanStep(
                            step_id=step_id,
                            op="FILTER",
                            pattern=pattern_name,
                            cost=0.0,
                            detail=detail,
                        )
                    )
                    step_id += 1

            for detail in self.edge_filters.get(e_idx, []):
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        op="FILTER",
                        pattern=pattern_name,
                        cost=0.0,
                        detail=detail,
                    )
                )
                step_id += 1

        steps.append(
            PlanStep(
                step_id=step_id,
                op="AGGREGATE",
                pattern=f"{self.query_name}_Eset[all]",
                cost=0.0,
                detail="AGGREGATE (refer to original SQL)",
            )
        )

        total_cost = root_cost + edge_cost
        return Plan(
            query=self.query_name,
            root_pattern=f"{self.query_name}_anchor[{anchor_alias}]",
            root_cost=root_cost,
            steps=steps,
            total_cost=total_cost,
        )


# -----------------------------------------------------
# Data loading and aggregation
# -----------------------------------------------------


def load_json(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_schema(repo_root: Path) -> SchemaInfo:
    schema_path = repo_root / "schemas" / "imdb" / "imdb_glogs_schema.json"
    data = load_json(schema_path)

    entity_id_to_name = {
        entry["label"]["id"]: entry["label"]["name"]
        for entry in data["entities"]
    }
    relation_id_to_name = {
        entry["label"]["id"]: entry["label"]["name"]
        for entry in data["relations"]
    }
    entity_name_to_id = {name: idx for idx, name in entity_id_to_name.items()}
    return SchemaInfo(
        entity_id_to_name=entity_id_to_name,
        entity_name_to_id=entity_name_to_id,
        relation_id_to_name=relation_id_to_name,
    )


def resolve_dynamic_label(
    table: str,
    alias: str,
    neighbors: Dict[str, Set[str]],
    alias_table: Dict[str, str],
) -> Optional[str]:
    table = table.lower()

    if table == "info_type":
        for nb in neighbors.get(alias, set()):
            nb_table = alias_table.get(nb)
            if nb_table == "movie_info_idx":
                return "infoIdxVertex"
            if nb_table == "movie_info":
                return "infoVertex"
            if nb_table == "person_info":
                return "personInfoVertex"
        return "infoVertex"

    if table == "kind_type":
        return "title"

    if table == "role_type":
        return "castInfoVertex"

    if table == "comp_cast_type":
        return "complCastInfoVertex"

    return None


def collect_alias_stats(
    query_json: Dict,
    schema: SchemaInfo,
) -> Tuple[
    Dict[str, AliasStat],
    Dict[str, List[str]],
    Dict[str, Set[str]],
    List[Tuple[str, str]],
]:
    aliases_data: Dict[str, Dict] = query_json.get("aliases", {})
    edges_data: List[Dict] = query_json.get("edges", [])

    alias_table: Dict[str, str] = {}
    neighbors: Dict[str, Set[str]] = {}
    degree: Dict[str, int] = {}

    for alias, info in aliases_data.items():
        table = info.get("table", "").lower()
        alias_table[alias] = table
        neighbors.setdefault(alias, set())
        degree.setdefault(alias, 0)

    sql_edges: List[Tuple[str, str]] = []
    for edge in edges_data:
        left = edge.get("left_alias")
        right = edge.get("right_alias")
        if not left or not right:
            continue
        neighbors.setdefault(left, set()).add(right)
        neighbors.setdefault(right, set()).add(left)
        degree[left] = degree.get(left, 0) + 1
        degree[right] = degree.get(right, 0) + 1
        sql_edges.append((left, right))

    alias_stats: Dict[str, AliasStat] = {}
    label_to_aliases: Dict[str, List[str]] = {}

    for alias, info in aliases_data.items():
        table = alias_table[alias]
        # 1) Vertex tables: map directly to vertex labels in schema.entities
        label = TABLE_TO_LABEL_DIRECT.get(table)
        # 2) Non-vertex tables: map to relations so filters can be attached to edges/edge attributes
        if label is None and table in NON_VERTEX_TABLE_TO_RELATION:
            label = f"__EDGE__:{NON_VERTEX_TABLE_TO_RELATION[table]}"
        # 3) Others: keep legacy heuristics (only for a few tables like info_type/role_type)
        if label is None:
            label = resolve_dynamic_label(table, alias, neighbors, alias_table)
        # 4) Still unknown: keep original table name (warn later; do not force a wrong attachment)
        if label is None:
            label = table

        combined = info.get("combined", {})
        sel = float(combined.get("selectivity", 1.0) or 1.0)

        filters: List[str] = []
        for fil in info.get("filters", []) or []:
            expr = fil.get("expression")
            if expr:
                filters.append(expr)

        alias_stats[alias] = AliasStat(
            alias=alias,
            table=table,
            label=label,
            selectivity=sel,
            filters=filters,
            degree=degree.get(alias, 0),
        )

        # Only allow vertex labels that exist in the schema to participate
        if label in schema.entity_name_to_id:
            label_to_aliases.setdefault(label, []).append(alias)

    # Keep output order stable
    for label_aliases in label_to_aliases.values():
        label_aliases.sort()

    return alias_stats, label_to_aliases, {k: set(v) for k, v in neighbors.items()}, sql_edges


# -----------------------------------------------------
# CLI
# -----------------------------------------------------


def run_optimizer(
    query_name: str,
    repo_root: Path,
    json_dir: Path,
    estimator: GLogsEstimator,
    cost_scale: float,
    schema: SchemaInfo,
    allow_reverse: bool,
) -> None:
    qname = query_name.lower()
    filters_path = json_dir / f"{qname}_filters.json"
    pattern_path = repo_root / "patterns" / "job" / f"{qname}.json"

    query_json = load_json(filters_path)
    pattern_json = load_json(pattern_path)
    query_json["allow_reverse"] = bool(allow_reverse)

    (
        alias_stats,
        label_to_aliases,
        alias_neighbors,
        sql_edges,
    ) = collect_alias_stats(query_json, schema)

    optimizer = JobQueryOptimizer(
        query_name=qname,
        query_json=query_json,
        pattern_json=pattern_json,
        schema=schema,
        alias_stats=alias_stats,
        label_to_aliases=label_to_aliases,
        alias_neighbors=alias_neighbors,
        sql_edges=sql_edges,
        estimator=estimator,
        cost_scale=cost_scale,
    )

    # allow_reverse affects feasible expand candidates and physical direction in build_plan
    optimizer.allow_reverse = bool(query_json.get("allow_reverse", True))

    output_lines: List[str] = []
    output_lines.append(f"[INFO] === Optimizing query {qname} ===")
    output_lines.append(f"[INFO] allow_reverse={optimizer.allow_reverse}")

    output_lines.append("[INFO] Alias binding diagnostics:")
    for alias in sorted(alias_stats.keys()):
        st = alias_stats[alias]
        target = optimizer.alias_target.get(alias, "(unknown)")
        output_lines.append(
            f"  alias={alias}, table={st.table}, mapped_label={st.label}, sel={st.selectivity:.6g}, target={target}"
        )
        for expr in st.filters:
            output_lines.append(f"    filter: {alias}: {expr}")

    output_lines.append("[INFO] Vertex effective F values (after selectivity):")
    for tag, F_eff in optimizer.vertex_F_eff.items():
        alias = optimizer.tag_to_alias[tag]
        label = optimizer.tag_to_label[tag]
        F_struct = optimizer.vertex_F_struct[tag]
        sel = optimizer.vertex_selectivity.get(tag, 1.0)
        output_lines.append(
            f"  tag_id={tag}, alias={alias}, label={label}, "
            f"F_struct={F_struct:.4f}, sel={sel:.6f}, F_eff={F_eff:.4f}"
        )

    root_F_eff = optimizer.vertex_F_eff[optimizer.anchor_tag]
    root_cost = optimizer.cost_scale * root_F_eff
    output_lines.append(
        f"[INFO] Greedy anchor: tag_id={optimizer.anchor_tag}, "
        f"alias={optimizer.tag_to_alias[optimizer.anchor_tag]}, "
        f"label={optimizer.tag_to_label[optimizer.anchor_tag]}"
    )
    output_lines.append(f"[INFO] Greedy root cost: {root_cost:.4f}")

    (
        greedy_seq,
        greedy_cost,
        best_seq,
        best_edge_cost,
        best_anchor,
    ) = optimizer.search_best_seq()

    best_root_F_eff = optimizer.vertex_F_eff[best_anchor]
    best_root_cost = optimizer.cost_scale * best_root_F_eff
    if best_anchor != optimizer.anchor_tag:
        output_lines.append(
            f"[INFO] BnB anchor override: tag_id={best_anchor}, "
            f"alias={optimizer.tag_to_alias[best_anchor]}, "
            f"label={optimizer.tag_to_label[best_anchor]}, "
            f"root_cost={best_root_cost:.4f}"
        )
    else:
        output_lines.append("[INFO] BnB anchor matches greedy anchor")

    greedy_plan = optimizer.build_plan(
        greedy_seq,
        root_cost,
        greedy_cost,
        optimizer.anchor_tag,
    )
    best_plan = optimizer.build_plan(
        best_seq,
        best_root_cost,
        best_edge_cost,
        best_anchor,
    )

    output_lines.append("")
    output_lines.extend(render_plan(greedy_plan, "Greedy plan"))
    output_lines.append("")
    output_lines.extend(render_plan(best_plan, "BnB best plan"))

    output_lines.append("")
    output_lines.append("[INFO] Single-edge subset F values:")
    for edge in optimizer.edges_spec:
        mask = 1 << edge.idx
        F = optimizer.subset_F.get(mask, float("nan"))
        src_alias = optimizer.tag_to_alias[edge.src_tag]
        dst_alias = optimizer.tag_to_alias[edge.dst_tag]
        output_lines.append(
            f"  edge_idx={edge.idx}, from={src_alias}, to={dst_alias}, "
            f"relation={edge.description}, F={F:.4f}"
        )

    if optimizer.warnings:
        output_lines.append("")
        output_lines.append("[WARN] Planner warnings:")
        for w in optimizer.warnings:
            output_lines.append(f"  {w}")

    output_dir = Path(__file__).resolve().parent / "query_plan"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / qname
    output_text = "\n".join(output_lines) + "\n"
    output_path.write_text(output_text, encoding="utf-8")
    print(f"[INFO] Plan output written to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JOB query optimizer using GLogS estimates")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Query name to optimize (e.g., q1)",
    )
    parser.add_argument(
        "--glogs",
        default="catalogs/imdb_small/glogs/imdb_small.bincode",
        help="Relative path to the GLogS catalog",
    )
    parser.add_argument(
        "--script",
        default="scripts/glogs/estimate.sh",
        help="Relative path to the script that invokes GLogS",
    )
    parser.add_argument(
        "--json-dir",
        default="ispg/imdb/job/query_filters",
        help="Directory containing query JSON files (relative to repo root)",
    )
    parser.add_argument(
        "--cost-scale",
        type=float,
        default=0.1,
        help="Cost scaling factor",
    )
    parser.add_argument(
        "--allow-reverse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to allow reverse expand (dst -> src). Enabled by default; disable with --no-allow-reverse if the storage lacks reverse adjacency.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate execution plans for all queries",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    json_dir = (repo_root / args.json_dir).resolve()
    estimator = GLogsEstimator(repo_root=repo_root, catalog_rel=args.glogs, script_rel=args.script)
    schema = load_schema(repo_root)

    query_order: List[str] = []
    seen: Set[str] = set()

    def add_query(name: str) -> None:
        q = name.lower()
        if q.endswith("_filters"):
            q = q[:-8]
        if q in seen:
            return
        seen.add(q)
        query_order.append(q)

    for q in args.queries or []:
        add_query(q)

    if args.all:
        if not json_dir.exists():
            raise SystemExit(f"Query JSON directory does not exist: {json_dir}")
        def query_key(path: Path) -> Tuple[float, str]:
            stem = path.stem
            base = stem[:-8] if stem.endswith("_filters") else stem
            if base.startswith("q") and base[1:].isdigit():
                return (float(int(base[1:])), base)
            return (math.inf, base)

        for path in sorted(json_dir.glob("*_filters.json"), key=query_key):
            add_query(path.stem)

    if not query_order:
        raise SystemExit("Please specify at least one query via --query or --all")

    for query_name in query_order:
        run_optimizer(
            query_name=query_name,
            repo_root=repo_root,
            json_dir=json_dir,
            estimator=estimator,
            cost_scale=args.cost_scale,
            schema=schema,
            allow_reverse=args.allow_reverse,
        )


if __name__ == "__main__":
    main()
