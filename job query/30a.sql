SELECT MIN(g.mi_info) AS movie_budget,
       MIN(mi_idx.info) AS movie_votes,
       MIN(g.n_name) AS writer,
       MIN(g.t_title) AS complete_violent_movie
FROM GRAPH_TABLE (graph
  MATCH
    (cct1:COMP_CAST_TYPE)<-[cc_subject:COMPLETE_CAST_SUBJECT]-(t:TITLE)-[cc_status:COMPLETE_CAST_STATUS]->(cct2:COMP_CAST_TYPE),
    (n:NAME)-[ci_name:CAST_INFO_NAME_TITLE]->(t),
    (t)-[mi:MOVIE_INFO]->(it1:INFO_TYPE),
    (t)-[mk:MOVIE_KEYWORD]->(k:KEYWORD)
  COLUMNS (
    t.id AS t_id,
    mi.info AS mi_info,
    n.name AS n_name,
    t.title AS t_title,
    cct1.kind AS cct1_kind,
    cct2.kind AS cct2_kind,
    ci_name.note AS ci_name_note,
    it1.info AS it1_info,
    k.keyword AS k_keyword,
    n.gender AS n_gender,
    t.production_year AS t_production_year,
    cc_subject.id AS cc_subject_id,
    cc_status.id AS cc_status_id
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'votes'
WHERE g.cct1_kind IN ('cast', 'crew')
  AND g.cct2_kind = 'complete+verified'
  AND g.ci_name_note IN ('(writer)', '(head writer)', '(written by)', '(story)', '(story editor)')
  AND g.it1_info = 'genres'
  AND g.k_keyword IN ('murder', 'violence', 'blood', 'gore', 'death', 'female-nudity', 'hospital')
  AND g.mi_info IN ('Horror', 'Thriller')
  AND g.n_gender = 'm'
  AND g.t_production_year > 2000
  AND g.cc_subject_id = g.cc_status_id;
