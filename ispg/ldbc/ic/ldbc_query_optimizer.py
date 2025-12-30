#!/usr/bin/env python3
"""LDBC IC query optimizer supporting relgo/ispg strategies and varExpand estimation."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_GLOGS = "catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode"
DEFAULT_GLOGS_SCRIPT = "scripts/glogs/estimate.sh"
DEFAULT_FILTER_DIR = "ispg/ldbc/query_filters"
DEFAULT_PATTERN_DIR = "ispg/ldbc/query_pattern"


# -----------------------------------------------------
# Schema helpers
# -----------------------------------------------------


@dataclass
class SchemaInfo:
    entity_id_to_name: Dict[int, str]
    entity_name_to_id: Dict[str, int]
    relation_id_to_name: Dict[int, str]
    relation_name_to_id: Dict[str, int]


@dataclass
class VertexAliasStat:
    alias: str
    label: str
    domain: str
    selectivity: float
    filters: List[str] = field(default_factory=list)


@dataclass
class EdgeAliasStat:
    alias: str
    relation_label: str
    selectivity: float
    filters: List[str] = field(default_factory=list)


@dataclass
class EdgeSpec:
    idx: int
    alias: Optional[str]
    src_tag: int
    dst_tag: int
    estimator_src_tag: int
    estimator_dst_tag: int
    relation_label: str
    schema_source_label: str
    schema_target_label: str
    min_hops: int
    max_hops: int
    is_var_expand: bool
    domain: str  # "match" or "sql"
    is_identity: bool = False


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
    strategy: str
    root_pattern: str
    root_cost: float
    steps: List[PlanStep]
    total_cost: float


def render_plan(plan: Plan, title: str) -> List[str]:
    lines: List[str] = []
    lines.append(f"=== {title} ({plan.query}, strategy={plan.strategy}) ===")
    lines.append(f"  Root pattern: {plan.root_pattern}")
    lines.append(f"  Total plan cost: {plan.total_cost:.6f}")
    for s in plan.steps:
        if s.op in {"VERTEX_SCAN", "VAREXPAND"}:
            lines.append(
                f"    Step {s.step_id}: op={s.op}, pattern={s.pattern}, cost={s.cost:.6f}, detail={s.detail}"
            )
        elif s.op == "FILTER":
            lines.append(
                f"    Step {s.step_id}: op={s.op}, pattern={s.pattern}, detail={s.detail}"
            )
        else:
            lines.append(
                f"    Step {s.step_id}: op={s.op}, pattern={s.pattern}, cost={s.cost:.6f}, "
                f"from={s.from_var}, to={s.to_var}, detail={s.detail}"
            )
    return lines


# -----------------------------------------------------
# GLogS estimator
# -----------------------------------------------------


class GLogsEstimator:
    def __init__(
        self,
        repo_root: Path,
        catalog_rel: str,
        script_rel: str,
        quiet: bool = True,
    ) -> None:
        self.repo_root = repo_root
        self.catalog_path = repo_root / catalog_rel
        self.script_path = repo_root / script_rel
        self.quiet = quiet

        if not self.catalog_path.exists():
            raise FileNotFoundError(f"GLogS catalog not found: {self.catalog_path}")
        if not self.script_path.exists():
            raise FileNotFoundError(f"GLogS estimate.sh not found: {self.script_path}")

    def estimate_pattern(self, pattern: Dict) -> float:
        tmp_dir = Path(tempfile.gettempdir()) / "ispg"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir=str(tmp_dir)) as tmp:
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
                raise RuntimeError(f"Failed to parse GLogS output: {first_line}")
            return float(parts[0])
        except subprocess.CalledProcessError as exc:
            if not self.quiet:
                print(
                    f"[WARN] GLogS invocation failed; using fallback F=1.0. stderr:\n{exc.stderr.strip()}",
                    file=sys.stderr,
                )
            return 1.0
        except RuntimeError as exc:
            if not self.quiet:
                print(f"[WARN] {exc}; using fallback F=1.0", file=sys.stderr)
            return 1.0
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


# -----------------------------------------------------
# Alias stats extraction
# -----------------------------------------------------


def collect_alias_stats(
    query_json: Dict,
) -> Tuple[Dict[str, VertexAliasStat], Dict[str, EdgeAliasStat]]:
    vertex_stats: Dict[str, VertexAliasStat] = {}
    edge_stats: Dict[str, EdgeAliasStat] = {}
    for alias, info in (query_json.get("aliases") or {}).items():
        kind = info.get("kind")
        domain = info.get("domain", "match")
        combined = info.get("combined") or {}
        sel = float(combined.get("selectivity", 1.0) or 1.0)
        filters: List[str] = []
        for fil in info.get("filters") or []:
            expr = fil.get("expression")
            if expr:
                filters.append(expr)
        if kind == "vertex":
            label = info.get("label") or info.get("schema_label") or alias
            vertex_stats[alias] = VertexAliasStat(
                alias=alias,
                label=label,
                domain=domain,
                selectivity=sel,
                filters=filters,
            )
        elif kind == "table":
            relation = info.get("relationship_label") or info.get("label") or alias
            edge_stats[alias] = EdgeAliasStat(
                alias=alias,
                relation_label=relation,
                selectivity=sel,
                filters=filters,
            )
    return vertex_stats, edge_stats


# -----------------------------------------------------
# Optimizer core
# -----------------------------------------------------


class LdbcQueryOptimizer:
    def __init__(
        self,
        query_name: str,
        query_json: Dict,
        pattern_json: Dict,
        schema: SchemaInfo,
        estimator: GLogsEstimator,
        cost_scale: float,
        strategy: str,
        knows_alpha: float = 0.0,
    ) -> None:
        self.query_name = query_name
        self.strategy = strategy
        self.query_json = query_json
        self.pattern_match = pattern_json.get("match") or {}
        self.pattern_sql = pattern_json.get("sql") or {}
        self.schema = schema
        self.estimator = estimator
        self.cost_scale = cost_scale
        self.knows_relation_label = "Person_knows_Person"
        self.knows_alpha = float(knows_alpha)

        top_meta = query_json.get("top") if isinstance(query_json, dict) else None
        self.top_k: Optional[int] = None
        self.top_order_by: Optional[str] = None
        if isinstance(top_meta, dict):
            try:
                k = int(top_meta.get("k")) if top_meta.get("k") is not None else None
            except Exception:
                k = None
            self.top_k = k if k and k > 0 else None
            ob = top_meta.get("order_by")
            self.top_order_by = str(ob) if ob else None

        self._post_top_edge_indices: Set[int] = set()
        self._post_top_mask: int = 0

        self.vertex_stats, self.edge_stats = collect_alias_stats(query_json)

        self.tag_to_alias: Dict[int, str] = {}
        self.tag_to_label: Dict[int, str] = {}
        self.vertex_domain: Dict[int, str] = {}
        self.vertex_selectivity: Dict[int, float] = {}
        self.vertex_filters: Dict[int, List[str]] = {}

        self._ingest_vertices(self.pattern_match.get("vertices", []), domain="match")
        self._ingest_vertices(self.pattern_sql.get("vertices", []), domain="sql")
        if not self.tag_to_alias:
            raise ValueError(f"Query {query_name} has no vertices; cannot optimize")

        self.edges_spec: List[EdgeSpec] = []
        self.edge_selectivity: Dict[int, float] = {}
        self.edge_filters: Dict[int, List[str]] = {}
        self._ingest_edges(self.pattern_match.get("edges", []), domain="match")
        self._ingest_edges(self.pattern_sql.get("edges", []), domain="sql")
        if not self.edges_spec:
            raise ValueError(f"Query {query_name} pattern has no edges; cannot build a plan")

        self.num_edges = len(self.edges_spec)
        self.full_mask = (1 << self.num_edges) - 1

        self._init_top_defer_edges()

        self.var_expand_F: Dict[int, float] = {}
        self.var_expand_hop_breakdown: Dict[int, List[Tuple[int, float]]] = {}
        self._init_var_expand_costs()

        self.vertex_F_struct: Dict[int, float] = {}
        self.vertex_F_eff: Dict[int, float] = {}
        self._init_vertex_costs()

        self._subset_cache: Dict[Tuple[int, Tuple[int, ...]], Tuple[float, float]] = {
            (0, ()): (0.0, 0.0)
        }

    # ---- helpers to ensure full edge coverage ----

    def _ensure_full_edge_cover(self, seq: List[int], anchor_tag: int) -> List[int]:
        completed: List[int] = list(seq)
        mask = 0
        visited: Set[int] = {anchor_tag}
        for idx in completed:
            mask |= 1 << idx
            spec = self.edges_spec[idx]
            visited.add(spec.src_tag)
            visited.add(spec.dst_tag)

        remaining = [spec.idx for spec in self.edges_spec if not (mask & (1 << spec.idx))]
        if not remaining:
            return completed

        while remaining:
            attach_idx = None
            for idx in remaining:
                spec = self.edges_spec[idx]
                if spec.src_tag in visited or spec.dst_tag in visited:
                    attach_idx = idx
                    break
            if attach_idx is None:
                attach_idx = remaining[0]
            remaining.remove(attach_idx)
            completed.append(attach_idx)
            mask |= 1 << attach_idx
            spec = self.edges_spec[attach_idx]
            visited.add(spec.src_tag)
            visited.add(spec.dst_tag)

        return completed

    def _sequence_edge_cost(self, seq: List[int], anchor_tag: int) -> float:
        mask = 0
        cost = 0.0
        visited: Set[int] = {anchor_tag}
        for idx in seq:
            mask |= 1 << idx
            spec = self.edges_spec[idx]
            visited.add(spec.src_tag)
            visited.add(spec.dst_tag)
            cost += self._subset_metrics(mask, visited)[1]
        return cost

    # ---- ingestion helpers ----

    def _ingest_vertices(self, vertices: Iterable[Dict], domain: str) -> None:
        for vertex in vertices:
            tag = vertex["tag_id"]
            alias = vertex.get("alias") or f"{domain}_tag_{tag}"
            label = vertex.get("label")
            if not label:
                label_id = vertex.get("label_id")
                label = self.schema.entity_id_to_name.get(label_id, alias)
            self.tag_to_alias[tag] = alias
            self.tag_to_label[tag] = label
            self.vertex_domain[tag] = domain

            stat = self.vertex_stats.get(alias)
            sel = stat.selectivity if stat else 1.0
            filters = [f"{alias}: {expr}" for expr in (stat.filters if stat else [])]
            self.vertex_selectivity[tag] = sel
            self.vertex_filters[tag] = filters

    def _ingest_edges(self, edges: Iterable[Dict], domain: str) -> None:
        for edge in edges:
            idx = len(self.edges_spec)
            src_tag = edge["source_tag"]
            dst_tag = edge["target_tag"]
            relation_label = edge.get("relation_label", f"edge_{idx}")
            schema_source_label = edge.get("schema_source_label", self.tag_to_label.get(src_tag, ""))
            schema_target_label = edge.get("schema_target_label", self.tag_to_label.get(dst_tag, ""))

            est_src_tag = src_tag
            est_dst_tag = dst_tag
            src_label = self.tag_to_label.get(src_tag)
            dst_label = self.tag_to_label.get(dst_tag)
            if (
                schema_source_label
                and schema_target_label
                and src_label
                and dst_label
            ):
                if src_label == schema_source_label and dst_label == schema_target_label:
                    pass
                elif dst_label == schema_source_label and src_label == schema_target_label:
                    est_src_tag, est_dst_tag = dst_tag, src_tag
                # If labels cannot be matched to the schema, keep query direction (do not force swap).

            spec = EdgeSpec(
                idx=idx,
                alias=edge.get("alias"),
                src_tag=src_tag,
                dst_tag=dst_tag,
                estimator_src_tag=est_src_tag,
                estimator_dst_tag=est_dst_tag,
                relation_label=relation_label,
                schema_source_label=schema_source_label,
                schema_target_label=schema_target_label,
                min_hops=int(edge.get("min_hops", 1) or 1),
                max_hops=int(edge.get("max_hops", 1) or 1),
                is_var_expand=bool(edge.get("is_var_expand")),
                domain=domain,
                is_identity=bool(edge.get("is_identity")),
            )
            self.edges_spec.append(spec)
            self.edge_selectivity[idx] = 1.0
            self.edge_filters[idx] = []
            if spec.alias:
                stat = self.edge_stats.get(spec.alias)
                if stat and stat.relation_label == relation_label:
                    self.edge_selectivity[idx] *= stat.selectivity
                    self.edge_filters[idx].extend(f"{spec.alias}: {expr}" for expr in stat.filters)

    # ---- schema helpers ----

    def _entity_label_id(self, label: str) -> int:
        if label not in self.schema.entity_name_to_id:
            raise KeyError(f"Vertex label not found in schema: {label}")
        return self.schema.entity_name_to_id[label]

    def _relation_label_id(self, label: str) -> int:
        if label not in self.schema.relation_name_to_id:
            raise KeyError(f"Relation label not found in schema: {label}")
        return self.schema.relation_name_to_id[label]

    # ---- pattern construction ----

    def _pattern_for_mask(
        self,
        mask: int,
        explicit_vertices: Optional[Iterable[int]] = None,
    ) -> Dict:
        used_tags: Set[int] = set(explicit_vertices or [])
        active_edges: List[EdgeSpec] = []
        for spec in self.edges_spec:
            if not (mask & (1 << spec.idx)):
                continue
            used_tags.add(spec.src_tag)
            used_tags.add(spec.dst_tag)
            if spec.is_var_expand or spec.is_identity:
                continue
            active_edges.append(spec)

        if not used_tags:
            return {"vertices": [], "edges": []}

        sorted_tags = sorted(used_tags)
        tag_lookup = {tag: idx for idx, tag in enumerate(sorted_tags)}
        vertices_sel = [
            {
                "tag_id": tag_lookup[tag],
                "label_id": self._entity_label_id(self.tag_to_label[tag]),
            }
            for tag in sorted_tags
        ]
        edges_sel = [
            {
                "tag_id": spec.idx,
                "src": tag_lookup[spec.estimator_src_tag],
                "dst": tag_lookup[spec.estimator_dst_tag],
                "label_id": self._relation_label_id(spec.relation_label),
            }
            for spec in active_edges
        ]
        return {"vertices": vertices_sel, "edges": edges_sel}

    def _pattern_for_vertex(self, tag_id: int) -> Dict:
        return {
            "vertices": [
                {
                    "tag_id": tag_id,
                    "label_id": self._entity_label_id(self.tag_to_label[tag_id]),
                }
            ],
            "edges": [],
        }

    # ---- varExpand estimation ----

    def _init_var_expand_costs(self) -> None:
        for spec in self.edges_spec:
            if not spec.is_var_expand:
                continue
            breakdown: List[Tuple[int, float]] = []
            hop_values: List[float] = []
            for hop in range(spec.min_hops, spec.max_hops + 1):
                value = max(self._estimate_var_expand_hop(spec, hop), 1.0)
                breakdown.append((hop, value))
                hop_values.append(value)
            total = hop_values[0] if spec.min_hops == spec.max_hops else sum(hop_values)
            self.var_expand_F[spec.idx] = total
            self.var_expand_hop_breakdown[spec.idx] = breakdown

    def _estimate_var_expand_hop(self, spec: EdgeSpec, hop: int) -> float:
        src_label = spec.schema_source_label or self.tag_to_label.get(spec.src_tag)
        dst_label = spec.schema_target_label or self.tag_to_label.get(spec.dst_tag)
        if not src_label or not dst_label:
            raise ValueError(f"varExpand edge {spec.relation_label} is missing label information")
        rel_id = self._relation_label_id(spec.relation_label)

        vertices = [
            {
                "tag_id": 0,
                "label_id": self._entity_label_id(src_label),
            }
        ]
        edges: List[Dict] = []
        for step in range(1, hop + 1):
            vertices.append(
                {
                    "tag_id": step,
                    "label_id": self._entity_label_id(dst_label),
                }
            )
            edges.append(
                {
                    "tag_id": step - 1,
                    "src": step - 1,
                    "dst": step,
                    "label_id": rel_id,
                }
            )
        pattern = {"vertices": vertices, "edges": edges}
        return self.estimator.estimate_pattern(pattern)

    def _knows_edge_count(self, mask: int) -> int:
        cnt = 0
        for spec in self.edges_spec:
            if not (mask & (1 << spec.idx)):
                continue
            if spec.is_identity:
                continue
            if spec.relation_label == self.knows_relation_label:
                cnt += 1
        return cnt

    def _init_top_defer_edges(self) -> None:
        """Initialize edges that are allowed/required to be executed after TOP.

        This is intentionally conservative: we only enable TOP-aware planning for
        IC-10, and only defer the b-e location edge that does not affect scoring.
        """

        self._post_top_edge_indices = set()
        self._post_top_mask = 0

        if not self.top_k:
            return

        if not self.query_name.lower().startswith("ic-10"):
            return

        alias_to_tag = {alias: tag for tag, alias in self.tag_to_alias.items()}
        b_tag = alias_to_tag.get("b")
        e_tag = alias_to_tag.get("e")
        if b_tag is None or e_tag is None:
            return

        for spec in self.edges_spec:
            if spec.relation_label != "Person_isLocatedIn_Place":
                continue
            if {spec.src_tag, spec.dst_tag} != {b_tag, e_tag}:
                continue
            self._post_top_edge_indices.add(spec.idx)
            self._post_top_mask |= 1 << spec.idx

    def _is_post_top_phase(self, mask: int) -> bool:
        return bool(self._post_top_mask) and bool(mask & self._post_top_mask)

    # ---- vertex costs ----

    def _anchor_candidates(self) -> List[int]:
        """Anchor candidates for planning.

        Per the intended cost model, anchor selection should be driven by
        effective frequency (GLogS structural frequency × selectivity).

        To avoid picking an unfiltered vertex just because its label is rare
        in the GLogS catalog, we prefer vertices that have extracted filters.
        """

        with_filters = [tag for tag in self.tag_to_label if self.vertex_filters.get(tag)]
        return sorted(with_filters) if with_filters else sorted(self.tag_to_label.keys())

    def _init_vertex_costs(self) -> None:
        for tag in self.tag_to_label:
            pattern = self._pattern_for_vertex(tag)
            F_struct = max(self.estimator.estimate_pattern(pattern), 1.0)
            sel = self.vertex_selectivity.get(tag, 1.0)
            F_eff = F_struct * sel
            self.vertex_F_struct[tag] = F_struct
            self.vertex_F_eff[tag] = F_eff

        allowed_tags = self._anchor_candidates()
        self.anchor_tag = min(allowed_tags, key=lambda tag: self.vertex_F_eff[tag])

    # ---- subset costs ----

    def _used_tags_for_mask(self, mask: int) -> Set[int]:
        used: Set[int] = set()
        for spec in self.edges_spec:
            if mask & (1 << spec.idx):
                used.add(spec.src_tag)
                used.add(spec.dst_tag)
        return used

    def _subset_metrics(
        self,
        mask: int,
        explicit_vertices: Optional[Iterable[int]] = None,
    ) -> Tuple[float, float]:
        vertex_set: Set[int] = set(explicit_vertices or [])
        vertex_set.update(self._used_tags_for_mask(mask))
        vertex_key = tuple(sorted(vertex_set))
        cache_key = (mask, vertex_key)
        if cache_key in self._subset_cache:
            return self._subset_cache[cache_key]

        pattern = self._pattern_for_mask(mask, vertex_set)
        base_struct = 1.0 if not pattern["edges"] else max(self.estimator.estimate_pattern(pattern), 1.0)
        multiplier = 1.0
        for spec in self.edges_spec:
            if spec.is_var_expand and mask & (1 << spec.idx):
                multiplier *= self.var_expand_F.get(spec.idx, 1.0)

        F_struct = base_struct * multiplier

        # Knows-only power-law correction (to compensate small-catalog density bias).
        # Apply ONLY when the subset contains Person_knows_Person and there is an anchor filter.
        # The correction scales structural frequency as: F_struct *= p_anchor^(alpha * m_knows)
        # where alpha < 0 increases the cost when p_anchor is small.
        if self.knows_alpha != 0.0:
            m_knows = self._knows_edge_count(mask)
            if m_knows:
                p_anchor = float(self.vertex_selectivity.get(self.anchor_tag, 1.0))
                # Avoid zero selectivity causing infinities.
                p_anchor = max(p_anchor, 1e-12)
                if p_anchor < 1.0:
                    F_struct *= p_anchor ** (self.knows_alpha * m_knows)

        sel = 1.0
        for tag in vertex_set:
            sel *= self.vertex_selectivity.get(tag, 1.0)
        for spec in self.edges_spec:
            if mask & (1 << spec.idx):
                if spec.is_identity:
                    continue
                sel *= self.edge_selectivity.get(spec.idx, 1.0)

        F_eff = F_struct * sel

        # TOP-aware cost: once we enter the post-TOP phase, cap effective frequency by k.
        if self.top_k and self._is_post_top_phase(mask):
            F_eff = min(F_eff, float(self.top_k))
        cost = self.cost_scale * F_eff
        self._subset_cache[cache_key] = (F_eff, cost)
        return F_eff, cost

    # ---- search helpers ----

    def _candidate_edges(self, mask: int, vertices: Set[int]) -> List[int]:
        cand: List[int] = []
        pre_top_done = True
        if self._post_top_mask:
            pre_top_done = ((mask & ~self._post_top_mask) == (self.full_mask & ~self._post_top_mask))
        for spec in self.edges_spec:
            if mask & (1 << spec.idx):
                continue
            if self._post_top_mask and not pre_top_done and (self._post_top_mask & (1 << spec.idx)):
                continue
            if spec.src_tag in vertices or spec.dst_tag in vertices:
                cand.append(spec.idx)
        if cand:
            return cand
        if self._post_top_mask and not pre_top_done:
            return [
                spec.idx
                for spec in self.edges_spec
                if not (mask & (1 << spec.idx)) and not (self._post_top_mask & (1 << spec.idx))
            ]
        return [spec.idx for spec in self.edges_spec if not (mask & (1 << spec.idx))]

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
                trial_vertices = set(vertices)
                spec = self.edges_spec[e_idx]
                trial_vertices.add(spec.src_tag)
                trial_vertices.add(spec.dst_tag)
                _, cost = self._subset_metrics(new_mask, trial_vertices)
                if cost < best_cost:
                    best_cost = cost
                    best_edge = e_idx
            if best_edge is None:
                break
            mask |= 1 << best_edge
            spec = self.edges_spec[best_edge]
            vertices.add(spec.src_tag)
            vertices.add(spec.dst_tag)
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
        min_next_cost = math.inf
        for idx in cand_edges:
            spec = self.edges_spec[idx]
            test_vertices = set(vertices)
            test_vertices.add(spec.src_tag)
            test_vertices.add(spec.dst_tag)
            cost = self._subset_metrics(mask | (1 << idx), test_vertices)[1]
            if cost < min_next_cost:
                min_next_cost = cost
        if cost_so_far + min_next_cost >= best["cost"]:
            return
        for idx in cand_edges:
            new_mask = mask | (1 << idx)
            new_vertices = set(vertices)
            spec = self.edges_spec[idx]
            new_vertices.add(spec.src_tag)
            new_vertices.add(spec.dst_tag)
            seq.append(idx)
            self._bnb_dfs(
                new_mask,
                new_vertices,
                cost_so_far + self._subset_metrics(new_mask, new_vertices)[1],
                seq,
                best,
            )
            seq.pop()

    def search_best_seq(self) -> Tuple[List[int], float, List[int], float, int]:
        greedy_seq, greedy_cost = self.greedy_initial()
        # Anchor is chosen solely by minimal vertex effective frequency (F_struct * selectivity).
        # Do not override anchor by total-plan cost; this matches the intended design.
        anchor = self.anchor_tag
        best = {"cost": float("inf"), "seq": []}
        self._bnb_dfs(0, {anchor}, 0.0, [], best)
        best_seq = list(best["seq"])  # type: ignore[list-item]
        best_edge_cost = float(best["cost"])
        if math.isinf(best_edge_cost):
            best_edge_cost = 0.0
        return greedy_seq, greedy_cost, best_seq, best_edge_cost, anchor

    # ---- plan construction ----

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
        anchor_F = self.vertex_F_eff[anchor_tag]
        steps.append(
            PlanStep(
                step_id=step_id,
                op="VERTEX_SCAN",
                pattern=f"{self.query_name}_anchor[{anchor_alias}]",
                cost=anchor_F,
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
        current_vertices = set(visited)
        inserted_top = False
        for e_idx in seq:
            if (
                not inserted_top
                and self.top_k
                and (self._post_top_mask & (1 << e_idx))
                and mask != self.full_mask
            ):
                detail = f"TOP {self.top_k}"
                if self.top_order_by:
                    detail += f" ORDER BY {self.top_order_by}"
                steps.append(
                    PlanStep(
                        step_id=step_id,
                        op="TOP",
                        pattern=f"{self.query_name}_TOP",
                        cost=0.0,
                        detail=detail,
                    )
                )
                step_id += 1
                inserted_top = True
            spec = self.edges_spec[e_idx]
            next_mask = mask | (1 << e_idx)
            next_vertices = set(current_vertices)
            next_vertices.add(spec.src_tag)
            next_vertices.add(spec.dst_tag)
            # For display, prefer "bound -> newly introduced" direction to avoid showing from_var
            # that does not appear in earlier steps.
            from_tag = spec.src_tag
            to_tag = spec.dst_tag
            if spec.src_tag in current_vertices and spec.dst_tag not in current_vertices:
                from_tag, to_tag = spec.src_tag, spec.dst_tag
            elif spec.dst_tag in current_vertices and spec.src_tag not in current_vertices:
                from_tag, to_tag = spec.dst_tag, spec.src_tag
            src_alias = self.tag_to_alias[from_tag]
            dst_alias = self.tag_to_alias[to_tag]
            pattern_edges = [str(i) for i in range(self.num_edges) if next_mask & (1 << i)]
            pattern_name = f"{self.query_name}_Eset[{','.join(pattern_edges)}]"
            if spec.is_identity:
                op = "IDENTITY"
                detail = f"IDENTITY::{src_alias}<->{dst_alias}"
                step_cost = 0.0
            elif spec.is_var_expand:
                op = "VAREXPAND"
                detail = (
                    f"{spec.domain.upper()}::{spec.relation_label} hops {spec.min_hops}-{spec.max_hops} "
                    f"contrib={self.var_expand_F.get(spec.idx, 1.0):.4f}"
                )
            else:
                op = "EXPAND"
                detail = f"{spec.domain.upper()}::{spec.relation_label}"
            if not spec.is_identity:
                subset_F = self._subset_metrics(next_mask, next_vertices)[0]
                step_cost = subset_F
            steps.append(
                PlanStep(
                    step_id=step_id,
                    op=op,
                    pattern=pattern_name,
                    cost=step_cost,
                    detail=detail,
                    from_var=src_alias,
                    to_var=dst_alias,
                )
            )
            step_id += 1
            mask = next_mask
            current_vertices = next_vertices

            newly_visited: List[int] = []
            for tag in (spec.src_tag, spec.dst_tag):
                if tag not in visited:
                    visited.add(tag)
                    newly_visited.append(tag)

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
            strategy=self.strategy,
            root_pattern=f"{self.query_name}_anchor[{anchor_alias}]",
            root_cost=root_cost,
            steps=steps,
            total_cost=total_cost,
        )


# -----------------------------------------------------
# I/O helpers
# -----------------------------------------------------


def load_json(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_schema(repo_root: Path) -> SchemaInfo:
    schema_path = repo_root / "ispg" / "ldbc" / "ldbc_glogs_schema.json"
    data = load_json(schema_path)
    entity_id_to_name = {entry["label"]["id"]: entry["label"]["name"] for entry in data["entities"]}
    relation_id_to_name = {entry["label"]["id"]: entry["label"]["name"] for entry in data["relations"]}
    entity_name_to_id = {name: idx for idx, name in entity_id_to_name.items()}
    relation_name_to_id = {name: idx for idx, name in relation_id_to_name.items()}
    return SchemaInfo(
        entity_id_to_name=entity_id_to_name,
        entity_name_to_id=entity_name_to_id,
        relation_id_to_name=relation_id_to_name,
        relation_name_to_id=relation_name_to_id,
    )


# -----------------------------------------------------
# Plan orchestration
# -----------------------------------------------------


def run_optimizer(
    query_name: str,
    repo_root: Path,
    json_dir: Path,
    pattern_dir: Path,
    estimator: GLogsEstimator,
    cost_scale: float,
    schema: SchemaInfo,
    strategies: Iterable[str],
    knows_alpha: float = 0.0,
) -> None:
    qname = query_name.lower()
    filters_path = json_dir / f"{qname}_filters.json"
    pattern_path = pattern_dir / f"{qname}.json"
    query_json = load_json(filters_path)
    pattern_json = load_json(pattern_path)

    output_dir = repo_root / "ispg" / "ldbc" / "query_plan"
    output_dir.mkdir(parents=True, exist_ok=True)

    timing_path = output_dir / "plan_generation_time_ms.csv"

    def _append_plan_timing_ms(query: str, strategy: str, elapsed_ms: float) -> None:
        header = "query,strategy,plan_generation_ms"
        line = f"{query},{strategy},{elapsed_ms:.3f}"
        if not timing_path.exists():
            timing_path.write_text(header + "\n" + line + "\n", encoding="utf-8")
            return
        with timing_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    for strategy in strategies:
        t0 = time.perf_counter()
        optimizer = LdbcQueryOptimizer(
            query_name=qname,
            query_json=query_json,
            pattern_json=pattern_json,
            schema=schema,
            estimator=estimator,
            cost_scale=cost_scale,
            strategy=strategy,
            knows_alpha=knows_alpha,
        )

        lines: List[str] = []
        lines.append(f"[INFO] === Optimizing query {qname} (strategy={strategy}) ===")

        def _rel(path: Path) -> str:
            try:
                return str(path.relative_to(repo_root))
            except ValueError:
                return str(path)

        lines.append("[INFO] Input sources:")
        lines.append(f"  filters_dir={_rel(json_dir)}")
        lines.append(f"  pattern_dir={_rel(pattern_dir)}")
        lines.append(f"  glogs_catalog={_rel(estimator.catalog_path)}")
        lines.append(f"  glogs_script={_rel(estimator.script_path)}")
        if optimizer.knows_alpha != 0.0:
            lines.append(
                f"[INFO] Knows power-law correction: relation={optimizer.knows_relation_label}, alpha={optimizer.knows_alpha:g}"
            )

        lines.append("[INFO] Vertex effective F values (after selectivity):")
        for tag in sorted(optimizer.vertex_F_eff.keys()):
            alias = optimizer.tag_to_alias[tag]
            label = optimizer.tag_to_label[tag]
            F_struct = optimizer.vertex_F_struct[tag]
            sel = optimizer.vertex_selectivity.get(tag, 1.0)
            F_eff = optimizer.vertex_F_eff[tag]
            lines.append(
                f"  tag_id={tag}, alias={alias}, label={label}, F_struct={F_struct:.4f}, sel={sel:.6f}, F_eff={F_eff:.4f}"
            )

        root_F_eff = optimizer.vertex_F_eff[optimizer.anchor_tag]
        root_cost = optimizer.cost_scale * root_F_eff
        lines.append(
            f"[INFO] Greedy anchor: tag_id={optimizer.anchor_tag}, alias={optimizer.tag_to_alias[optimizer.anchor_tag]}, "
            f"label={optimizer.tag_to_label[optimizer.anchor_tag]}"
        )
        lines.append(f"[INFO] Greedy root cost: {root_cost:.4f}")

        greedy_seq, greedy_cost, best_seq, best_edge_cost, best_anchor = optimizer.search_best_seq()
        best_root_F_eff = optimizer.vertex_F_eff[best_anchor]
        best_root_cost = optimizer.cost_scale * best_root_F_eff
        lines.append(
            f"[INFO] Anchor fixed by min(F_struct*selectivity): tag_id={best_anchor}, alias={optimizer.tag_to_alias[best_anchor]}, "
            f"label={optimizer.tag_to_label[best_anchor]}, root_cost={best_root_cost:.4f}"
        )

        complete_seq = optimizer._ensure_full_edge_cover(best_seq, best_anchor)
        if len(complete_seq) != len(best_seq):
            lines.append(
                f"[INFO] Edge coverage augmented: original_edges={len(best_seq)}, augmented_edges={len(complete_seq)}"
            )
        augmented_edge_cost = optimizer._sequence_edge_cost(complete_seq, best_anchor)
        best_plan = optimizer.build_plan(complete_seq, best_root_cost, augmented_edge_cost, best_anchor)

        t1 = time.perf_counter()
        elapsed_ms = (t1 - t0) * 1000.0

        lines.append("")
        lines.extend(render_plan(best_plan, "ISPG best plan"))

        if optimizer.var_expand_F:
            lines.append("")
            lines.append("[INFO] varExpand contributions:")
            for edge_idx, breakdown in optimizer.var_expand_hop_breakdown.items():
                spec = optimizer.edges_spec[edge_idx]
                parts = ", ".join(f"hop={hop}: {value:.4f}" for hop, value in breakdown)
                lines.append(
                    f"  edge_idx={edge_idx}, relation={spec.relation_label}, total={optimizer.var_expand_F[edge_idx]:.4f}, {parts}"
                )

        lines.append("")
        lines.append("[INFO] Single-edge subset F values:")
        for spec in optimizer.edges_spec:
            mask = 1 << spec.idx
            vertex_pair = {spec.src_tag, spec.dst_tag}
            F, _ = optimizer._subset_metrics(mask, vertex_pair)
            src_alias = optimizer.tag_to_alias[spec.src_tag]
            dst_alias = optimizer.tag_to_alias[spec.dst_tag]
            lines.append(
                f"  edge_idx={spec.idx}, from={src_alias}, to={dst_alias}, relation={spec.relation_label}, F={F:.4f}"
            )

        output_path = output_dir / f"{qname}_{strategy}.plan"
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[INFO] Plan output written to {output_path}")

        # Note: timing stops before any file writes (plan output / timing doc).
        _append_plan_timing_ms(qname, strategy, elapsed_ms)
        print(f"[INFO] Plan generation time (ms): {elapsed_ms:.3f} (recorded in {timing_path})")


# -----------------------------------------------------
# CLI
# -----------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LDBC IC query optimizer using GLogS estimates with relgo/ispg strategies"
    )
    parser.add_argument("--query", action="append", dest="queries", help="Query name to optimize (e.g., ic-1)")
    parser.add_argument(
        "--glogs",
        default=DEFAULT_GLOGS,
        help="Relative path to the GLogS catalog",
    )
    parser.add_argument(
        "--script",
        default=DEFAULT_GLOGS_SCRIPT,
        help="Relative path to the GLogS estimate script",
    )
    parser.add_argument(
        "--json-dir",
        default=DEFAULT_FILTER_DIR,
        help="Query filter JSON directory (relative to repo root)",
    )
    parser.add_argument(
        "--pattern-dir",
        default=DEFAULT_PATTERN_DIR,
        help="Query pattern JSON directory (relative to repo root)",
    )
    parser.add_argument("--cost-scale", type=float, default=0.1, help="Cost scaling factor")
    parser.add_argument(
        "--knows-alpha",
        type=float,
        default=-0.5,
        help=(
            "Apply a power-law correction only for Person_knows_Person: "
            "F_struct *= p_anchor^(alpha*m_knows). "
            "With alpha<0, when anchor selectivity is small, knows-heavy subgraphs are boosted "
            "in estimated frequency/cost."
        ),
    )
    parser.add_argument("--all", action="store_true", help="Generate plans for all queries")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    json_dir = (repo_root / args.json_dir).resolve()
    pattern_dir = (repo_root / args.pattern_dir).resolve()
    if not pattern_dir.exists():
        alt = repo_root / "ispg" / "ldbc" / "query_pattern"
        if alt.exists():
            pattern_dir = alt
    estimator = GLogsEstimator(
        repo_root=repo_root,
        catalog_rel=args.glogs,
        script_rel=args.script,
    )
    schema = load_schema(repo_root)

    strategies: List[str] = ["ispg"]
    knows_alpha = args.knows_alpha

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
            if base.startswith("ic-"):
                parts = base.split("-")
                if len(parts) == 2 and parts[1].isdigit():
                    return (float(int(parts[1])), base)
            return (math.inf, base)

        for path in sorted(json_dir.glob("*_filters.json"), key=query_key):
            add_query(path.stem)

    if not query_order:
        raise SystemExit("Specify at least one query via --query or --all")

    for query_name in query_order:
        run_optimizer(
            query_name=query_name,
            repo_root=repo_root,
            json_dir=json_dir,
            pattern_dir=pattern_dir,
            estimator=estimator,
            cost_scale=args.cost_scale,
            schema=schema,
            strategies=strategies,
            knows_alpha=knows_alpha,
        )


if __name__ == "__main__":
    main()
