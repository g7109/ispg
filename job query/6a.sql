SELECT MIN(k.keyword) AS movie_keyword,
       MIN(g.n_name) AS actor_name,
       MIN(g.t_title) AS marvel_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[ci_name_title:CAST_INFO_NAME_TITLE]->(n:NAME)
  COLUMNS (
    t.id AS t_id,
    n.name AS n_name,
    t.title AS t_title,
    t.production_year AS t_production_year
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'marvel-cinematic-universe'
WHERE g.n_name LIKE '%Downey%Robert%'
  AND g.t_production_year > 2010;
