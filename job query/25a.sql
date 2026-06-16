SELECT MIN(g.mi_info) AS movie_budget,
       MIN(mi_idx.info) AS movie_votes,
       MIN(g.n_name) AS male_writer,
       MIN(g.t_title) AS violent_movie_title
FROM GRAPH_TABLE (graph
  MATCH
    (n:NAME)-[ci_name_title:CAST_INFO_NAME_TITLE]->(t:TITLE)-[mk:MOVIE_KEYWORD]->(k:KEYWORD),
    (t)-[mi:MOVIE_INFO]->(it1:INFO_TYPE)
  COLUMNS (
    t.id AS t_id,
    mi.info AS mi_info,
    n.name AS n_name,
    t.title AS t_title,
    ci_name_title.note AS ci_name_title_note,
    it1.info AS it1_info,
    k.keyword AS k_keyword,
    n.gender AS n_gender
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'votes'
WHERE g.ci_name_title_note IN ('(writer)', '(head writer)', '(written by)', '(story)', '(story editor)')
  AND g.it1_info = 'genres'
  AND g.k_keyword IN ('murder', 'blood', 'gore', 'death', 'female-nudity')
  AND g.mi_info = 'Horror'
  AND g.n_gender = 'm';
