SELECT MIN(g.lt_link) AS link_type,
       MIN(g.t1_title) AS first_movie,
       MIN(g.t2_title) AS second_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t1:TITLE)-[ml_movie:MOVIE_LINK_MOVIE]->(t2:TITLE),
    (t1)-[ml_type:MOVIE_LINK_TYPE]->(lt:LINK_TYPE)
  COLUMNS (
    t1.id AS t1_id,
    lt.link AS lt_link,
    t1.title AS t1_title,
    t2.title AS t2_title,
    ml_movie.id AS ml_movie_id,
    ml_type.id AS ml_type_id
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t1_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = '10,000-mile-club'
WHERE g.ml_movie_id = g.ml_type_id;
