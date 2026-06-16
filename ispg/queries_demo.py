"""Demo queries: a few IC variants that place the person anchor on the SPJ side (Get entry).

Same style as queries.py, but registered into a separate DEMO_REGISTRY; it does not
reference or modify the main REGISTRY and does not affect the paper's experiments.
A vertex with declared_in="SPJ" enters via Get (read its vertex relation on the relational
side) as the plan's starting point, demonstrating plans that "begin on the SPJ side".

Usage (same as the main queries):
    from queries_demo import DEMO_REGISTRY
    plan = Optimizer(Stats()).optimize(DEMO_REGISTRY["ic2-get"])
"""
from __future__ import annotations

from ir import Edge, Relation, SPJMQuery, Vertex

DEMO_REGISTRY: dict[str, SPJMQuery] = {}

# ---- predicate constants (taken from real sf1 values) ----
ID = 933
CD = 1300000000000
WF = 2010


def Vx(var, label, pred=None, din="MATCH"):
    return Vertex(var, label, din, None, pred or [])


def Ed(label, src, dst, din="MATCH", pred=None, ptbl=None):
    return Edge(label, label, src, dst, din, pred or [], ptbl)


def Rel(var, label, parent, fanout_table, by="src", fixed=None, ptbl=None, pred=None):
    return Relation(var, label, parent=parent, fanout_table=fanout_table, fanout_by=by,
                    fanout_fixed=fixed, pred_table=ptbl, predicates=pred or [])


def Q(name, vertices, edges, relations=None, proj=None):
    q = SPJMQuery(name=name, vertices={v.var: v for v in vertices}, edges=edges,
                  relations={r.var: r for r in (relations or [])}, projection=proj or [])
    DEMO_REGISTRY[name] = q
    return q


# ===== IC2 variant: friends' comments -- anchor p1 placed on the SPJ side (Get) =====
Q("ic2-get",
  [Vx("p1", "PERSON", [("id", "=", ID)], din="SPJ"),
   Vx("p2", "PERSON"),
   Vx("c", "COMMENT", [("creationDate", "<", CD)])],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "c", "p2")],
  proj=["p2.id", "c.creationDate"])

# ===== IC7 variant: friends who liked my message (triangle) -- p1 on SPJ side (Get), closing edge still SPJ =====
Q("ic7-get",
  [Vx("p1", "PERSON", [("id", "=", ID)], din="SPJ"),
   Vx("p2", "PERSON"),
   Vx("c", "MESSAGE")],
  [Ed("KNOWS", "p1", "p2"), Ed("LIKES", "p2", "c"),
   Ed("HASCREATOR", "c", "p1", din="SPJ")],
  proj=["p2.id", "c.content"])

# ===== IC9 variant: friends' recent comments -- p1 on SPJ side (Get) =====
Q("ic9-get",
  [Vx("p1", "PERSON", [("id", "=", ID)], din="SPJ"),
   Vx("p2", "PERSON"),
   Vx("c", "COMMENT", [("creationDate", "<", CD)])],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "c", "p2")],
  proj=["p2.firstName", "c.creationDate"])

# ===== Fig. 4 style: a non-graph relation R' as the plan's starting point (Get(R') -> Resolve the parent vertex) =====
# triangle: p1-KNOWS->p2-KNOWS->p3 is the MATCH path; p1-KNOWS->p3 is the SPJ closing edge (executed as
# EdgeCheck, the paper's Follows); p1 carries a relation c with a strongly selective predicate (the paper's
# filtered Orders). p1 has no fixed id, so the most selective side (relation c) gets a chance to be the root
# and drive the plan -- verifying that the SPJ-rooted, R'-rooted plan Get(c)->Resolve(p1)->Expand is in the
# search space.
Q("fig4-relroot",
  [Vx("p1", "PERSON"), Vx("p2", "PERSON"), Vx("p3", "PERSON")],
  [Ed("KNOWS", "p1", "p2"), Ed("KNOWS", "p2", "p3"), Ed("KNOWS", "p1", "p3", din="SPJ")],
  relations=[Rel("c", "Comment", parent="p1", fanout_table="comment_hasCreator_person",
                 by="dst", ptbl="comment", pred=[("creationDate", "<", 1104537600000)])],  # before 2005, strongly selective
  proj=["p2.id", "p3.id"])


# ===== IC11 variant: friends' employment -- p1 on SPJ side (Get) =====
Q("ic11-get",
  [Vx("p1", "PERSON", [("id", "=", ID)], din="SPJ"),
   Vx("p2", "PERSON"),
   Vx("o", "ORGANISATION"), Vx("pl", "PLACE")],
  [Ed("KNOWS", "p1", "p2"),
   Ed("WORKAT", "p2", "o", pred=[("workFrom", "<", WF)], ptbl="person_workAt_organisation"),
   Ed("ISLOCATEDIN", "o", "pl")],
  proj=["p2.id", "o.name"])
