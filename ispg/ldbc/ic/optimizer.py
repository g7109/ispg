"""ISPG Plan Optimizer — Algorithm 1 (§5.5).

Bottom-up DP over covered variable sets.  Plans are trees (bushy).

  §5.2  APU and predicate-conditioned frequency F(U)
  §5.3  Per-operator cost model
  §5.5  Algorithm 1

Queries with VarExpand (is_var_expand=True) are rejected.
Run gen_fixed_hop_subqueries.py first to expand them into fixed-hop variants.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional, Tuple

from ispg.core.estimator import GLogsEstimator, SchemaInfo
from ispg.ldbc.ic.plan import EdgeCheckInfo, EdgeInfo, PlanNode, VertexInfo

# ── Cost model α coefficients (§5.3) ─────────────────────────────────────────
ALPHA_SRC  = 1.0   # Scan / Get  : α_src  × F(Ut)
ALPHA_EXP  = 1.0   # Expand      : α_exp  × F(Ut)  [= α_exp × F(Us) × σ_e(Θ)]
ALPHA_CHK  = 0.1   # EdgeCheck   : α_chk  × F(Us)
# Join / Merge: α_join × F(Us), "charged on the state it reads" (§V-C). For the
# binary Merge the state read is both inputs, so this is α_join × (F(U1)+F(U2)).
ALPHA_JOIN = 1.0


class ISPGOptimizer:
    """Bottom-up DP plan optimizer — Algorithm 1 (§5.5)."""

    def __init__(
        self,
        query_name:  str,
        filter_json: Dict,
        schema:      SchemaInfo,
        estimator:   GLogsEstimator,
        cost_scale:  float = 0.1,
    ) -> None:
        self.query_name = query_name
        self.schema     = schema
        self.estimator  = estimator
        self.cost_scale = cost_scale

        self.vertices: Dict[str, VertexInfo] = {}
        self.edges:    List[EdgeInfo]        = []
        self._F_cache: Dict[Tuple, float]    = {}

        self._ingest(filter_json)

        if not self.vertices:
            raise ValueError(f"{query_name}: no vertices in filter JSON")
        if not self.edges:
            raise ValueError(f"{query_name}: no edges — cannot build a plan")

        var_edges = [e for e in filter_json.get("edges", []) if e.get("is_var_expand")]
        if var_edges:
            raise ValueError(
                f"{query_name}: contains VarExpand edges. "
                "Run gen_fixed_hop_subqueries.py and use the -k variants "
                "(e.g. ic-1-1, ic-1-2, ic-1-3)."
            )

        self.all_aliases: FrozenSet[str] = frozenset(self.vertices)
        self._singleton_F: Dict[str, float] = {
            a: self._glog_single(v) for a, v in self.vertices.items()
        }

    # ── ingestion ─────────────────────────────────────────────────────────────

    def _ingest(self, filt: Dict) -> None:
        alias_data: Dict[str, Dict] = filt.get("aliases", {})

        for v in filt.get("vertices", []):
            alias    = v["alias"]
            if alias in self.vertices:
                # Two distinct vertices sharing one alias would be silently
                # overwritten in this dict, dropping a vertex and mis-binding
                # identity edges. Fail loudly instead (see ic-9-2 alias 'm').
                raise ValueError(
                    f"duplicate vertex alias '{alias}' in filter JSON "
                    f"(labels '{self.vertices[alias].label}' vs "
                    f"'{v.get('label')}'); regenerate the sub-query with "
                    "gen_fixed_hop_subqueries.py"
                )
            info     = alias_data.get(alias, {})
            combined = info.get("combined") or {}
            sel      = float(combined.get("selectivity", 1.0) or 1.0)
            filters  = [
                f["expression"] for f in (info.get("filters") or [])
                if f.get("expression")
            ]
            label    = v.get("label", alias)
            # A label not registered as a graph entity is a non-graph relation
            # R' (Def 2); it carries a fanout instead of a GLogS estimate.
            # LDBC IC has only graph entities, so is_relation is always False.
            is_rel   = label not in self.schema.entity_name_to_id
            fanout   = float(combined.get("fanout", 1.0) or 1.0) if is_rel else 1.0
            self.vertices[alias] = VertexInfo(
                alias=alias,
                tag_id=v["tag_id"],
                label=label,
                label_id=v.get("label_id", 0),
                domain=v.get("domain", "match"),
                selectivity=sel,
                filters=filters,
                is_relation=is_rel,
                fanout=fanout,
            )

        for idx, e in enumerate(filt.get("edges", [])):
            src = e.get("source_alias", "")
            dst = e.get("target_alias", "")
            if src not in self.vertices or dst not in self.vertices:
                continue

            src_tag = e.get("source_tag", self.vertices[src].tag_id)
            dst_tag = e.get("target_tag", self.vertices[dst].tag_id)

            # Swap src/dst for GLogS if query direction ≠ schema direction
            sc_src  = e.get("schema_source_label", "")
            sc_dst  = e.get("schema_target_label", "")
            src_lbl = self.vertices[src].label
            dst_lbl = self.vertices[dst].label
            est_src, est_dst = src_tag, dst_tag
            if sc_src and sc_dst and src_lbl and dst_lbl:
                if dst_lbl == sc_src and src_lbl == sc_dst:
                    est_src, est_dst = dst_tag, src_tag

            # Domain
            origin  = e.get("origin", "")
            e_alias = e.get("alias")
            if e_alias and e_alias in alias_data:
                domain = alias_data[e_alias].get("domain", "sql")
            elif "match" in origin:
                domain = "match"
            else:
                domain = "sql"

            # Edge selectivity
            e_sel = 1.0
            if e_alias and e_alias in alias_data:
                e_sel = float(
                    (alias_data[e_alias].get("combined") or {}).get("selectivity", 1.0) or 1.0
                )

            self.edges.append(EdgeInfo(
                idx=idx,
                src_alias=src, dst_alias=dst,
                src_tag=src_tag, dst_tag=dst_tag,
                est_src_tag=est_src, est_dst_tag=est_dst,
                relation_label=e.get("relation_label", ""),
                relation_id=e.get("relation_id"),
                domain=domain,
                is_identity=bool(e.get("is_identity", False)),
                selectivity=e_sel,
            ))

    # ── APU frequency estimation (§5.2) ──────────────────────────────────────

    def _glog_single(self, v: VertexInfo) -> float:
        if v.is_relation:
            # Non-graph relation R': frequency carried by its fanout (Def 3),
            # with no GLogS structural estimate. (Inert on LDBC.)
            return max(v.fanout, 1.0) * v.selectivity
        pattern = {"vertices": [{"tag_id": 0, "label_id": v.label_id}], "edges": []}
        return max(self.estimator.estimate_pattern(pattern), 1.0) * v.selectivity

    def _struct_F(
        self, covered: FrozenSet[str], edges: List[EdgeInfo]
    ) -> float:
        """GLogS structural frequency F(p') of the sub-pattern formed by the
        vertices in *covered* and the given *edges* (identity edges and edges
        with no relation_id are excluded from the GLogS pattern; §3.3 eq 3.2).

        Non-graph relations R' and any edge touching one are excluded: they have
        no graph structure and contribute through fanout in _F_with_edges (Def
        3), not through GLogS. On LDBC every vertex is a graph entity, so this
        filtering is a no-op there."""
        verts  = [
            self.vertices[a] for a in covered
            if not self.vertices[a].is_relation
        ]
        closed = [
            e for e in edges
            if not e.is_identity
            and not self.vertices[e.src_alias].is_relation
            and not self.vertices[e.dst_alias].is_relation
        ]
        if not verts:
            return 1.0

        cache_key = (
            frozenset(v.tag_id for v in verts),
            frozenset((e.est_src_tag, e.est_dst_tag, e.relation_id) for e in closed),
        )
        if cache_key not in self._F_cache:
            sorted_tags = sorted({v.tag_id for v in verts})
            tmap = {t: i for i, t in enumerate(sorted_tags)}
            gv   = [{"tag_id": tmap[v.tag_id], "label_id": v.label_id} for v in verts]
            ge   = [
                {
                    "tag_id":  e.idx,
                    "src":     tmap[e.est_src_tag],
                    "dst":     tmap[e.est_dst_tag],
                    "label_id": e.relation_id,
                }
                for e in closed
                if e.relation_id is not None
                and e.est_src_tag in tmap
                and e.est_dst_tag in tmap
            ]
            self._F_cache[cache_key] = max(
                self.estimator.estimate_pattern({"vertices": gv, "edges": ge}), 1.0
            )
        return self._F_cache[cache_key]

    def _F_with_edges(
        self, covered: FrozenSet[str], edges: List[EdgeInfo]
    ) -> float:
        """F(U) = F(p') × ∏ sel(θv|ℓ) × ∏ sel(θe|ℓ) × ∏ fo(R'j)  (Def 3).

        F(p') is the GLogS structural frequency of the graph vertices; each
        non-graph relation R' in *covered* contributes its fanout fo(R') on the
        same footing as a vertex-expansion factor. Only the predicates of the
        supplied *edges* are applied, so the caller may measure either a
        fully-closed sub-pattern or a single-edge expansion (σ_e of §5.4)."""
        F = self._struct_F(covered, edges)
        for a in covered:
            v = self.vertices[a]
            F *= v.selectivity
            if v.is_relation:
                F *= v.fanout          # Def 3 fanout factor (inert on LDBC)
        for e in edges:
            if not e.is_identity:
                F *= e.selectivity
        return F

    def _closed_edges(self, covered: FrozenSet[str]) -> List[EdgeInfo]:
        """Declared edges of P̂ whose both endpoints lie in *covered*."""
        return [
            e for e in self.edges
            if e.src_alias in covered and e.dst_alias in covered
            and not e.is_identity
        ]

    def _estimate_F(self, covered: FrozenSet[str]) -> float:
        """F(U) over the sub-pattern induced on *covered*: all its vertices and
        every declared edge of P̂ closed among them (§5.2)."""
        if len(covered) == 1:
            return self._singleton_F[next(iter(covered))]
        return self._F_with_edges(covered, self._closed_edges(covered))

    # ── Cost formulas (§5.3) ──────────────────────────────────────────────────

    def _c_source(self, F_out: float) -> float:
        return self.cost_scale * ALPHA_SRC * F_out

    def _c_expand(self, F_out: float) -> float:
        return self.cost_scale * ALPHA_EXP * F_out

    def _c_merge(self, F1: float, F2: float) -> float:
        return self.cost_scale * ALPHA_JOIN * (F1 + F2)

    def _c_expand_int(
        self, F_main: float, F_in: float, n_checks: int
    ) -> float:
        """ExpandInt cost (§5.4): a main Expand reading the σ of its edge plus
        one constant-time EdgeCheck per remaining closed edge.

            α_exp · F_main + α_chk · F_in · n_checks

        where F_main = F(Us)·σ_main is the single-edge expansion frequency and
        F_in = F(Us) is the input-state frequency.  With n_checks = 0 this is
        exactly the single-edge Expand cost, so acyclic plans are unchanged."""
        return self.cost_scale * (
            ALPHA_EXP * F_main + ALPHA_CHK * F_in * n_checks
        )

    # ── Candidate extensions ──────────────────────────────────────────────────

    def _expansions(
        self, S: FrozenSet[str]
    ) -> Dict[str, List[EdgeInfo]]:
        """Map each new vertex reachable from S in one step to *every* edge
        connecting it to S.  Multiple such edges mean the new vertex closes a
        cycle and is bound by an ExpandInt (§5.4) rather than a plain Expand."""
        groups: Dict[str, List[EdgeInfo]] = {}
        for e in self.edges:
            if e.src_alias in S and e.dst_alias not in S:
                groups.setdefault(e.dst_alias, []).append(e)
            elif e.dst_alias in S and e.src_alias not in S:
                groups.setdefault(e.src_alias, []).append(e)
        return groups

    # ── Algorithm 1 ──────────────────────────────────────────────────────────

    def optimize(self) -> Optional[PlanNode]:
        """Bottom-up DP — Algorithm 1 (§5.5).

        M maps each covered set S to the cheapest PlanNode that produces it.
        We grow from singletons, each round trying:
          (a) Unary extension via Expand / Identity.
          (b) Binary Merge of two disjoint subsets.
        """
        M: Dict[FrozenSet[str], PlanNode] = {}

        # Step 2 — singletons: source operators
        for alias, v in self.vertices.items():
            S = frozenset({alias})
            F = self._singleton_F[alias]
            op = "SCAN" if v.domain == "match" else "GET"
            c  = self._c_source(F)
            M[S] = PlanNode(
                op=op, covered=S, F=F, op_cost=c, total_cost=c,
                detail=f"{alias} ({v.label})", to_alias=alias,
            )

        # Steps 3–10 — grow by increasing size
        for size in range(2, len(self.all_aliases) + 1):

            # (a) Unary extension — bind one new vertex, closing every P̂-edge
            #     between it and S_prev within one ExpandInt (§5.4).
            for S_prev in [S for S in M if len(S) == size - 1]:
                prev = M[S_prev]
                base_edges = self._closed_edges(S_prev)
                for new_alias, edges in self._expansions(S_prev).items():
                    S_new = S_prev | {new_alias}
                    if not S_new.issubset(self.all_aliases):
                        continue

                    F_new   = self._estimate_F(S_new)
                    nonid   = [e for e in edges if not e.is_identity]
                    idedges = [e for e in edges if e.is_identity]

                    if idedges:
                        # A key-equality bridge introduces the vertex for free
                        # (§3.3); every other edge is closed by an EdgeCheck.
                        main      = idedges[0]
                        nonid_chk = nonid
                        op_label  = "IDENTITY"
                        op_cost   = (
                            self.cost_scale * ALPHA_CHK * prev.F * len(nonid_chk)
                        )
                        detail    = (
                            f"IDENTITY::{main.src_alias}<->{main.dst_alias}"
                        )
                        closed_edges = idedges[1:] + nonid
                    else:
                        # Pick the min-σ edge as the navigating Expand (§5.6
                        # min-degree ordering); close the rest with EdgeCheck.
                        f_single = {
                            id(e): self._F_with_edges(S_new, base_edges + [e])
                            for e in nonid
                        }
                        main         = min(nonid, key=lambda e: f_single[id(e)])
                        rest         = [e for e in nonid if e is not main]
                        op_label     = "EXPAND"
                        op_cost      = self._c_expand_int(
                            f_single[id(main)], prev.F, len(rest)
                        )
                        detail       = f"{main.domain.upper()}::{main.relation_label}"
                        closed_edges = rest

                    # A declared edge of P̂ (relation mapped in the graph
                    # schema) is traversed by Expand even when written on the
                    # SPJ side; a relation with no such mapping is a Join (§2.2).
                    is_declared = (
                        main.relation_id is not None
                        and main.relation_id in self.schema.relation_id_to_name
                    )
                    is_join = (op_label == "EXPAND") and not is_declared

                    total = prev.total_cost + op_cost
                    if S_new not in M or total < M[S_new].total_cost:
                        from_a = (
                            main.src_alias
                            if new_alias == main.dst_alias
                            else main.dst_alias
                        )
                        checks = [
                            EdgeCheckInfo(
                                e.src_alias, e.dst_alias,
                                e.relation_label, e.is_identity,
                            )
                            for e in closed_edges
                        ]
                        M[S_new] = PlanNode(
                            op=op_label, covered=S_new, F=F_new,
                            op_cost=op_cost, total_cost=total, detail=detail,
                            from_alias=from_a, to_alias=new_alias,
                            edge_label=main.relation_label,
                            is_join=is_join,
                            edge_checks=checks,
                            children=[prev],
                        )

            # (b) Binary Merge: all disjoint (S1, S2) with |S1|+|S2| = size
            for k in range(1, size // 2 + 1):
                lefts  = [S for S in M if len(S) == k]
                rights = [S for S in M if len(S) == size - k]
                for S1 in lefts:
                    for S2 in rights:
                        if S1 & S2:
                            continue
                        S_new = S1 | S2
                        if not S_new.issubset(self.all_aliases):
                            continue
                        n1, n2 = M[S1], M[S2]
                        F_new  = self._estimate_F(S_new)
                        mc     = self._c_merge(n1.F, n2.F)
                        total  = n1.total_cost + n2.total_cost + mc
                        detail = (
                            f"MERGE {{{','.join(sorted(S1))}}} "
                            f"⋈ {{{','.join(sorted(S2))}}}"
                        )
                        if S_new not in M or total < M[S_new].total_cost:
                            M[S_new] = PlanNode(
                                op="MERGE", covered=S_new, F=F_new,
                                op_cost=mc, total_cost=total, detail=detail,
                                children=[n1, n2],
                            )

        return M.get(self.all_aliases)
