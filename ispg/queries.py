"""Registry of pre-encoded ISPG SPJM queries (LDBC SNB Interactive Complex).

Partitioning principle (boundary taken from the older LDBC compiler's MATCH / outer-JOIN
split, semantics simplified per the newer spec, and constrained to the paper's SPJM scope
-- inner joins / cycle-closing EdgeCheck / relation tables R'; no anti-joins/aggregation):
  - a cycle-closing edge (both graph endpoints bound) -> an Edge with declared_in="SPJ",
    executed as EdgeCheck;
  - a leaf entity (strongly selective predicate, no cycle) -> a relation table R',
    executed as Join (contributes fanout);
  - the main path/tree -> stays in MATCH (Expand).
VarExpand (knows*1..k) is split into fixed-hop subqueries: one for 1 hop, one for 2 hops, ...
IC-10 is not split in the paper; treated as a single hop (only one KNOWS), so no ic10-2.
"""
from __future__ import annotations

from ir import Edge, Relation, SPJMQuery, Vertex

REGISTRY: dict[str, SPJMQuery] = {}

# ---- predicate constants (taken from real sf1 values, to avoid zero selectivity) ----
ID = 933                          # person.id
FN = "John"                       # firstName
CD = 1300000000000                # creationDate <  (-> 2011-03-13)
CDLO, CDHI = 1262304000000, 1300000000000   # creationDate range
JD = 1300000000000                # joinDate >=
WF = 2010                         # workFrom <
N1, N2 = "India", "China"         # place.name (country)
TAG = "Gabriela_Sabatini"         # tag.name
TCN = "Athlete"                   # tagclass.name
CDR = [("creationDate", ">=", CDLO), ("creationDate", "<", CDHI)]


# ---- shorthand helpers ----
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
    REGISTRY[name] = q
    return q


# helper: a friend's location (person->place, fanout=1) as R'
def LocOf(parent, name=None):
    return Rel("pl", "Place", parent=parent, fanout_table="person_isLocatedIn_place",
               by="src", ptbl="place", pred=[("name", "=", name)] if name else [])


# ===================== IC1: location of friends (k hops) -- isLocatedIn as SPJ (R') =====================
# MATCH: friend path; SPJ: p2's location pl as a relation table (older outer LEFT JOIN person_isLocatedIn_place)
Q("ic1-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON", [("firstName", "=", FN)])],
  [Ed("KNOWS", "p1", "p2")],
  relations=[LocOf("p2")], proj=["p2.id", "pl.name"])

Q("ic1-2",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("p2", "PERSON", [("firstName", "=", FN)])],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "p2")],
  relations=[LocOf("p2")], proj=["p2.id", "pl.name"])

Q("ic1-3",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("pb", "PERSON"),
   Vx("p2", "PERSON", [("firstName", "=", FN)])],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "pb"), Ed("KNOWS", "pb", "p2")],
  relations=[LocOf("p2")], proj=["p2.id", "pl.name"])

# ===================== IC2: friends' comments (by date) -- pure MATCH (older version had no outer JOIN) =====================
Q("ic2-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"),
   Vx("c", "COMMENT", [("creationDate", "<", CD)])],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "c", "p2")],
  proj=["p2.id", "c.creationDate"])

# ===================== IC3: friends who commented in two countries -- place (country) as SPJ (R') =====================
# MATCH: friend + two comments; SPJ: each comment's country pl1/pl2 as a relation table (older outer place-hierarchy JOIN)
Q("ic3-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"),
   Vx("c1", "COMMENT", CDR), Vx("c2", "COMMENT", CDR)],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "c1", "p2"), Ed("HASCREATOR", "c2", "p2")],
  relations=[Rel("pl1", "Place", "c1", "comment_isLocatedIn_place", ptbl="place", pred=[("name", "=", N1)]),
             Rel("pl2", "Place", "c2", "comment_isLocatedIn_place", ptbl="place", pred=[("name", "=", N2)])],
  proj=["p2.id"])

Q("ic3-2",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("p2", "PERSON"),
   Vx("c1", "COMMENT", CDR), Vx("c2", "COMMENT", CDR)],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "p2"),
   Ed("HASCREATOR", "c1", "p2"), Ed("HASCREATOR", "c2", "p2")],
  relations=[Rel("pl1", "Place", "c1", "comment_isLocatedIn_place", ptbl="place", pred=[("name", "=", N1)]),
             Rel("pl2", "Place", "c2", "comment_isLocatedIn_place", ptbl="place", pred=[("name", "=", N2)])],
  proj=["p2.id"])

# ===================== IC4: tags of friends' new posts -- pure MATCH (older anti-join exceeds SPJM scope, dropped) =====================
Q("ic4-1",
  [Vx("pa", "PERSON"), Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"),
   Vx("ps", "POST", CDR), Vx("t", "TAG")],
  [Ed("KNOWS", "pa", "p1"), Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "ps", "p2"), Ed("HASTAG", "ps", "t")],
  proj=["t.name"])

# ===================== IC5: forums (their posts) that friends joined -- hasMember cycle-closing SPJ EdgeCheck =====================
# cycle: p2 created post m, forum f contains m, and f's member is p2 (closing hasMember, with joinDate)
Q("ic5-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"), Vx("f", "FORUM"), Vx("m", "POST")],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "m", "p2"), Ed("CONTAINEROF", "f", "m"),
   Ed("HASMEMBER", "f", "p2", din="SPJ", pred=[("joinDate", ">=", JD)], ptbl="forum_hasMember_person")],
  proj=["f.title"])

