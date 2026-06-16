"""Registry of JOB (Join-Order-Benchmark, over IMDB) queries as ISPG SPJM queries.

Hand-encoded SPJM IR for the 33 JOB queries, mirroring queries.py for LDBC: the ../job
query/*.sql files are the reference SQL/PGQ, and each is modelled here the same way as
LDBC (the boundary follows the rewritten SQL):
  - a central entity is a vertex (title / name); a relationship table linking two
    vertices is a MATCH edge;
  - a selective satellite table is a relation R' (the SPJ side, executed as Join via
    key-mapping), carrying its strong predicate -- so a plan may enter from the selective
    SPJ side and interleave with MATCH;
  - per-element predicates are attached to the vertex/edge they constrain.
See stats_imdb.TABLE_TO_LABEL / NONVERTEX_TO_EDGE for the table-to-graph mapping.
"""
from __future__ import annotations

from ir import Edge, Relation, SPJMQuery, Vertex

JOB_REGISTRY: dict[str, SPJMQuery] = {}


def Vx(var, label, pred=None):
    # table_for_pred defaults to the table behind the label (JOB labels are table names)
    return Vertex(var, label, "MATCH", label.lower() if pred else None, pred or [])


def Ed(label, src, dst, din="MATCH", pred=None):
    return Edge(label, label, src, dst, din, pred or [], label.lower() if pred else None)


def Rel(var, label, parent, fanout_table, pred=None, by="src"):
    return Relation(var, label, parent=parent, fanout_table=fanout_table, fanout_by=by,
                    pred_table=label.lower(), predicates=pred or [])


def Q(name, vertices, edges, relations=None):
    q = SPJMQuery(name=name, vertices={v.var: v for v in vertices}, edges=edges,
                  relations={r.var: r for r in (relations or [])})
    JOB_REGISTRY[name] = q
    return q


# Each query: MATCH stays connected; one strongly-selective satellite table is the R'
# (Get on the SPJ side -> Resolve into MATCH), carrying the selective equality predicate.

Q("1a",
  [Vx("t", "TITLE"), Vx("ct", "COMPANY_TYPE", [("kind", "=", "production companies")])],
  [Ed("MOVIE_COMPANIES_TYPE", "t", "ct")],
  [Rel("it", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "top 250 rank")])])

Q("2a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "=", "[de]")]), Vx("t", "TITLE")],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn")],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "character-name-in-title")])])

Q("3a",
  [Vx("t", "TITLE", [("production_year", ">", 2005)]), Vx("it", "INFO_TYPE")],
  [Ed("MOVIE_INFO", "t", "it",
      pred=[("info", "in", ["Sweden", "Norway", "Germany", "Denmark",
                            "Swedish", "Denish", "Norwegian", "German"])])],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "like", "%sequel%")])])

Q("4a",
  [Vx("t", "TITLE", [("production_year", ">", 2005)]),
   Vx("k", "KEYWORD", [("keyword", "like", "%sequel%")])],
  [Ed("MOVIE_KEYWORD", "t", "k")],
  [Rel("it", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("5a",
  [Vx("t", "TITLE", [("production_year", ">", 2005)]), Vx("it", "INFO_TYPE")],
  [Ed("MOVIE_INFO", "t", "it",
      pred=[("info", "in", ["Sweden", "Norway", "Germany", "Denmark",
                            "Swedish", "Denish", "Norwegian", "German"])])],
  [Rel("ct", "COMPANY_TYPE", "t", "movie_companies", [("kind", "=", "production companies")])])

Q("6a",
  [Vx("t", "TITLE", [("production_year", ">", 2010)]),
   Vx("n", "NAME", [("name", "like", "%Downey%Robert%")])],
  [Ed("CAST_INFO_NAME_TITLE", "t", "n")],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "marvel-cinematic-universe")])])

Q("7a",
  [Vx("an", "AKA_NAME", [("name", "like", "%a%")]),
   Vx("n", "NAME", [("name_pcode_cf", ">=", "A"), ("name_pcode_cf", "<=", "F")]),
   Vx("t", "TITLE", [("production_year", ">=", 1980), ("production_year", "<=", 1995)]),
   Vx("lt", "LINK_TYPE", [("link", "=", "features")])],
  [Ed("ALSO_KNOWN_AS_NAME", "an", "n"), Ed("CAST_INFO_NAME_TITLE", "n", "t"),
   Ed("MOVIE_LINK_LINKED_TYPE", "t", "lt")],
  [Rel("it", "INFO_TYPE", "n", "person_info", [("info", "=", "mini biography")])])

