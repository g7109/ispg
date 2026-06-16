SELECT MIN(g.kt_kind) AS movie_kind,
       MIN(g.t_title) AS complete_us_internet_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[:KIND_TYPE_TITLE]->(kt:KIND_TYPE),
    (t)-[mi:MOVIE_INFO]->(it1:INFO_TYPE),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE),
    (t)-[mk:MOVIE_KEYWORD]->(k:KEYWORD)
  COLUMNS (
    t.id AS t_id,
    kt.kind AS kt_kind,
    t.title AS t_title,
    cn.country_code AS cn_country_code,
    it1.info AS it1_info,
    mi.note AS mi_note,
    mi.info AS mi_info,
    t.production_year AS t_production_year,
    mc_name.id AS mc_name_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN complete_cast cc_status ON cc_status.movie_id = g.t_id
JOIN comp_cast_type cct1 ON cct1.id = cc_status.status_id AND cct1.kind = 'complete+verified'
WHERE g.cn_country_code = '[us]'
  AND g.it1_info = 'release dates'
  AND g.kt_kind IN ('movie')
  AND g.mi_note LIKE '%internet%'
  AND g.mi_info IS NOT NULL
  AND (g.mi_info LIKE 'USA:% 199%' OR g.mi_info LIKE 'USA:% 200%')
  AND g.t_production_year > 2000
  AND g.mc_name_id = g.mc_type_id;
