SELECT MIN(g.t_title) AS typical_european_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[mi:MOVIE_INFO]->(it:INFO_TYPE)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    mi.info AS mi_info,
    t.production_year AS t_production_year
  ) g
)
JOIN movie_companies mc_type ON mc_type.movie_id = g.t_id
  AND mc_type.note LIKE '%(theatrical)%'
  AND mc_type.note LIKE '%(France)%'
JOIN company_type ct ON ct.id = mc_type.company_type_id AND ct.kind = 'production companies'
WHERE g.mi_info IN ('Sweden',
                    'Norway',
                    'Germany',
                    'Denmark',
                    'Swedish',
                    'Denish',
                    'Norwegian',
                    'German')
  AND g.t_production_year > 2005;