Q("8a",
  [Vx("an1", "AKA_NAME"), Vx("n1", "NAME", [("name", "like", "%Yo%")]),
   Vx("rt", "ROLE_TYPE", [("role", "=", "actress")]), Vx("t", "TITLE")],
  [Ed("ALSO_KNOWN_AS_NAME", "an1", "n1"), Ed("CAST_INFO_NAME_ROLE", "n1", "rt"),
   Ed("CAST_INFO_NAME_TITLE", "n1", "t", pred=[("note", "=", "(voice: English version)")])],
  [Rel("cn", "COMPANY_NAME", "t", "movie_companies", [("country_code", "=", "[jp]")])])

Q("9a",
  [Vx("an", "AKA_NAME"), Vx("n", "NAME", [("gender", "=", "f"), ("name", "like", "%Ang%")]),
   Vx("rt", "ROLE_TYPE", [("role", "=", "actress")]), Vx("chn", "CHAR_NAME"),
   Vx("t", "TITLE", [("production_year", ">=", 2005), ("production_year", "<=", 2015)])],
  [Ed("ALSO_KNOWN_AS_NAME", "an", "n"), Ed("CAST_INFO_NAME_ROLE", "n", "rt"),
   Ed("CAST_INFO_NAME_CHAR", "n", "chn"),
   Ed("CAST_INFO_NAME_TITLE", "n", "t",
      pred=[("note", "in", ["(voice)", "(voice: Japanese version)",
                            "(voice) (uncredited)", "(voice: English version)"])])],
  [Rel("cn", "COMPANY_NAME", "t", "movie_companies", [("country_code", "=", "[us]")])])

Q("10a",
  [Vx("t", "TITLE", [("production_year", ">", 2005)]), Vx("ct", "COMPANY_TYPE"),
   Vx("chn", "CHAR_NAME"), Vx("rt", "ROLE_TYPE", [("role", "=", "actor")])],
  [Ed("MOVIE_COMPANIES_TYPE", "t", "ct"),
   Ed("CAST_INFO_TITLE_CHAR", "t", "chn", pred=[("note", "like", "%(voice)%")]),
   Ed("CAST_INFO_TITLE_ROLE", "t", "rt")],
  [Rel("cn", "COMPANY_NAME", "t", "movie_companies", [("country_code", "=", "[ru]")])])

Q("11a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "<>", "[pl]")]),
   Vx("t", "TITLE", [("production_year", ">=", 1950), ("production_year", "<=", 2000)]),
   Vx("lt", "LINK_TYPE", [("link", "like", "%follow%")]),
   Vx("ct", "COMPANY_TYPE", [("kind", "=", "production companies")])],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_LINK_TYPE", "t", "lt"),
   Ed("MOVIE_COMPANIES_TYPE", "t", "ct")],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "sequel")])])

Q("12a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")]),
   Vx("t", "TITLE", [("production_year", ">=", 2005), ("production_year", "<=", 2008)]),
   Vx("it1", "INFO_TYPE", [("info", "=", "genres")]),
   Vx("ct", "COMPANY_TYPE", [("kind", "=", "production companies")])],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn"),
   Ed("MOVIE_INFO", "t", "it1", pred=[("info", "in", ["Drama", "Horror"])]),
   Ed("MOVIE_COMPANIES_TYPE", "t", "ct")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("13a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "=", "[de]")]), Vx("t", "TITLE"),
   Vx("it2", "INFO_TYPE", [("info", "=", "release dates")]),
   Vx("kt", "KIND_TYPE", [("kind", "=", "movie")]),
   Vx("ct", "COMPANY_TYPE", [("kind", "=", "production companies")])],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_INFO", "t", "it2"),
   Ed("KIND_TYPE_TITLE", "t", "kt"), Ed("MOVIE_COMPANIES_TYPE", "t", "ct")],
  [Rel("it", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("14a",
  [Vx("t", "TITLE", [("production_year", ">", 2010)]),
   Vx("kind_type", "KIND_TYPE", [("kind", "=", "movie")]),
   Vx("it1", "INFO_TYPE", [("info", "=", "countries")]),
   Vx("k", "KEYWORD", [("keyword", "in", ["murder", "murder-in-title", "blood", "violence"])])],
  [Ed("KIND_TYPE_TITLE", "t", "kind_type"), Ed("MOVIE_INFO", "t", "it1"),
   Ed("MOVIE_KEYWORD", "t", "k")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("15a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")]),
   Vx("t", "TITLE", [("production_year", ">", 2000)]), Vx("k", "KEYWORD"),
   Vx("at", "AKA_TITLE"), Vx("ct", "COMPANY_TYPE")],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_KEYWORD", "t", "k"),
   Ed("ALSO_KNOWN_AS_TITLE", "at", "t"), Ed("MOVIE_COMPANIES_TYPE", "t", "ct")],
  [Rel("it1", "INFO_TYPE", "t", "movie_info", [("info", "=", "release dates")])])

