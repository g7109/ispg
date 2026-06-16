SELECT MIN(g.mi_info) AS movie_budget,
       MIN(mi_idx.info) AS movie_votes,
       MIN(g.n_name) AS writer,
       MIN(g.t_title) AS violent_liongate_movie
FROM GRAPH_TABLE (graph
  MATCH
    (n:NAME)-[ci_name:CAST_INFO_NAME_TITLE]->(t:TITLE),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t),
    (t)-[mi:MOVIE_INFO]->(it1:INFO_TYPE),
    (t)-[mk:MOVIE_KEYWORD]->(k:KEYWORD)
  COLUMNS (
    t.id AS t_id,
    mi.info AS mi_info,
    n.name AS n_name,
    t.title AS t_title,
    cn.name AS cn_name,
    it1.info AS it1_info,
    k.keyword AS k_keyword,
    n.gender AS n_gender,
    ci_name.note AS ci_name_note
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'votes'
WHERE g.cn_name LIKE 'Lionsgate%'
  AND g.it1_info = 'genres'
  AND g.k_keyword IN ('murder', 'violence', 'blood', 'gore', 'death', 'female-nudity', 'hospital')
  AND g.mi_info IN ('Horror', 'Thriller')
  AND g.n_gender = 'm'
  AND g.ci_name_note IN ('(writer)', '(head writer)', '(written by)', '(story)', '(story editor)');