Q("ic5-2",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("p2", "PERSON"),
   Vx("f", "FORUM"), Vx("m", "POST")],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "p2"), Ed("HASCREATOR", "m", "p2"),
   Ed("CONTAINEROF", "f", "m"),
   Ed("HASMEMBER", "f", "p2", din="SPJ", pred=[("joinDate", ">=", JD)], ptbl="forum_hasMember_person")],
  proj=["f.title"])

# ===================== IC6: tags co-occurring with a given tag -- given tag as SPJ (R') =====================
# MATCH: friend + post + co-occurring tag t2; SPJ: the post also carries the given tag t_given (strongly selective name predicate)
Q("ic6-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"), Vx("m", "POST"),
   Vx("t2", "TAG", [("name", "<>", TAG)])],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "m", "p2"), Ed("HASTAG", "m", "t2")],
  relations=[Rel("tg", "Tag", "m", "post_hasTag_tag", ptbl="tag", pred=[("name", "=", TAG)])],
  proj=["t2.name"])

Q("ic6-2",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("p2", "PERSON"), Vx("m", "POST"),
   Vx("t2", "TAG", [("name", "<>", TAG)])],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "p2"), Ed("HASCREATOR", "m", "p2"), Ed("HASTAG", "m", "t2")],
  relations=[Rel("tg", "Tag", "m", "post_hasTag_tag", ptbl="tag", pred=[("name", "=", TAG)])],
  proj=["t2.name"])

# ===================== IC7: friends who liked my message -- hasCreator cycle-closing SPJ EdgeCheck =====================
# triangle: I (p1) know p2, p2 likes message c, c was created by me (p1) (closing hasCreator)
Q("ic7-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"), Vx("c", "MESSAGE")],
  [Ed("KNOWS", "p1", "p2"), Ed("LIKES", "p2", "c"),
   Ed("HASCREATOR", "c", "p1", din="SPJ")],
  proj=["p2.id", "c.content"])

# ===================== IC8: commenters who replied to my post -- pure MATCH =====================
Q("ic8-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("ps", "POST"), Vx("c", "COMMENT"), Vx("p2", "PERSON")],
  [Ed("HASCREATOR", "ps", "p1"), Ed("REPLYOF", "c", "ps"), Ed("HASCREATOR", "c", "p2")],
  proj=["p2.id", "c.content"])

# ===================== IC9: friends' recent comments -- pure MATCH (older version takes only attributes, no structural SPJ) =====================
Q("ic9-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"),
   Vx("c", "COMMENT", [("creationDate", "<", CD)])],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "c", "p2")],
  proj=["p2.firstName", "c.creationDate"])

Q("ic9-2",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("p2", "PERSON"),
   Vx("c", "COMMENT", [("creationDate", "<", CD)])],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "p2"), Ed("HASCREATOR", "c", "p2")],
  proj=["p2.firstName", "c.creationDate"])

# ===================== IC10: 2-hop friends matching interests (paper: single hop) -- hasTag cycle-closing SPJ =====================
# d(tag) is introduced by a's hasInterest (MATCH); post c's hasTag closes onto d (SPJ EdgeCheck) -- ExpandInt
Q("ic10-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"),
   Vx("c", "POST"), Vx("e", "PLACE"), Vx("d", "TAG")],
  [Ed("KNOWS", "p1", "p2"), Ed("HASCREATOR", "c", "p2"), Ed("ISLOCATEDIN", "p2", "e"),
   Ed("HASINTEREST", "p1", "d"), Ed("HASTAG", "c", "d", din="SPJ")],
  proj=["p2.id", "p2.firstName", "e.name"])

# ===================== IC11: friends' employment (organisation/location) -- pure MATCH (older version had no outer JOIN) =====================
Q("ic11-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("p2", "PERSON"),
   Vx("o", "ORGANISATION"), Vx("pl", "PLACE")],
  [Ed("KNOWS", "p1", "p2"),
   Ed("WORKAT", "p2", "o", pred=[("workFrom", "<", WF)], ptbl="person_workAt_organisation"),
   Ed("ISLOCATEDIN", "o", "pl")],
  proj=["p2.id", "o.name"])

Q("ic11-2",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("pa", "PERSON"), Vx("p2", "PERSON"),
   Vx("o", "ORGANISATION"), Vx("pl", "PLACE")],
  [Ed("KNOWS", "p1", "pa"), Ed("KNOWS", "pa", "p2"),
   Ed("WORKAT", "p2", "o", pred=[("workFrom", "<", WF)], ptbl="person_workAt_organisation"),
   Ed("ISLOCATEDIN", "o", "pl")],
  proj=["p2.id", "o.name"])

# ===================== IC12: tag classes of posts that friends' comments reply to -- hasType->tagclass as SPJ (R') =====================
Q("ic12-1",
  [Vx("p1", "PERSON", [("id", "=", ID)]), Vx("f", "PERSON"), Vx("c", "COMMENT"),
   Vx("ps", "POST"), Vx("t", "TAG")],
  [Ed("KNOWS", "p1", "f"), Ed("HASCREATOR", "c", "f"), Ed("REPLYOF", "c", "ps"), Ed("HASTAG", "ps", "t")],
  relations=[Rel("tc", "TagClass", "t", "tag_hasType_tagclass", ptbl="tagclass", pred=[("name", "=", TCN)])],
  proj=["f.id", "f.firstName"])


if __name__ == "__main__":
    print(f"registered {len(REGISTRY)} queries:")
    for name, q in REGISTRY.items():
        spj_e = [f"{e.src}-{e.label}-{e.dst}" for e in q.edges if e.declared_in == "SPJ"]
        rels = [f"{r.var}:{r.label}" for r in q.relations.values()]
        print(f"  {name:8} V{len(q.vertices)} E{len(q.edges)} | SPJ-cycle {spj_e or '-'} R' {rels or '-'}")