Q("16a",
  [Vx("an", "AKA_NAME"), Vx("n", "NAME"),
   Vx("t", "TITLE", [("episode_nr", ">=", 50), ("episode_nr", "<", 100)]),
   Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")])],
  [Ed("ALSO_KNOWN_AS_NAME", "an", "n"), Ed("CAST_INFO_NAME_TITLE", "n", "t"),
   Ed("MOVIE_COMPANIES_NAME", "t", "cn")],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "character-name-in-title")])])

Q("17a",
  [Vx("n", "NAME", [("name", "like", "B%")]), Vx("t", "TITLE"),
   Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")])],
  [Ed("CAST_INFO_NAME_TITLE", "n", "t"), Ed("MOVIE_COMPANIES_NAME", "t", "cn")],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "character-name-in-title")])])

Q("18a",
  [Vx("n", "NAME", [("gender", "=", "m"), ("name", "like", "%Tim%")]), Vx("t", "TITLE"),
   Vx("it1", "INFO_TYPE", [("info", "=", "budget")])],
  [Ed("CAST_INFO_NAME_TITLE", "n", "t",
      pred=[("note", "in", ["(producer)", "(executive producer)"])]),
   Ed("MOVIE_INFO", "t", "it1")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "votes")])])

Q("19a",
  [Vx("n", "NAME", [("gender", "=", "f"), ("name", "like", "%Ang%")]),
   Vx("t", "TITLE", [("production_year", ">=", 2005), ("production_year", "<=", 2009)]),
   Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")]), Vx("an", "AKA_NAME"),
   Vx("rt", "ROLE_TYPE", [("role", "=", "actress")]), Vx("chn", "CHAR_NAME")],
  [Ed("CAST_INFO_NAME_TITLE", "n", "t",
      pred=[("note", "in", ["(voice)", "(voice: Japanese version)",
                            "(voice) (uncredited)", "(voice: English version)"])]),
   Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("ALSO_KNOWN_AS_NAME", "n", "an"),
   Ed("CAST_INFO_NAME_ROLE", "n", "rt"), Ed("CAST_INFO_NAME_CHAR", "chn", "n")],
  [Rel("it", "INFO_TYPE", "t", "movie_info", [("info", "=", "release dates")])])

Q("20a",
  [Vx("t", "TITLE", [("production_year", ">", 1950)]),
   Vx("kind_type", "KIND_TYPE", [("kind", "=", "movie")]),
   Vx("cct1", "COMP_CAST_TYPE", [("kind", "=", "cast")]),
   Vx("cct2", "COMP_CAST_TYPE", [("kind", "like", "%complete%")]),
   Vx("chn", "CHAR_NAME", [("name", "like", "%Tony%Stark%")]), Vx("n", "NAME")],
  [Ed("KIND_TYPE_TITLE", "t", "kind_type"), Ed("COMPLETE_CAST_SUBJECT", "t", "cct1"),
   Ed("COMPLETE_CAST_STATUS", "t", "cct2"), Ed("CAST_INFO_TITLE_CHAR", "t", "chn"),
   Ed("CAST_INFO_NAME_TITLE", "n", "t")],
  [Rel("k", "KEYWORD", "t", "movie_keyword",
       [("keyword", "in", ["superhero", "sequel", "second-part", "marvel-comics",
                           "based-on-comic", "tv-special", "fight", "violence"])])])

Q("21a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "<>", "[pl]")]),
   Vx("t", "TITLE", [("production_year", ">=", 1950), ("production_year", "<=", 2000)]),
   Vx("lt", "LINK_TYPE", [("link", "like", "%follow%")]),
   Vx("ct", "COMPANY_TYPE", [("kind", "=", "production companies")]), Vx("it", "INFO_TYPE")],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_LINK_TYPE", "t", "lt"),
   Ed("MOVIE_COMPANIES_TYPE", "t", "ct"),
   Ed("MOVIE_INFO", "t", "it",
      pred=[("info", "in", ["Sweden", "Norway", "Germany", "Denmark",
                            "Swedish", "Denish", "Norwegian", "German"])])],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "sequel")])])

