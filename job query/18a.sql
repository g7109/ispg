SELECT MIN(g.mi_info) AS movie_budget,
       MIN(mi_idx.info) AS movie_votes,
       MIN(g.t_title) AS movie_title
FROM GRAPH_TABLE (graph
  MATCH
    (n:NAME)-[ci_name_title:CAST_INFO_NAME_TITLE]->(t:TITLE)-[mi:MOVIE_INFO]->(it1:INFO_TYPE)
  COLUMNS (
    t.id AS t_id,
    mi.info AS mi_info,
    t.title AS t_title,
    ci_name_title.note AS ci_name_title_note,
    it1.info AS it1_info,
    n.gender AS n_gender,
    n.name AS n_name
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'votes'
WHERE g.ci_name_title_note IN ('(producer)', '(executive producer)')
  AND g.it1_info = 'budget'
  AND g.n_gender = 'm'
  AND g.n_name LIKE '%Tim%';
