SELECT MIN(g.cn1_name) AS first_company,
       MIN(g.cn2_name) AS second_company,
       MIN(mi_idx1.info) AS first_rating,
       MIN(g.mi_idx2_info) AS second_rating,
       MIN(g.t1_title) AS first_movie,
       MIN(g.t2_title) AS second_movie
FROM GRAPH_TABLE (graph
  MATCH
    (cn1:COMPANY_NAME)<-[mc1_name:MOVIE_COMPANIES_NAME]-(t1:TITLE)-[:KIND_TYPE_TITLE]->(kt1:KIND_TYPE),
    (t1)-[ml_movie:MOVIE_LINK_MOVIE]->(t2:TITLE),
    (t1)-[ml_type:MOVIE_LINK_TYPE]->(lt:LINK_TYPE),
    (t2)-[:KIND_TYPE_TITLE]->(kt2:KIND_TYPE),
    (t2)-[mc2_name:MOVIE_COMPANIES_NAME]->(cn2:COMPANY_NAME),
    (t2)-[mi_idx2:MOVIE_INFO_IDX]->(it2:INFO_TYPE)
  COLUMNS (
    t1.id AS t1_id,
    cn1.name AS cn1_name,
    cn2.name AS cn2_name,
    mi_idx2.info AS mi_idx2_info,
    t1.title AS t1_title,
    t2.title AS t2_title,
    cn1.country_code AS cn1_country_code,
    it2.info AS it2_info,
    kt1.kind AS kt1_kind,
    kt2.kind AS kt2_kind,
    lt.link AS lt_link,
    t2.production_year AS t2_production_year
  ) g
)
JOIN movie_info_idx mi_idx1 ON mi_idx1.movie_id = g.t1_id
JOIN info_type it1 ON it1.id = mi_idx1.info_type_id AND it1.info = 'rating'
WHERE g.cn1_country_code = '[us]'
  AND g.it2_info = 'rating'
  AND g.kt1_kind IN ('tv series')
  AND g.kt2_kind IN ('tv series')
  AND g.lt_link IN ('sequel', 'follows', 'followed by')
  AND g.mi_idx2_info < '3.0'
  AND g.t2_production_year >= 2005
  AND g.t2_production_year <= 2008;