Q("22a",
  [Vx("cn", "COMPANY_NAME", [("country_code", "<>", "[us]")]),
   Vx("t", "TITLE", [("production_year", ">", 2008)]),
   Vx("k", "KEYWORD", [("keyword", "in", ["murder", "murder-in-title", "blood", "violence"])]),
   Vx("it1", "INFO_TYPE", [("info", "=", "countries")]),
   Vx("kt", "KIND_TYPE", [("kind", "in", ["movie", "episode"])]), Vx("ct", "COMPANY_TYPE")],
  [Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_KEYWORD", "t", "k"),
   Ed("MOVIE_INFO", "t", "it1"), Ed("KIND_TYPE_TITLE", "t", "kt"),
   Ed("MOVIE_COMPANIES_TYPE", "t", "ct")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("23a",
  [Vx("t", "TITLE", [("production_year", ">", 2000)]),
   Vx("kt", "KIND_TYPE", [("kind", "=", "movie")]),
   Vx("it1", "INFO_TYPE", [("info", "=", "release dates")]),
   Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")]), Vx("ct", "COMPANY_TYPE"),
   Vx("k", "KEYWORD")],
  [Ed("KIND_TYPE_TITLE", "t", "kt"), Ed("MOVIE_INFO", "t", "it1"),
   Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_COMPANIES_TYPE", "t", "ct"),
   Ed("MOVIE_KEYWORD", "t", "k")],
  [Rel("cct1", "COMP_CAST_TYPE", "t", "complete_cast", [("kind", "=", "complete+verified")])])

Q("24a",
  [Vx("n", "NAME", [("gender", "=", "f"), ("name", "like", "%An%")]),
   Vx("t", "TITLE", [("production_year", ">", 2010)]),
   Vx("rt", "ROLE_TYPE", [("role", "=", "actress")]), Vx("an", "AKA_NAME"),
   Vx("chn", "CHAR_NAME"),
   Vx("k", "KEYWORD", [("keyword", "in", ["hero", "martial-arts", "hand-to-hand-combat"])]),
   Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")])],
  [Ed("CAST_INFO_NAME_ROLE", "n", "rt",
      pred=[("note", "in", ["(voice)", "(voice: Japanese version)",
                            "(voice) (uncredited)", "(voice: English version)"])]),
   Ed("ALSO_KNOWN_AS_NAME", "n", "an"), Ed("CAST_INFO_NAME_CHAR", "n", "chn"),
   Ed("CAST_INFO_NAME_TITLE", "n", "t"), Ed("MOVIE_KEYWORD", "t", "k"),
   Ed("MOVIE_COMPANIES_NAME", "t", "cn")],
  [Rel("it", "INFO_TYPE", "t", "movie_info", [("info", "=", "release dates")])])

Q("25a",
  [Vx("n", "NAME", [("gender", "=", "m")]), Vx("t", "TITLE"),
   Vx("k", "KEYWORD", [("keyword", "in", ["murder", "blood", "gore", "death", "female-nudity"])]),
   Vx("it1", "INFO_TYPE", [("info", "=", "genres")])],
  [Ed("CAST_INFO_NAME_TITLE", "n", "t",
      pred=[("note", "in", ["(writer)", "(head writer)", "(written by)",
                            "(story)", "(story editor)"])]),
   Ed("MOVIE_KEYWORD", "t", "k"), Ed("MOVIE_INFO", "t", "it1", pred=[("info", "=", "Horror")])],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "votes")])])

