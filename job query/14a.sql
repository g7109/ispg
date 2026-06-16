SELECT MIN(mi_idx.info) AS rating,
       MIN(g.t_title) AS northern_dark_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[kt:KIND_TYPE_TITLE]->(kind_type:KIND_TYPE),
    (t)-[mi:MOVIE_INFO]->(it1:INFO_TYPE),
    (t)-[mk:MOVIE_KEYWORD]->(k:KEYWORD)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    it1.info AS it1_info,
    k.keyword AS k_keyword,
    kind_type.kind AS kind_type_kind,
    mi.info AS mi_info,
    t.production_year AS t_production_year
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id AND mi_idx.info < '8.5'
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'rating'
WHERE g.it1_info = 'countries'
  AND g.k_keyword IN ('murder', 'murder-in-title', 'blood', 'violence')
  AND g.kind_type_kind = 'movie'
  AND g.mi_info IN ('Sweden', 'Norway', 'Germany', 'Denmark', 'Swedish',
                    'Denish', 'Norwegian', 'German', 'USA', 'American')
  AND g.t_production_year > 2010;
