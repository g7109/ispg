"""SPJM intermediate representation (IR).

A query = vertices + declared edges (P-hat) + SPJ relation tables (R') + projection.
Each element carries declared_in: "MATCH" | "SPJ" -- the renderer uses this to draw
circles/squares, and to draw EdgeCheck edges as dashed lines.
"""
from __future__ import annotations

from dataclasses import dataclass, field

Pred = tuple[str, str, object]   # (column, operator, value); operator like '=', '<', '>'


@dataclass
class Vertex:
    var: str
    label: str
    declared_in: str = "MATCH"
    table_for_pred: str | None = None      # table to evaluate predicate selectivity on (default = label's table)
    predicates: list[Pred] = field(default_factory=list)


@dataclass
class Edge:
    var: str                # edge variable (may be anonymous)
    label: str              # e.g. KNOWS / HASCREATOR
    src: str                # source vertex variable (as written in the pattern)
    dst: str                # target vertex variable
    declared_in: str = "MATCH"   # SPJ + both endpoints bound => EdgeCheck (drawn dashed)
    predicates: list[Pred] = field(default_factory=list)   # edge-attribute predicates
    pred_table: str | None = None   # table holding edge-attribute predicates (the edge table)


@dataclass
class Relation:
    """An SPJ-side relation table R' (square). Attached to a parent (a vertex or another
    relation) through the key-mapping / a join."""
    var: str
    label: str                  # display name, e.g. Comment / Organisation / Place
    parent: str                 # the variable it attaches to (a vertex or relation)
    fanout_table: str | None = None   # edge table used to compute fanout (alternative to fanout_fixed)
    fanout_by: str = "src"      # 'src' | 'dst'
    fanout_fixed: float | None = None  # given directly when fanout=1 (e.g. a PK join)
    declared_in: str = "SPJ"
    pred_table: str | None = None
    predicates: list[Pred] = field(default_factory=list)


@dataclass
class SPJMQuery:
    name: str
    vertices: dict[str, Vertex]
    edges: list[Edge]
    relations: dict[str, Relation] = field(default_factory=dict)
    projection: list[str] = field(default_factory=list)
    params: dict[str, object] = field(default_factory=dict)   # concrete values for $Id etc.

    # --- derived ---
    def induced_edges(self, varset: set[str]) -> list[Edge]:
        return [e for e in self.edges if e.src in varset and e.dst in varset]

    def connected(self, varset) -> bool:
        """Whether the subset forms a connected subpattern (vertices joined by declared
        edges; relations attached to their parent through the key-mapping). An APU must be
        connected (paper Def. 2): no isolated vertex/table allowed."""
        S = set(varset)
        if len(S) <= 1:
            return True
        adj = {v: set() for v in S}
        for e in self.edges:
            if e.src in S and e.dst in S:
                adj[e.src].add(e.dst)
                adj[e.dst].add(e.src)
        for r in S:
            if r in self.relations:
                p = self.relations[r].parent
                if p in S:
                    adj[r].add(p)
                    adj[p].add(r)
        seen, stack = set(), [next(iter(S))]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(adj[x] - seen)
        return seen == S

    def edges_touching(self, var: str, bound: set[str]) -> list[Edge]:
        """Declared edges between `var` and already-bound vertices (used for Expand
        connectivity / cycle-closing detection)."""
        out = []
        for e in self.edges:
            if e.src == var and e.dst in bound:
                out.append(e)
            elif e.dst == var and e.src in bound:
                out.append(e)
        return out
