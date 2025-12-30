from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ================== Minimal GLogS wrapper ==================

class GLogsEstimator:
    """
        Minimal GLogS wrapper:
        - Uses scripts/glogs/estimate.sh + catalogs/imdb_small/glogs/imdb_small.bincode
            to estimate the frequency for a given pattern JSON, and returns the first
            numeric value (pattern frequency).
    """

    def __init__(
        self,
        repo_root: Path,
        catalog_rel: str = "catalogs/imdb_small/glogs/imdb_small.bincode",
        script_rel: str = "scripts/glogs/estimate.sh",
    ) -> None:
        self.repo_root = repo_root
        self.catalog_path = repo_root / catalog_rel
        self.script_path = repo_root / script_rel

        if not self.catalog_path.exists():
            raise FileNotFoundError(
                f"GLogS catalog not found: {self.catalog_path}\n"
                f"Please ensure this path exists under the ispg repository."
            )
        if not self.script_path.exists():
            raise FileNotFoundError(
                f"GLogS estimate.sh not found: {self.script_path}\n"
                f"Please ensure this path exists under the ispg repository."
            )

    def estimate_pattern_dict(self, pattern: Dict) -> float:
        """
        Write a pattern dict to a temporary JSON file, then invoke estimate.sh.
        Returns the first numeric value from GLogS output (estimated frequency).
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
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
                raise RuntimeError("Empty GLogS output")

            # Accept either "167580,0.000001222" or "167580 0.000001222".
            first_line = stdout.splitlines()[0].strip()
            norm = first_line.replace(",", " ")
            parts = norm.split()
            if not parts:
                raise RuntimeError(f"Unrecognized GLogS output format: {first_line}")
            val = float(parts[0])
            return val

        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"GLogS estimation failed, stderr:\n{e.stderr}"
            ) from e
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


# ================== Plan representation ==================

@dataclass
class EdgeSpec:
    """High-level edge spec used only for IMDB JOB Q1d."""
    idx: int        # Edge index in the pattern JSON
    u_tag: int      # Source vertex tag_id (from q1.json)
    v_tag: int      # Destination vertex tag_id
    etype: str      # Human-readable edge type (for printing)


@dataclass
class PlanStep:
    step_id: int
    op: str               # "FILTER" / "EXPAND" / "AGGREGATE"
    pattern: str
    cost: float
    from_var: Optional[str] = None
    to_var: Optional[str] = None
    detail: str = ""


@dataclass
class Plan:
    root_pattern: str
    root_cost: float
    steps: List[PlanStep]
    total_cost: float
    variant: str = "IMDB_Q1d"


def print_plan(plan: Plan, title: str) -> None:
    print(f"=== {title} ===")
    print(f"  [Variant] {plan.variant}")
    print(f"  Root pattern: {plan.root_pattern}")
    print(f"  Root cost (est.): {plan.root_cost:.4f}")
    print(f"  Total plan cost: {plan.total_cost:.4f}")
    for s in plan.steps:
        if s.op == "VERTEX_SCAN":
            print(
                f"    Step {s.step_id}: op={s.op}, "
                f"pattern={s.pattern}, cost={s.cost:.4f}, detail={s.detail}"
            )
        elif s.op in ("FILTER", "AGGREGATE"):
            # Do not print cost/from/to for FILTER/AGGREGATE.
            print(
                f"    Step {s.step_id}: op={s.op}, "
                f"pattern={s.pattern}, detail={s.detail}"
            )
        else:
            # Other operators (e.g., EXPAND) print full info.
            print(
                f"    Step {s.step_id}: op={s.op}, "
                f"pattern={s.pattern}, cost={s.cost:.4f}, "
                f"from={s.from_var}, to={s.to_var}, detail={s.detail}"
            )


# ================== IMDB JOB Q1d Optimizer (demo) ==================

class IMDBQ1dOptimizer:
    """
        A minimal optimizer for JOB Q1d using GLogS (imdb_small.bincode).
        It performs greedy initialization + Branch-and-Bound search over join/expand order.

        Vertex variable binding (manual):
      tag_id=0 -> t      (title)
      tag_id=1 -> cn     (company_name)
      tag_id=2 -> mi_idx (movie_info_idx / info_type)

        Edge binding (kept consistent with edges order in patterns/job/q1.json):
      edge 0: t -> cn      (title_companies)
      edge 1: t -> mi_idx  (title_infoidx)
    """

    def __init__(self, estimator: GLogsEstimator, repo_root: Path) -> None:
        self.estimator = estimator
        self.repo_root = repo_root

        # Load JOB Q1's GLogS pattern definition.
        q1_json_path = self.repo_root / "patterns" / "job" / "q1.json"
        if not q1_json_path.exists():
            raise FileNotFoundError(
                f"patterns/job/q1.json not found: {q1_json_path}\n"
                f"Please ensure the ispg repository includes JOB q1.json."
            )
        with q1_json_path.open("r", encoding="utf-8") as f:
            self.q1_pattern_full = json.load(f)

        # Vertices/edges JSON (used to build subset patterns).
        self.vertices_json: List[Dict] = self.q1_pattern_full["vertices"]
        self.edges_json: List[Dict] = self.q1_pattern_full["edges"]

        # Manual tag_id -> variable name mapping.
        self.tag_to_var: Dict[int, str] = {
            0: "t",
            1: "cn",
            2: "mi_idx",
        }
        self.var_to_tag: Dict[str, int] = {v: k for k, v in self.tag_to_var.items()}

        # Manual edges_spec (idx must match edges_json order).
        self.edges_spec: List[EdgeSpec] = [
            EdgeSpec(idx=0, u_tag=0, v_tag=1, etype="title_companies"),
            EdgeSpec(idx=1, u_tag=0, v_tag=2, etype="title_infoidx"),
        ]
        self.num_edges: int = len(self.edges_spec)
        if self.num_edges != len(self.edges_json):
            raise ValueError(
                f"edges_spec and q1.json edge count mismatch: {self.num_edges} vs {len(self.edges_json)}"
            )

        # Bitmask for all edges.
        self.full_mask: int = (1 << self.num_edges) - 1

        # Cost scale factor: cost = cost_scale * F_eff(...)
        self.cost_scale: float = 0.1

        # Initialize per-vertex filter text and selectivity.
        self._init_vertex_selectivity()

        # Initialize F_struct({v}) and F_eff({v}), and choose an anchor.
        self.vertex_F_struct: Dict[int, float] = {}
        self.vertex_F_eff: Dict[int, float] = {}
        self._init_vertex_fp_and_anchor()

        # Precompute F_eff(P) and subset_cost for all non-empty edge subsets.
        self.subset_F: Dict[int, float] = {}
        self.subset_cost: Dict[int, float] = {}
        self._init_subset_costs()

    # --------- Build subset pattern JSON ---------

    def _build_pattern_json_for_subset(self, mask: int) -> Dict:
        """
        Given an edge-subset bitmask, build a pattern JSON derived from q1.json.
        - vertices: all src/dst vertices that appear in the selected edges
        - edges: the edges corresponding to the selected idx values
        """
        used_tags: Set[int] = set()
        edges_sel: List[Dict] = []

        for i, e in enumerate(self.edges_json):
            if mask & (1 << i):
                edges_sel.append(e)
                used_tags.add(e["src"])
                used_tags.add(e["dst"])

        vertices_sel = [v for v in self.vertices_json if v["tag_id"] in used_tags]

        return {
            "vertices": vertices_sel,
            "edges": edges_sel,
        }

    def _build_vertex_only_pattern(self, tag_id: int) -> Dict:
        """
        Build a pattern for a single vertex to estimate F_struct({v}).
        """
        vertices_sel = [v for v in self.vertices_json if v["tag_id"] == tag_id]
        return {
            "vertices": vertices_sel,
            "edges": [],
        }

    def _used_tags_for_mask(self, mask: int) -> Set[int]:
        """Return the set of vertex tag_ids that appear in an edge subset mask."""
        used: Set[int] = set()
        for e in self.edges_spec:
            if mask & (1 << e.idx):
                used.add(e.u_tag)
                used.add(e.v_tag)
        return used

    # --------- Vertex selectivity & FILTER text ---------

    def _init_vertex_selectivity(self) -> None:
        """
        Initialize predicate selectivity (per vertex) and its FILTER text.
        - Selectivity is loaded from ispg/imdb/job/q1_filter.json
        - FILTER text is only used to build a human-readable plan
        """
        # FILTER text per vertex (Q1d-specific).
        self.vertex_filter_details: Dict[int, List[str]] = {
            # tag_id=0 -> t (title)
            0: ["FILTER t.production_year > 2000"],
            # tag_id=2 -> mi_idx (movie_info_idx / info_type)
            2: ["FILTER it.info = 'bottom 10 rank'"],
            # tag_id=1 -> cn (company_name / movie_companies)
            1: [
                "FILTER ct.kind = 'production companies'",
                "FILTER mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'",
            ],
        }

        # Default selectivity is 1.0 for all vertices.
        self.vertex_selectivity: Dict[int, float] = {
            tag_id: 1.0 for tag_id in self.tag_to_var.keys()
        }

        # Load selectivity from q1_filter.json if present.
        filter_path = self.repo_root / "ispg" / "imdb" / "job" / "q1_filter.json"
        if not filter_path.exists():
            return

        try:
            with filter_path.open("r", encoding="utf-8") as f:
                sel_data = json.load(f)
        except Exception:
            # Keep defaults on failure.
            return

        s_t = float(sel_data.get("t.production_year > 2000", 1.0))
        s_it = float(sel_data.get("it.info = 'bottom 10 rank'", 1.0))
        s_ct = float(sel_data.get("ct.kind = 'production companies'", 1.0))
        s_mc = float(
            sel_data.get("mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'", 1.0)
        )

        # tag_id: 0 -> t, 1 -> cn, 2 -> mi_idx
        self.vertex_selectivity[0] = s_t
        # cn is affected by both ct and mc; multiply them for simplicity.
        self.vertex_selectivity[1] = s_ct * s_mc
        self.vertex_selectivity[2] = s_it

    def _init_vertex_fp_and_anchor(self) -> None:
        """
                For each vertex v estimate:
                    - F_struct({v}): structural cardinality only
                    - F_eff({v}): F_struct({v}) × s_v
                Then choose the vertex with minimum F_eff as anchor_tag.
        """
        for tag_id in self.tag_to_var.keys():
            pattern_v = self._build_vertex_only_pattern(tag_id)
            F_struct = self.estimator.estimate_pattern_dict(pattern_v)
            F_struct = max(F_struct, 1.0)

            s_v = self.vertex_selectivity.get(tag_id, 1.0)
            F_eff = F_struct * s_v

            self.vertex_F_struct[tag_id] = F_struct
            self.vertex_F_eff[tag_id] = F_eff

        # Choose the vertex with minimum F_eff as anchor.
        self.anchor_tag = min(
            self.vertex_F_eff.items(),
            key=lambda kv: kv[1],
        )[0]

    # --------- Edge-subset F_eff and cost ---------

    def _init_subset_costs(self) -> None:
        """
                For every non-empty edge subset mask precompute:
                    - subset_F[mask]: F_eff(P), i.e., GLogS frequency × vertex selectivities
                    - subset_cost[mask]: per-step cost, approximated as cost_scale * F_eff(P)
        """
        for mask in range(1, 1 << self.num_edges):
            pattern_json = self._build_pattern_json_for_subset(mask)
            F_struct = self.estimator.estimate_pattern_dict(pattern_json)
            F_struct = max(F_struct, 1.0)

            used_tags = self._used_tags_for_mask(mask)
            sel = 1.0
            for tag in used_tags:
                sel *= self.vertex_selectivity.get(tag, 1.0)

            F_eff = F_struct * sel
            self.subset_F[mask] = F_eff
                # ISPG cost: cumulative intermediate result size; scale for readability.
            self.subset_cost[mask] = self.cost_scale * F_eff

            # --------- Greedy + BnB search over edge order ---------

    def _candidate_edges_from_state(
        self,
        mask: int,
        vertices: Set[int],
    ) -> List[int]:
        """Return edges that can connect to current vertices (at least one endpoint is in vertices)."""
        candidates: List[int] = []
        for e in self.edges_spec:
            if mask & (1 << e.idx):
                continue
            if e.u_tag in vertices or e.v_tag in vertices:
                candidates.append(e.idx)
        return candidates

    def greedy_initial(self) -> Tuple[List[int], float]:
        """
        Greedy initialization: start from mask=0 (anchor only), and each step add the edge
        that minimizes subset_cost(new_mask), until all edges are covered.
        Accumulated cost = sum of subset_cost(new_mask) at each step (excluding root cost).
        """
        mask = 0
        vertices: Set[int] = {self.anchor_tag}
        cost_so_far = 0.0
        seq: List[int] = []

        while mask != self.full_mask:
            cand_edges = self._candidate_edges_from_state(mask, vertices)
            if not cand_edges:
                break

            best_edge = None
            best_cost_increase = math.inf
            for e_idx in cand_edges:
                new_mask = mask | (1 << e_idx)
                inc = self.subset_cost[new_mask]
                if inc < best_cost_increase:
                    best_cost_increase = inc
                    best_edge = e_idx

            assert best_edge is not None
            mask |= (1 << best_edge)

            # Update current vertex set.
            e_spec = self.edges_spec[best_edge]
            vertices.add(e_spec.u_tag)
            vertices.add(e_spec.v_tag)

            cost_so_far += best_cost_increase
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
        """
                Branch-and-Bound DFS:
                    - mask: selected-edge bitmask
                    - vertices: currently connected vertex set
                    - cost_so_far: accumulated subset_cost (excluding root_cost)
                    - seq: current edge order
                    - best: {"cost": float, "seq": List[int]}
        """
        if mask == self.full_mask:
            if cost_so_far < best["cost"]:
                best["cost"] = cost_so_far
                best["seq"] = list(seq)
            return

        cand_edges = self._candidate_edges_from_state(mask, vertices)
        if not cand_edges:
            return

        # Optimistic lower bound: the minimum subset_cost among next edges.
        min_next_cost = min(
            self.subset_cost[mask | (1 << e_idx)] for e_idx in cand_edges
        )
        optimistic_lb = cost_so_far + min_next_cost
        if optimistic_lb >= best["cost"]:
            return

        for e_idx in cand_edges:
            new_mask = mask | (1 << e_idx)
            new_vertices = set(vertices)
            e_spec = self.edges_spec[e_idx]
            new_vertices.add(e_spec.u_tag)
            new_vertices.add(e_spec.v_tag)

            new_cost = cost_so_far + self.subset_cost[new_mask]
            seq.append(e_idx)
            self._bnb_dfs(new_mask, new_vertices, new_cost, seq, best)
            seq.pop()

    def search_best_plan_ops(self) -> Tuple[List[int], float, List[int], float]:
        """
                Returns both:
                    - greedy_initial() result (greedy edge order & edge-only cost)
                    - Branch-and-Bound best result (best edge order & edge-only cost)
                Note: returned costs do NOT include root cost; add root_cost separately.
        """
        greedy_seq, greedy_cost_edges = self.greedy_initial()

        best: Dict[str, object] = {
            "cost": float("inf"),
            "seq": list(greedy_seq),
        }

        self._bnb_dfs(
            mask=0,
            vertices={self.anchor_tag},
            cost_so_far=0.0,
            seq=[],
            best=best,
        )
        best_seq: List[int] = best["seq"]  # type: ignore
        best_cost_edges: float = float(best["cost"])
        return greedy_seq, greedy_cost_edges, best_seq, best_cost_edges

    # --------- Convert edge order to a readable plan ---------

    def build_plan_from_seq(
        self,
        seq: List[int],
        root_cost: float,
        edge_cost_total: float,
    ) -> Plan:
        """
                Build a readable plan from an edge order:
                    - Apply FILTER on the anchor vertex first
                    - Then EXPAND according to seq; after each expansion apply FILTER on newly introduced vertices
                    - Finally apply AGGREGATE
        root_cost: F_eff({anchor}) * cost_scale
                edge_cost_total: sum of subset_cost(new_mask) across steps
        """
        steps: List[PlanStep] = []
        step_id = 1

        visited_tags: Set[int] = {self.anchor_tag}
        anchor_var = self.tag_to_var[self.anchor_tag]

        # Step: anchor VERTEX_SCAN (explicitly charged as root_cost)
        steps.append(
            PlanStep(
                step_id=step_id,
                op="VERTEX_SCAN",
                pattern=f"IMDB_Q1d_anchor[{anchor_var}]",
                cost=root_cost,
                from_var=None,
                to_var=anchor_var,
                detail=f"Scan anchor vertex {anchor_var}",
            )
        )
        step_id += 1

        # Step: anchor FILTER
        anchor_filters = self.vertex_filter_details.get(self.anchor_tag, [])
        for detail in anchor_filters:
            steps.append(
                PlanStep(
                    step_id=step_id,
                    op="FILTER",
                    pattern=f"IMDB_Q1d_anchor[{anchor_var}]",
                    cost=0.0,
                    from_var=None,
                    to_var=None,
                    detail=detail,
                )
            )
            step_id += 1

        # EXPAND + FILTER on newly introduced vertices
        mask = 0
        for edge_idx in seq:
            mask |= (1 << edge_idx)
            e_spec = self.edges_spec[edge_idx]
            src_tag = e_spec.u_tag
            dst_tag = e_spec.v_tag
            src_var = self.tag_to_var[src_tag]
            dst_var = self.tag_to_var[dst_tag]

            edge_ids = [str(i) for i in range(self.num_edges) if mask & (1 << i)]
            pattern_name = f"IMDB_Q1d_Eset[{','.join(edge_ids)}]"

            steps.append(
                PlanStep(
                    step_id=step_id,
                    op="EXPAND",
                    pattern=pattern_name,
                    cost=self.subset_cost[mask],
                    from_var=src_var,
                    to_var=dst_var,
                    detail=f"Expand {src_var}->{dst_var} ({e_spec.etype})",
                )
            )
            step_id += 1

            new_tags: List[int] = []
            for tag in (src_tag, dst_tag):
                if tag not in visited_tags:
                    visited_tags.add(tag)
                    new_tags.append(tag)

            for tag in new_tags:
                # Anchor filters have already been applied; handle other vertices only.
                if tag == self.anchor_tag:
                    continue
                filter_details = self.vertex_filter_details.get(tag, [])
                for detail in filter_details:
                    steps.append(
                        PlanStep(
                            step_id=step_id,
                            op="FILTER",
                            pattern=pattern_name,
                            cost=0.0,
                            from_var=None,
                            to_var=None,
                            detail=detail,
                        )
                    )
                    step_id += 1

        steps.append(
            PlanStep(
                step_id=step_id,
                op="AGGREGATE",
                pattern="IMDB_Q1d_Eset[all]",
                cost=0.0,
                from_var=None,
                to_var=None,
                detail=(
                    "AGGREGATE MIN(mc.note) AS production_note, "
                    "MIN(t.title) AS movie_title, "
                    "MIN(t.production_year) AS movie_year"
                ),
            )
        )

        total_cost = root_cost + edge_cost_total

        plan = Plan(
            root_pattern=f"IMDB_Q1d_anchor[{anchor_var}]",
            root_cost=root_cost,
            steps=steps,
            total_cost=total_cost,
            variant="IMDB_Q1d",
        )
        return plan


# ================== Demo entry ==================

def demo_imdb_q1d() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    estimator = GLogsEstimator(
        repo_root=repo_root,
        catalog_rel="catalogs/imdb_small/glogs/imdb_small.bincode",
        script_rel="scripts/glogs/estimate.sh",
    )
    optimizer = IMDBQ1dOptimizer(estimator=estimator, repo_root=repo_root)

    # Print per-vertex FP after applying selectivity.
    print("[INFO] Vertex effective F values (after selectivity):")
    for tag, F_eff in optimizer.vertex_F_eff.items():
        vname = optimizer.tag_to_var[tag]
        F_struct = optimizer.vertex_F_struct[tag]
        sel = optimizer.vertex_selectivity.get(tag, 1.0)
        print(
            f"  tag_id={tag}, var={vname}, "
            f"F_struct={F_struct:.4f}, sel={sel:.6f}, F_eff={F_eff:.4f}"
        )
    anchor_var = optimizer.tag_to_var[optimizer.anchor_tag]
    print(f"[INFO] Chosen anchor vertex: tag_id={optimizer.anchor_tag}, var={anchor_var}")

    # root_cost = cost_scale * F_eff({anchor})
    root_F_eff = optimizer.vertex_F_eff[optimizer.anchor_tag]
    root_cost = optimizer.cost_scale * root_F_eff
    print(f"[INFO] Root effective cost (anchor scan): {root_cost:.4f}\n")

    greedy_seq, greedy_cost_edges, best_seq, best_cost_edges = optimizer.search_best_plan_ops()

    greedy_plan = optimizer.build_plan_from_seq(greedy_seq, root_cost, greedy_cost_edges)
    best_plan = optimizer.build_plan_from_seq(best_seq, root_cost, best_cost_edges)

    print_plan(greedy_plan, "GreedyInitial plan on IMDB JOB Q1d (imdb_small)")
    print()
    print_plan(best_plan, "Branch-and-Bound best plan on IMDB JOB Q1d (imdb_small)")

    print("\n[INFO] Single-edge subset F values for Q1d (on imdb_small):")
    for e in optimizer.edges_spec:
        mask = 1 << e.idx
        F = optimizer.subset_F[mask]
        print(f"  edge_idx={e.idx}, etype={e.etype}, F={F:.4f}")


if __name__ == "__main__":
    demo_imdb_q1d()
