"""ISPG plan optimizer.

Cost-based, bottom-up search over covered sets in the unified "graph operator +
relational operator" space (paper Alg. 1):
  - source operators : Scan (a vertex, graph side) or Get (a vertex's relation, or a
                       non-graph relation R', relational side) -- a plan may start on
                       either side;
  - Expand           : pull in a new vertex along a MATCH edge;
  - EdgeCheck        : close an edge (MATCH or SPJ) once both endpoints are bound
                       (the SPJ case = the paper's Follows edge);
  - Join             : attach a relation R' once its parent is bound (contributes fanout);
  - Resolve          : key-mapping a relation source back to its parent vertex (Fig. 4);
  - Merge            : combine two independently built subplans (bushy plans).
Each state S has a frequency freq(S) = the frequency of its sub-APU (structural F x
predicate sel x relation fanout), independent of the path that reaches it. Cost =
sum over operators of alpha * freq; DP keeps the minimum. Produces a plan tree, rendered
as text by render_ascii().
"""
from __future__ import annotations

from ir import SPJMQuery
from stats import VLABEL2TABLE, Stats

# Tunable; join >> expand (cf. GLogS). scan/get are equal by default -- the entry side is
# chosen by the DP on cost (paper Sec. V-A: whether the first source is a graph-side Scan
# or a relational-side Get is itself a cost choice in the search space); raise/lower `get`
# to make the entry side actually differ. resolve = key-mapping resolution (Fig. 4).
ALPHA = {"src": 1.0, "scan": 1.0, "get": 1.0, "resolve": 1.0,
         "exp": 1.0, "check": 0.5, "join": 6.0}


