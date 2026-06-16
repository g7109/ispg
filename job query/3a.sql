SELECT MIN(g.t_title) AS movie_title
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[mi:MOVIE_INFO]->(:INFO_TYPE)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    t.production_year AS t_production_year,
    mi.info AS mi_info
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword LIKE '%sequel%'
WHERE g.mi_info IN ('Sweden', 'Norway', 'Germany', 'Denmark', 'Swedish', 'Denish', 'Norwegian', 'German')
  AND g.t_production_year > 2005;
