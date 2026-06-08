"""Plan data structures and rendering for ISPG tree-shaped plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ispg.ldbc.ic.optimizer import ISPGOptimizer


@dataclass
class VertexInfo:
    alias:       str
    tag_id:      int
    label:       str
    label_id:    int
    domain:      str    # "match" | "sql"
    selectivity: float  # sel(Θ | ℓ)
    filters:     List[str]


@dataclass
class EdgeInfo:
    idx:            int
    src_alias:      str
    dst_alias:      str
    src_tag:        int
    dst_tag:        int
    est_src_tag:    int   # corrected for GLogS schema direction
    est_dst_tag:    int
    relation_label: str
    relation_id:    Optional[int]
    domain:         str   # "match" | "sql"
    is_identity:    bool  # zero-cost key-equality bridge
    selectivity:    float


@dataclass
class EdgeCheckInfo:
    """A declared edge closed inside the matching by an EdgeCheck (§5.4)."""
    from_alias:     str
    to_alias:       str
    relation_label: str
    is_identity:    bool


@dataclass
class PlanNode:
    """One node in the interleaved SPJM plan tree (§2.3)."""
    op:         str                   # SCAN GET EXPAND IDENTITY MERGE
    covered:    FrozenSet[str]        # aliases whose columns are in dom(I)
    F:          float                 # |I| ≈ F(U)
    op_cost:    float                 # cost of this operator
    total_cost: float                 # cumulative cost from root to here
    detail:     str
    from_alias: Optional[str] = None
    to_alias:   Optional[str] = None
    edge_label: Optional[str] = None
    # True when this unary op introduces a non-declared relation (Ω_r Join,
    # §2.2) rather than traversing a declared edge of P̂ (Expand). Declared
    # edges stay Expand even when written on the SPJ side — that is the ISPG
    # interleaving (§3.3); only a relation with no key-mapping is a Join.
    is_join:    bool = False
    # Edges closed inside the matching by this operator (§5.4 ExpandInt).
    # Each entry is (from_alias, to_alias, relation_label, is_identity); the
    # operator binds `to_alias` via a single Expand and closes every remaining
    # edge with an EdgeCheck against already-bound endpoints.
    edge_checks: List["EdgeCheckInfo"] = field(default_factory=list)
    children:   List["PlanNode"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_binary(self) -> bool:
        return len(self.children) == 2


# ── Rendering ─────────────────────────────────────────────────────────────────
#
# The optimizer keeps a small internal op enum (SCAN/GET/EXPAND/IDENTITY/MERGE);
# rendering maps it to the operator names of the paper's Table 2.1 so the output
# reads in the algebra of §2.2 / §5.4:
#   SCAN→Scan  GET→Get  MERGE→Merge  Select  Join  Expand  ExpandInt  EdgeCheck  π_A
# Mapping rules:
#   EXPAND with is_join          → Join       (Ω_r: a relation with no key-mapping)
#   EXPAND with edge_checks       → ExpandInt  (§5.4: main Expand + closed EdgeChecks)
#   EXPAND otherwise              → Expand
#   IDENTITY                      → Select     (§3.3 key equality x.id = y.id)


def _op_display(node: PlanNode) -> str:
    if node.op == "SCAN":
        return "Scan"
    if node.op == "GET":
        return "Get"
    if node.op == "MERGE":
        return "Merge"
    if node.op == "IDENTITY":
        return "Select"
    if node.op == "EXPAND":
        if node.is_join:
            return "Join"
        if node.edge_checks:
            return "ExpandInt"
        return "Expand"
    return node.op


def _check_str(ec: "EdgeCheckInfo") -> str:
    """One closed edge of an ExpandInt: an identity edge is a key-equality
    Select, any other declared edge is an EdgeCheck (§5.4)."""
    if ec.is_identity:
        return f"Select {ec.from_alias}.id={ec.to_alias}.id"
    return f"EdgeCheck {ec.from_alias}->{ec.to_alias} ({ec.relation_label})"


def plan_steps(root: PlanNode, opt: "ISPGOptimizer") -> List[str]:
    """Linearise the plan tree in execution order (children before parents),
    naming each operator as in the paper (Table 2.1).

    Select steps for vertex predicates are emitted right after the operator
    that introduces the vertex.
    """
    lines: List[str] = []
    step = [1]

    def emit(text: str) -> None:
        lines.append(f"    Step {step[0]}: {text}")
        step[0] += 1

    def emit_filters(node: PlanNode, cov: str) -> None:
        if node.to_alias and node.to_alias in opt.vertices:
            for fexpr in opt.vertices[node.to_alias].filters:
                emit(f"op=Select, state={cov}, detail={node.to_alias}: {fexpr}")

    def visit(node: PlanNode) -> None:
        for child in node.children:
            visit(child)

        qn  = opt.query_name
        cov = f"{qn}_Cov[{','.join(sorted(node.covered))}]"
        disp = _op_display(node)

        if node.op in ("SCAN", "GET"):
            emit(
                f"op={disp}, state={cov}, F={node.F:.6f}, "
                f"op_cost={node.op_cost:.6f}, detail={node.detail}"
            )
            emit_filters(node, cov)

        elif node.op == "IDENTITY":
            # Same vertex bound under two aliases — a key-equality Select (§3.3).
            emit(
                f"op=Select, state={cov}, F={node.F:.6f}, "
                f"op_cost={node.op_cost:.6f}, "
                f"detail={node.from_alias}.id = {node.to_alias}.id (identity)"
            )
            for ec in node.edge_checks:
                if ec.is_identity:
                    emit(
                        f"op=Select, state={cov}, "
                        f"detail={ec.from_alias}.id = {ec.to_alias}.id (identity)"
                    )
                else:
                    emit(
                        f"op=EdgeCheck, state={cov}, "
                        f"from={ec.from_alias}, to={ec.to_alias}, "
                        f"detail=close {ec.from_alias}->{ec.to_alias} "
                        f"({ec.relation_label})"
                    )
            emit_filters(node, cov)

        elif node.op == "EXPAND":
            if node.edge_checks:
                # ExpandInt (§5.4 Def 5.3): one navigating Expand fused with the
                # EdgeChecks that close the remaining edges onto the new vertex.
                closed = "; ".join(_check_str(ec) for ec in node.edge_checks)
                emit(
                    f"op=ExpandInt, state={cov}, F={node.F:.6f}, "
                    f"op_cost={node.op_cost:.6f}, "
                    f"from={node.from_alias}, to={node.to_alias}, "
                    f"detail=Expand {node.from_alias}->{node.to_alias} "
                    f"({node.edge_label}); {closed}"
                )
            else:
                emit(
                    f"op={disp}, state={cov}, F={node.F:.6f}, "
                    f"op_cost={node.op_cost:.6f}, "
                    f"from={node.from_alias}, to={node.to_alias}, "
                    f"detail={node.detail}"
                )
            emit_filters(node, cov)

        elif node.op == "MERGE":
            emit(
                f"op=Merge, state={cov}, F={node.F:.6f}, "
                f"op_cost={node.op_cost:.6f}, detail={node.detail}"
            )

        else:
            emit(
                f"op={disp}, state={cov}, F={node.F:.6f}, "
                f"op_cost={node.op_cost:.6f}, detail={node.detail}"
            )

    visit(root)
    qn = opt.query_name
    emit(
        f"op=π_A, state={qn}_Cov[all], F=0.000000, op_cost=0.000000, "
        f"detail=final projection π_A (refer to original SQL for aggregation/ordering)"
    )
    return lines


def plan_tree_str(node: PlanNode, indent: int = 0) -> List[str]:
    """ASCII tree view for visual inspection, using paper operator names."""
    lines: List[str] = []
    pad = "  " * indent
    disp = _op_display(node)
    if node.is_binary:
        lines.append(
            f"{pad}{disp}  F={node.F:.4f}  cumcost={node.total_cost:.4f}"
        )
        lines.append(f"{pad}├─ LEFT:")
        lines.extend(plan_tree_str(node.children[0], indent + 1))
        lines.append(f"{pad}└─ RIGHT:")
        lines.extend(plan_tree_str(node.children[1], indent + 1))
    else:
        if node.op == "IDENTITY":
            body = f"{disp}({node.from_alias}.id={node.to_alias}.id)"
        elif node.op in ("SCAN", "GET"):
            body = f"{disp}({node.detail})"
        else:
            body = f"{disp}({node.edge_label or node.detail})"
        closes = ""
        if node.op == "EXPAND" and node.edge_checks:
            closed = ",".join(
                f"{ec.from_alias}->{ec.to_alias}" for ec in node.edge_checks
            )
            closes = f"  closes[{closed}]"
        lines.append(
            f"{pad}{body}{closes}  "
            f"F={node.F:.4f}  cumcost={node.total_cost:.4f}"
        )
        if node.children:
            lines.extend(plan_tree_str(node.children[0], indent + 1))
    return lines