Q("26a",
  [Vx("t", "TITLE", [("production_year", ">", 2000)]),
   Vx("cct1", "COMP_CAST_TYPE", [("kind", "=", "cast")]),
   Vx("cct2", "COMP_CAST_TYPE", [("kind", "like", "%complete%")]),
   Vx("kt", "KIND_TYPE", [("kind", "=", "movie")]),
   Vx("chn", "CHAR_NAME", [("name", "like", "%man%")]), Vx("n", "NAME"),
   Vx("k", "KEYWORD", [("keyword", "in", ["superhero", "marvel-comics", "based-on-comic",
                                          "tv-special", "fight", "violence"])])],
  [Ed("COMPLETE_CAST_SUBJECT", "t", "cct1"), Ed("COMPLETE_CAST_STATUS", "t", "cct2"),
   Ed("KIND_TYPE_TITLE", "t", "kt"), Ed("CAST_INFO_TITLE_CHAR", "t", "chn"),
   Ed("CAST_INFO_NAME_TITLE", "n", "t"), Ed("MOVIE_KEYWORD", "t", "k")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("27a",
  [Vx("t", "TITLE", [("production_year", ">=", 1950), ("production_year", "<=", 2000)]),
   Vx("cct1", "COMP_CAST_TYPE", [("kind", "in", ["cast", "crew"])]),
   Vx("cct2", "COMP_CAST_TYPE", [("kind", "=", "complete")]),
   Vx("lt", "LINK_TYPE", [("link", "like", "%follow%")]),
   Vx("cn", "COMPANY_NAME", [("country_code", "<>", "[pl]")]),
   Vx("ct", "COMPANY_TYPE", [("kind", "=", "production companies")]), Vx("it", "INFO_TYPE")],
  [Ed("COMPLETE_CAST_STATUS", "t", "cct2"), Ed("COMPLETE_CAST_SUBJECT", "t", "cct1"),
   Ed("MOVIE_LINK_TYPE", "t", "lt"), Ed("MOVIE_COMPANIES_NAME", "t", "cn"),
   Ed("MOVIE_COMPANIES_TYPE", "t", "ct"),
   Ed("MOVIE_INFO", "t", "it", pred=[("info", "in", ["Sweden", "Germany", "Swedish", "German"])])],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "sequel")])])

Q("28a",
  [Vx("t", "TITLE", [("production_year", ">", 2000)]),
   Vx("cct1", "COMP_CAST_TYPE", [("kind", "=", "crew")]),
   Vx("cct2", "COMP_CAST_TYPE", [("kind", "<>", "complete+verified")]),
   Vx("cn", "COMPANY_NAME", [("country_code", "<>", "[us]")]),
   Vx("it1", "INFO_TYPE", [("info", "=", "countries")]),
   Vx("k", "KEYWORD", [("keyword", "in", ["murder", "murder-in-title", "blood", "violence"])]),
   Vx("kt", "KIND_TYPE", [("kind", "in", ["movie", "episode"])]), Vx("ct", "COMPANY_TYPE")],
  [Ed("COMPLETE_CAST_SUBJECT", "t", "cct1"), Ed("COMPLETE_CAST_STATUS", "t", "cct2"),
   Ed("MOVIE_COMPANIES_NAME", "t", "cn"), Ed("MOVIE_COMPANIES_TYPE", "t", "ct"),
   Ed("MOVIE_INFO", "t", "it1"), Ed("MOVIE_KEYWORD", "t", "k"), Ed("KIND_TYPE_TITLE", "t", "kt")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "rating")])])

Q("29a",
  [Vx("t", "TITLE", [("title", "=", "Shrek 2"),
                     ("production_year", ">=", 2000), ("production_year", "<=", 2010)]),
   Vx("cct1", "COMP_CAST_TYPE", [("kind", "=", "cast")]),
   Vx("cct2", "COMP_CAST_TYPE", [("kind", "=", "complete+verified")]),
   Vx("chn", "CHAR_NAME", [("name", "=", "Queen")]),
   Vx("n", "NAME", [("gender", "=", "f"), ("name", "like", "%An%")]),
   Vx("cn", "COMPANY_NAME", [("country_code", "=", "[us]")]),
   Vx("it", "INFO_TYPE", [("info", "=", "release dates")]),
   Vx("it3", "INFO_TYPE", [("info", "=", "trivia")]),
   Vx("rt", "ROLE_TYPE", [("role", "=", "actress")]), Vx("an", "AKA_NAME")],
  [Ed("COMPLETE_CAST_SUBJECT", "t", "cct1"), Ed("COMPLETE_CAST_STATUS", "t", "cct2"),
   Ed("CAST_INFO_TITLE_CHAR", "t", "chn",
      pred=[("note", "in", ["(voice)", "(voice) (uncredited)", "(voice: English version)"])]),
   Ed("CAST_INFO_NAME_TITLE", "n", "t"), Ed("MOVIE_COMPANIES_NAME", "t", "cn"),
   Ed("MOVIE_INFO", "t", "it"), Ed("PERSON_INFO", "n", "it3"),
   Ed("CAST_INFO_NAME_ROLE", "n", "rt"), Ed("ALSO_KNOWN_AS_NAME", "n", "an")],
  [Rel("k", "KEYWORD", "t", "movie_keyword", [("keyword", "=", "computer-animation")])])

