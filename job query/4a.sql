SELECT MIN(mi_idx.info) AS rating,
       MIN(g.t_title) AS movie_title
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[mk:MOVIE_KEYWORD]->(k:KEYWORD)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    t.production_year AS t_production_year,
    k.keyword AS k_keyword
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id AND mi_idx.info > '5.0'
JOIN info_type it ON it.id = mi_idx.info_type_id AND it.info = 'rating'
WHERE g.k_keyword LIKE '%sequel%'
  AND g.t_production_year > 2005;
