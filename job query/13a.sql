SELECT MIN(g.mi_info) AS release_date,
       MIN(miidx.info) AS rating,
       MIN(g.t_title) AS german_movie
FROM GRAPH_TABLE (graph
  MATCH
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t:TITLE)-[mi:MOVIE_INFO]->(it2:INFO_TYPE),
    (t)-[:KIND_TYPE_TITLE]->(kt:KIND_TYPE),
    (t)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE)
  COLUMNS (
    t.id AS t_id,
    mi.info AS mi_info,
    t.title AS t_title,
    cn.country_code AS cn_country_code,
    ct.kind AS ct_kind,
    it2.info AS it2_info,
    kt.kind AS kt_kind,
    mc_name.id AS mc_name_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN movie_info_idx miidx ON miidx.movie_id = g.t_id
JOIN info_type it ON it.id = miidx.info_type_id AND it.info = 'rating'
WHERE g.cn_country_code = '[de]'
  AND g.ct_kind = 'production companies'
  AND g.it2_info = 'release dates'
  AND g.kt_kind = 'movie'
  AND g.mc_name_id = g.mc_type_id;