Q("30a",
  [Vx("t", "TITLE", [("production_year", ">", 2000)]),
   Vx("cct1", "COMP_CAST_TYPE", [("kind", "in", ["cast", "crew"])]),
   Vx("cct2", "COMP_CAST_TYPE", [("kind", "=", "complete+verified")]),
   Vx("n", "NAME", [("gender", "=", "m")]),
   Vx("it1", "INFO_TYPE", [("info", "=", "genres")]),
   Vx("k", "KEYWORD", [("keyword", "in", ["murder", "violence", "blood", "gore",
                                          "death", "female-nudity", "hospital"])])],
  [Ed("COMPLETE_CAST_SUBJECT", "t", "cct1"), Ed("COMPLETE_CAST_STATUS", "t", "cct2"),
   Ed("CAST_INFO_NAME_TITLE", "n", "t",
      pred=[("note", "in", ["(writer)", "(head writer)", "(written by)",
                            "(story)", "(story editor)"])]),
   Ed("MOVIE_INFO", "t", "it1", pred=[("info", "in", ["Horror", "Thriller"])]),
   Ed("MOVIE_KEYWORD", "t", "k")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "votes")])])

Q("31a",
  [Vx("n", "NAME", [("gender", "=", "m")]), Vx("t", "TITLE"),
   Vx("cn", "COMPANY_NAME", [("name", "like", "Lionsgate%")]),
   Vx("it1", "INFO_TYPE", [("info", "=", "genres")]),
   Vx("k", "KEYWORD", [("keyword", "in", ["murder", "violence", "blood", "gore",
                                          "death", "female-nudity", "hospital"])])],
  [Ed("CAST_INFO_NAME_TITLE", "n", "t",
      pred=[("note", "in", ["(writer)", "(head writer)", "(written by)",
                            "(story)", "(story editor)"])]),
   Ed("MOVIE_COMPANIES_NAME", "t", "cn"),
   Ed("MOVIE_INFO", "t", "it1", pred=[("info", "in", ["Horror", "Thriller"])]),
   Ed("MOVIE_KEYWORD", "t", "k")],
  [Rel("it2", "INFO_TYPE", "t", "movie_info_idx", [("info", "=", "votes")])])

Q("32a",
  [Vx("t1", "TITLE"), Vx("t2", "TITLE"), Vx("lt", "LINK_TYPE")],
  [Ed("MOVIE_LINK_MOVIE", "t1", "t2"), Ed("MOVIE_LINK_TYPE", "t1", "lt")],
  [Rel("k", "KEYWORD", "t1", "movie_keyword", [("keyword", "=", "10,000-mile-club")])])

Q("33a",
  [Vx("t1", "TITLE"),
   Vx("t2", "TITLE", [("production_year", ">=", 2005), ("production_year", "<=", 2008)]),
   Vx("cn1", "COMPANY_NAME", [("country_code", "=", "[us]")]),
   Vx("kt1", "KIND_TYPE", [("kind", "=", "tv series")]),
   Vx("lt", "LINK_TYPE", [("link", "in", ["sequel", "follows", "followed by"])]),
   Vx("kt2", "KIND_TYPE", [("kind", "=", "tv series")]), Vx("cn2", "COMPANY_NAME"),
   Vx("it2", "INFO_TYPE", [("info", "=", "rating")])],
  [Ed("MOVIE_COMPANIES_NAME", "t1", "cn1"), Ed("KIND_TYPE_TITLE", "t1", "kt1"),
   Ed("MOVIE_LINK_MOVIE", "t1", "t2"), Ed("MOVIE_LINK_TYPE", "t1", "lt"),
   Ed("KIND_TYPE_TITLE", "t2", "kt2"), Ed("MOVIE_COMPANIES_NAME", "t2", "cn2"),
   Ed("MOVIE_INFO_IDX", "t2", "it2", pred=[("info", "<", "3.0")])],
  [Rel("it1", "INFO_TYPE", "t1", "movie_info_idx", [("info", "=", "rating")])])


if __name__ == "__main__":
    print(f"registered {len(JOB_REGISTRY)} JOB queries:")
    for name, q in JOB_REGISTRY.items():
        rels = [f"{r.var}:{r.label}" for r in q.relations.values()]
        print(f"  {name:5} V{len(q.vertices)} E{len(q.edges)} | R' {rels or '-'}")