class Optimizer:
    def __init__(self, stats: Stats):
        self.st = stats
        self._freq_cache: dict[frozenset, float] = {}

    # ---------- sub-APU frequency (pure function, cached) ----------
    def freq(self, q: SPJMQuery, S: frozenset, use_sel: bool = True) -> float:
        """Sub-APU frequency. use_sel=True is ISPG (with predicate selectivity);
        use_sel=False is the RelGo baseline (plain GLogS structural cost + relation
        fanout, ignoring predicate selectivity)."""
        key = (S, use_sel)
        if key in self._freq_cache:
            return self._freq_cache[key]
        Vs = [v for v in S if v in q.vertices]
        Rs = [r for r in S if r in q.relations]
        var_label = {v: q.vertices[v].label for v in Vs}
        induced = []
        for e in q.edges:
            if e.src in Vs and e.dst in Vs:
                tbl = self.st.resolve_edge(e.label, q.vertices[e.src].label, q.vertices[e.dst].label)
                induced.append((e.src, e.dst, tbl))
        F = self.st.structural_freq(var_label, induced)
        if use_sel:
            for v in Vs:                               # vertex predicates
                vx = q.vertices[v]
                if not vx.predicates:
                    continue
                tbl = vx.table_for_pred or VLABEL2TABLE[vx.label.upper()]
                for (col, op, val) in vx.predicates:
                    F *= self.st.selectivity(tbl, col, op, val)
            for e in q.edges:                          # edge-attribute predicates of closed edges
                if e.src in Vs and e.dst in Vs and e.predicates:
                    for (col, op, val) in e.predicates:
                        F *= self.st.selectivity(e.pred_table, col, op, val)
        for r in Rs:                                   # relation fanout (structural) + predicates (ISPG only)
            rel = q.relations[r]
            fo = rel.fanout_fixed if rel.fanout_fixed is not None \
                else self.st.fanout(rel.fanout_table, rel.fanout_by)
            F *= fo
            if use_sel:
                for (col, op, val) in rel.predicates:
                    F *= self.st.selectivity(rel.pred_table, col, op, val)
        self._freq_cache[key] = F
        return F

    def _rel_source_freq(self, q: SPJMQuery, r: str, use_sel: bool = True) -> float:
        """Frequency of a non-graph relation R' used as a source operator (Get). Treat it
        as the state "attached to parent, but with parent projected away":
        F = F(parent vertex) * fo(R') * sel(R'). Hence after Resolve binds the parent back,
        freq({R',parent}) equals what the Scan(parent)+Join(R') path yields (path
        independence, see optimize()). Meaningful only when parent is a vertex (the
        key-mapping resolves to a vertex)."""
        rel = q.relations[r]
        f = self.freq(q, frozenset({rel.parent}), use_sel)        # F(parent) * sel(parent predicates)
        fo = rel.fanout_fixed if rel.fanout_fixed is not None \
            else self.st.fanout(rel.fanout_table, rel.fanout_by)
        f *= fo
        if use_sel:
            for (col, op, val) in rel.predicates:
                f *= self.st.selectivity(rel.pred_table, col, op, val)
        return f

    # ---------- successor generation ----------
    def _successors(self, q: SPJMQuery, S: frozenset):
        """Yield (newS, op); op carries type/params/closing-edges for rebuild and costing."""
        Vbound = {v for v in S if v in q.vertices}
        # Expand: introduce a new vertex along a MATCH edge
        for e in q.edges:
            if e.declared_in != "MATCH":
                continue
            new = None
            if e.src in Vbound and e.dst not in S and e.dst in q.vertices:
                new, frm = e.dst, e.src
            elif e.dst in Vbound and e.src not in S and e.src in q.vertices:
                new, frm = e.src, e.dst
            if new is None:
                continue
            S2 = S | {new}
            # after introducing `new`, other edges between `new` and bound vertices => EdgeCheck
            closing = [ce for ce in q.edges if ce is not e
                       and ((ce.src == new and ce.dst in Vbound)
                            or (ce.dst == new and ce.src in Vbound))]
            yield frozenset(S2), {"type": "Expand", "edge": e, "from": frm,
                                  "new": new, "closing": closing}
        # Join: relation whose parent is already bound
        for r, rel in q.relations.items():
            if r not in S and rel.parent in S:
                yield frozenset(S | {r}), {"type": "Join", "rel": rel}
        # Resolve: after a relation is used as source, key-mapping binds its parent vertex
        # (paper identity (2), Fig. 4). In normal flow a relation is Join-ed only after its
        # parent is bound, so this branch fires only on a relation-rooted {r} state.
        for r in S:
            if r in q.relations:
                rel = q.relations[r]
                if rel.parent in q.vertices and rel.parent not in S:
                    yield frozenset(S | {rel.parent}), {"type": "Resolve", "rel": rel, "new": rel.parent}

    def _step_cost(self, q: SPJMQuery, S2: frozenset, op: dict) -> float:
        f = self.freq(q, S2)
        if op["type"] == "Expand":
            c = ALPHA["exp"] * f
            c += ALPHA["check"] * f * len(op["closing"])
            return c
        if op["type"] == "Join":
            return ALPHA["join"] * f
        if op["type"] == "Resolve":               # key-mapping: one lookup per row, count unchanged
            return ALPHA["resolve"] * f
        return f

    # ---------- DP (bottom-up over covered sets; full tree search space incl. Merge, Alg. 1) ----------
    def optimize(self, q: SPJMQuery) -> dict:
        """Find the least-cost subplan for each covered set S. Two kinds of successor:
          - unary extension (Expand/Join/EdgeCheck/Resolve): grow one accumulating state
            -> linear plan;
          - binary Merge: combine two independently built, disjoint, jointly-connected
            subplans -> bushy plan.
        Both are in the search space (search-space completeness); bushy plans are usually
        excluded by the high Merge cost, but are still enumerated and compared, not excluded
        from the space."""
        target = frozenset(set(q.vertices) | set(q.relations))
        n = len(target)
        best: dict[frozenset, float] = {}
        back: dict[frozenset, tuple] = {}
        self._merge_considered = 0          # diagnostic: number of Merge candidates enumerated

        # size 1: each vertex enumerates BOTH entry sides: Scan (graph side, bind a vertex
        # by label) and Get (relational side, read the vertex's relation); the DP keeps the
        # cheaper one (paper Sec. V-A: the entry side is itself a cost choice in the search
        # space, not a fixed annotation). On a tie, declared_in breaks it (SPJ->Get, else
        # Scan), preserving the entry side of existing queries/demos.
        for v in q.vertices:
            S = frozenset({v})
            f = self.freq(q, S)
            scan_c, get_c = ALPHA["scan"] * f, ALPHA["get"] * f
            if get_c < scan_c or (get_c == scan_c and q.vertices[v].declared_in == "SPJ"):
                best[S] = get_c
                back[S] = ("scan", {"type": "Get", "vertex": v})
            else:
                best[S] = scan_c
                back[S] = ("scan", {"type": "Scan", "vertex": v})
        # size 1: a non-graph relation R' as a source operator -- the paper's Get(Orders,2024)
        # in Fig. 4: read the strongly selective relation first, then resolve its parent vertex
        # via the key-mapping (Resolve). Only resolvable when the parent is a vertex.
        for r, rel in q.relations.items():
            if rel.parent in q.vertices:
                S = frozenset({r})
                best[S] = ALPHA["get"] * self._rel_source_freq(q, r)
                back[S] = ("rel_src", {"type": "Get", "rel": rel})

        for size in range(2, n + 1):
            # (a) unary extension: grow a size-1 subplan by one vertex/relation
            for Sp in [s for s in best if len(s) == size - 1]:
                base = best[Sp]
                for S2, op in self._successors(q, Sp):
                    if len(S2) != size:
                        continue
                    nc = base + self._step_cost(q, S2, op)
                    if nc < best.get(S2, float("inf")):
                        best[S2] = nc
                        back[S2] = ("unary", Sp, op)
            # (b) binary Merge: combine two disjoint, already-solved, jointly-connected subplans
            for k in range(1, size // 2 + 1):
                lefts = [s for s in best if len(s) == k]
                rights = [s for s in best if len(s) == size - k]
                for S1 in lefts:
                    for S2 in rights:
                        if S1 & S2:
                            continue
                        S = S1 | S2
                        if len(S) != size or not q.connected(S):
                            continue
                        self._merge_considered += 1
                        mc = ALPHA["join"] * (self.freq(q, S1) + self.freq(q, S2))
                        nc = best[S1] + best[S2] + mc
                        if nc < best.get(S, float("inf")):
                            best[S] = nc
                            back[S] = ("merge", S1, S2, mc)

        if target not in best:
            raise RuntimeError(f"cannot cover all variables: {target}")
        return self._build_plan(q, target, best, back)

    # ---------- greedy polynomial-time optimizer (Alg. 2) ----------
    def optimize_greedy(self, q: SPJMQuery) -> dict:
        """Greedy variant over the same interleaved space (paper Alg. 2). Starting from the
        least-cost source operator, at each step it commits to the applicable operator
        (Expand/Join/EdgeCheck/Resolve) of least added cost, considering a Merge with a
        subplan grown over the remaining variables when no unary extension applies, until
        all variables of Q are covered -- committing to each choice without reconsidering it.
        Each of the at most q steps considers O(q) applicable operators, so it runs in time
        polynomial in q. Its plan is well-formed and computes the same answer as optimize(),
        drawn from the same space, but is not guaranteed least-cost."""
        target = frozenset(set(q.vertices) | set(q.relations))
        best: dict[frozenset, float] = {}
        back: dict[frozenset, tuple] = {}

        def source_candidates(allowed: set):
            cs = []
            for v in q.vertices:
                if v not in allowed:
                    continue
                f = self.freq(q, frozenset({v}))
                op = "Get" if q.vertices[v].declared_in == "SPJ" else "Scan"
                a = ALPHA["get"] if op == "Get" else ALPHA["scan"]
                cs.append((a * f, frozenset({v}), ("scan", {"type": op, "vertex": v})))
            for r, rel in q.relations.items():
                if r in allowed and rel.parent in q.vertices:
                    cs.append((ALPHA["get"] * self._rel_source_freq(q, r), frozenset({r}),
                               ("rel_src", {"type": "Get", "rel": rel})))
            return cs

        def grow(seed: frozenset, cost: float, entry: tuple, allowed: set) -> frozenset:
            """Greedily extend `seed` within `allowed` by least-added-cost unary operators."""
            best[seed] = cost
            back[seed] = entry
            S = seed
            while True:
                choice = None                      # (added_cost, S2, op)
                for S2, op in self._successors(q, S):
                    if S2 in best or not S2 <= allowed:
                        continue
                    c = self._step_cost(q, S2, op)
                    if choice is None or c < choice[0]:
                        choice = (c, S2, op)
                if choice is None:
                    return S
                c, S2, op = choice
                best[S2] = best[S] + c
                back[S2] = ("unary", S, op)
                S = S2

        # line 1: start from the least-cost source operator
        c0, s0, e0 = min(source_candidates(set(target)), key=lambda x: x[0])
        S = grow(s0, c0, e0, set(target))
        # lines 7-8: while unary extension stalled, Merge with a subplan greedily grown over
        # the remaining variables (only reached when the rest is a separate component).
        while S != target:
            rest = set(target - S)
            cands = source_candidates(rest)
            if not cands:
                raise RuntimeError(f"greedy: cannot cover {set(target) - set(S)}")
            c1, s1, e1 = min(cands, key=lambda x: x[0])
            sub = grow(s1, c1, e1, rest)
            merged = S | sub
            if not q.connected(merged):
                raise RuntimeError("greedy: disconnected remainder")
            mc = ALPHA["join"] * (self.freq(q, S) + self.freq(q, sub))
            best[merged] = best[S] + best[sub] + mc
            back[merged] = ("merge", S, sub, mc)
            S = merged

        plan = self._build_plan(q, target, best, back)
        plan["query"] = q.name + " [Greedy]"
        plan["strategy"] = "greedy"
        return plan

    # ---------- RelGo baseline (optimize MATCH on the graph, SPJ on relations; fixed boundary, no interleaving) ----------
    def optimize_relgo(self, q: SPJMQuery) -> dict:
        """RelGo-style baseline (after the RelGo paper, Sec. 4.2):
          (1) graph optimization: fully optimize the MATCH component (declared_in=MATCH
              vertices/edges) with GLogS; FilterIntoMatchRule pushes MATCH-side predicates
              down (freq includes selectivity); cycles inside MATCH use EdgeCheck
              (EXPAND_INTERSECT) -- this part is identical to ISPG's MATCH part.
          (2) relational optimization: once MATCH is wrapped as SCAN_GRAPH_TABLE, an SPJ
              declared edge can only be a post-hoc binary Join and a relation R' a post-hoc
              Join, fixed after MATCH, never interleaved, never driving MATCH.
        So RelGo and ISPG differ only in how SPJ elements are handled: RelGo joins after the
        fact, ISPG interleaves / uses EdgeCheck; on pure-MATCH queries the two plans coincide."""
        gv = frozenset(q.vertices)
        best: dict[frozenset, float] = {}
        back: dict[frozenset, tuple] = {}
        for v in q.vertices:
            S = frozenset({v})
            best[S] = ALPHA["src"] * self.freq(q, S)          # includes predicates (FilterIntoMatch)
            back[S] = ("scan", {"type": "Scan", "vertex": v})
        for size in range(2, len(gv) + 1):
            for Sp in [s for s in best if len(s) == size - 1]:
                Vb = set(Sp)
                for e in q.edges:
                    if e.declared_in != "MATCH":
                        continue
                    new = frm = None
                    if e.src in Vb and e.dst not in Sp and e.dst in q.vertices:
                        new, frm = e.dst, e.src
                    elif e.dst in Vb and e.src not in Sp and e.src in q.vertices:
                        new, frm = e.src, e.dst
                    if new is None:
                        continue
                    S2 = Sp | {new}
                    # a cycle closed inside MATCH -> EdgeCheck (EXPAND_INTERSECT, worst-case optimal)
                    closing = [ce for ce in q.edges if ce is not e and ce.declared_in == "MATCH"
                               and ((ce.src == new and ce.dst in Vb) or (ce.dst == new and ce.src in Vb))]
                    fc = self.freq(q, S2)
                    c = best[Sp] + ALPHA["exp"] * fc + ALPHA["check"] * fc * len(closing)
                    if c < best.get(S2, float("inf")):
                        best[S2] = c
                        back[S2] = ("unary", Sp, {"type": "Expand", "edge": e,
                                                  "from": frm, "new": new, "closing": closing})
        if gv not in best:
            raise RuntimeError(f"relgo: MATCH part cannot cover graph vertices {gv}")

        plan = self._build_plan(q, gv, best, back)             # MATCH subplan (with predicates)
        tree, steps, cost = plan["tree"], plan["steps"], best[gv]
        idc = [len(steps)]

        def nid():
            idc[0] += 1
            return "r" + str(idc[0])

        cur = set(gv)
        for e in q.edges:                              # SPJ declared edge -> post-hoc binary Join (not EdgeCheck)
            if e.declared_in != "SPJ":
                continue
            jf = self.freq(q, frozenset(cur))
            jc = ALPHA["join"] * jf
            cost += jc
            lf = {"id": nid(), "kind": "leaf", "title": "Edge", "detail": e.label,
                  "var": None, "freq": round(jf, 3), "declared_in": "SPJ", "children": []}
            tree = {"id": nid(), "kind": "join", "title": "Join",
                    "detail": f"{e.src}-[{e.label}]-{e.dst}", "freq": round(jf, 3),
                    "step_cost": round(jc, 3), "declared_in": "SPJ", "children": [tree, lf]}
            steps.append(_node("Join", f"{e.src}-[{e.label}]-{e.dst}", frozenset(cur), jf, jc, "SPJ", "square"))
        for r in q.relations:                          # relation R' -> post-hoc Join (typical relational optimization)
            cur.add(r)
            rel = q.relations[r]
            jf = self.freq(q, frozenset(cur))
            jc = ALPHA["join"] * jf
            cost += jc
            lf = {"id": nid(), "kind": "leaf", "title": "Scan", "detail": f"{r}:{rel.label}",
                  "var": r, "freq": round(jf, 3), "declared_in": "SPJ", "children": []}
            tree = {"id": nid(), "kind": "join", "title": "Join", "detail": rel.label,
                    "freq": round(jf, 3), "step_cost": round(jc, 3), "declared_in": "SPJ",
                    "children": [tree, lf]}
            steps.append(_node("Join", f"{r}:{rel.label} |><| {rel.parent}", frozenset(cur), jf, jc, "SPJ", "square"))

        cum = 0.0
        for nd in steps:
            cum += nd["step_cost"]
            nd["cum_cost"] = round(cum, 2)
        return {"query": q.name + " [RelGo]", "total_cost": round(cost, 2),
                "steps": steps, "tree": tree, "strategy": "relgo"}

    # graph structure of the sub-APU for a covered set
    def apu_structure(self, q: SPJMQuery, S) -> dict:
        S = set(S)
        Vs = [v for v in S if v in q.vertices]
        verts = [{"var": v, "label": q.vertices[v].label, "shape": "circle",
                  "declared_in": q.vertices[v].declared_in,
                  "pred": _pred_str(q.vertices[v].predicates)} for v in sorted(Vs)]
        eds = [{"src": e.src, "dst": e.dst, "label": e.label, "declared_in": e.declared_in}
               for e in q.edges if e.src in S and e.dst in S]
        rels = [{"var": r, "label": q.relations[r].label, "parent": q.relations[r].parent,
                 "shape": "square", "pred": _pred_str(q.relations[r].predicates)}
                for r in sorted(S) if r in q.relations]
        return {"vertices": verts, "edges": eds, "relations": rels}

    # ---------- rebuild plan (recursively from `back`; supports the Merge binary tree) ----------
    def _build_plan(self, q: SPJMQuery, target, best, back, use_sel: bool = True) -> dict:
        nodes = []          # flat steps (post-order; for ASCII/debug)
        idc = [0]

        def nid():
            idc[0] += 1
            return "b" + str(idc[0])

        def leaf(title, detail, freq, declared_in, var):
            return {"id": nid(), "kind": "leaf", "title": title, "detail": detail, "var": var,
                    "freq": round(freq, 3), "declared_in": declared_in, "children": []}

        def comb(kind, title, detail, freq, cost, declared_in, children, edge=None):
            node = {"id": nid(), "kind": kind, "title": title, "detail": detail, "freq": round(freq, 3),
                    "step_cost": round(cost, 3), "declared_in": declared_in, "children": children}
            if edge is not None:
                node["edge"] = edge
            return node

        def vdetail(var, vx):
            p = _pred_str(vx.predicates)
            return f"{var} . {p}" if p else f"{var}:{vx.label}"

        def build(S):
            f = self.freq(q, S, use_sel)
            entry = back[S]
            kind = entry[0]
            if kind == "scan":
                op = entry[1]; v = op["vertex"]; vx = q.vertices[v]
                title = op["type"]                       # "Scan" (graph side) | "Get" (relational side)
                shape = "square" if title == "Get" else "circle"
                acost = ALPHA["get"] if title == "Get" else ALPHA["scan"]
                din = "SPJ" if title == "Get" else vx.declared_in
                node = leaf(title, vdetail(v, vx), f, din, v)
                nodes.append(_node(title, f"{v}:{vx.label}", S, f, acost * f, din, shape))
                return node
            if kind == "rel_src":                        # non-graph relation as source (Get) -- Fig. 4 entry
                rel = entry[1]["rel"]
                f = self._rel_source_freq(q, rel.var, use_sel)
                p = _pred_str(rel.predicates)
                ld = f"{rel.var}:{rel.label} . {p}" if p else f"{rel.var}:{rel.label}"
                node = leaf("Get", ld, f, "SPJ", rel.var)
                nodes.append(_node("Get", ld, S, f, ALPHA["get"] * f, "SPJ", "square"))
                return node
            if kind == "merge":
                _, S1, S2, mc = entry
                left, right = build(S1), build(S2)
                detail = f"{{{','.join(sorted(S1))}}} |><| {{{','.join(sorted(S2))}}}"
                node = comb("merge", "Merge", detail, f, mc, "SPJ", [left, right])
                nodes.append(_node("Merge", detail, S, f, mc, "SPJ", "square"))
                return node
            # kind == "unary"
            _, Sp, op = entry
            child = build(Sp)
            if op["type"] == "Resolve":              # key-mapping: resolve the parent vertex from a relation source
                rel = op["rel"]; new = op["new"]
                running = comb("join", "Resolve", f"{rel.var}.{rel.fanout_by} -> {new} (key-mapping)",
                               f, ALPHA["resolve"] * f, "SPJ", [child])
                nodes.append(_node("Resolve", f"{rel.var} -> {new}", S, f, ALPHA["resolve"] * f, "SPJ", "circle"))
                return running
            if op["type"] == "Expand":
                e = op["edge"]; new = op["new"]; vx = q.vertices[new]
                lf = leaf("Scan", vdetail(new, vx), self.freq(q, frozenset({new}), use_sel), vx.declared_in, new)
                running = comb("join", "Expand", f"{e.label} -> {new}", f, ALPHA["exp"] * f, "MATCH", [child, lf])
                nodes.append(_node("Expand", f"{op['from']}-[{e.label}]->{new}", S, f, ALPHA["exp"] * f, "MATCH", "circle"))
                for ce in op["closing"]:                 # closing edge => EdgeCheck
                    running = comb("check", "EdgeCheck", f"{ce.src} -[{ce.label}]- {ce.dst}", f, ALPHA["check"] * f,
                                   ce.declared_in, [running],
                                   edge={"src": ce.src, "dst": ce.dst, "label": ce.label, "declared_in": ce.declared_in})
                    nodes.append(_node("EdgeCheck", f"{ce.src}-[{ce.label}]-{ce.dst}", S, f, ALPHA["check"] * f, ce.declared_in, "edge"))
                return running
            # op["type"] == "Join"
            rel = op["rel"]
            fo = rel.fanout_fixed if rel.fanout_fixed is not None else self.st.fanout(rel.fanout_table, rel.fanout_by)
            p = _pred_str(rel.predicates)
            ld = f"{rel.var}:{rel.label} . {p}" if p else f"{rel.var}:{rel.label}"
            lf = leaf("Scan", ld, fo, "SPJ", rel.var)
            running = comb("join", "Join", rel.label, f, ALPHA["join"] * f, "SPJ", [child, lf])
            nodes.append(_node("Join", f"{rel.var}:{rel.label} |><| {rel.parent}", S, f, ALPHA["join"] * f, "SPJ", "square"))
            return running

        tree = build(target)
        cum = 0.0
        for nd in nodes:
            cum += nd["step_cost"]
            nd["cum_cost"] = round(cum, 2)
        return {"query": q.name, "total_cost": round(best[target], 2),
                "steps": nodes, "tree": tree,
                "merge_considered": getattr(self, "_merge_considered", 0)}


def _fmt_val(v):
    if isinstance(v, str):
        return f"'{v}'"
    if isinstance(v, int) and v > 10 ** 11:        # epoch ms -> date, to avoid overlong numbers
        import datetime
        return datetime.datetime.utcfromtimestamp(v / 1000).strftime("%Y-%m-%d")
    return str(v)


def _pred_str(preds):
    if not preds:
        return ""
    c, o, v = preds[0]
    return f"{c}{o}{_fmt_val(v)}"


def _node(op, args, S, freq, step_cost, declared_in, shape):
    return {"op": op, "args": args, "apu": sorted(S), "freq": round(freq, 3),
            "step_cost": round(step_cost, 3), "declared_in": declared_in, "shape": shape}


def render_ascii(plan: dict) -> str:
    out = [f"=== {plan['query']}  total_cost={plan['total_cost']} ==="]
    for i, n in enumerate(plan["steps"]):
        tag = {"circle": "(o)", "square": "[#]", "edge": "---"}.get(n["shape"], "   ")
        dash = "  (SPJ, dashed)" if n["declared_in"] == "SPJ" else ""
        out.append(f"  {i+1:>2}. {tag} {n['op']:<10} {n['args']:<34} "
                   f"F={n['freq']:>12,.2f}  step={n['step_cost']:>10,.2f}  cum={n['cum_cost']:>10,.2f}{dash}")
    return "\n".join(out)


if __name__ == "__main__":
    from queries import REGISTRY

    st = Stats()
    opt = Optimizer(st)
    for name in ["ic7-1", "ic9-1", "ic11-1", "ic5-1"]:
        opt._freq_cache.clear()
        plan = opt.optimize(REGISTRY[name])
        print(render_ascii(plan))
        print()
