SELECT MIN(g.cn_name) AS company_name,
       MIN(g.lt_link) AS link_type,
       MIN(g.t_title) AS western_follow_up
FROM GRAPH_TABLE (graph
  MATCH
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t:TITLE),
    (t)-[ml_type:MOVIE_LINK_TYPE]->(lt:LINK_TYPE),
    (t)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE),
    (t)-[mi:MOVIE_INFO]->(:INFO_TYPE)
  COLUMNS (
    t.id AS t_id,
    cn.name AS cn_name,
    lt.link AS lt_link,
    t.title AS t_title,
    cn.country_code AS cn_country_code,
    ct.kind AS ct_kind,
    mc_name.note AS mc_name_note,
    mi.info AS mi_info,
    t.production_year AS t_production_year,
    mc_name.id AS mc_name_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'sequel'
WHERE g.cn_country_code <> '[pl]'
  AND (g.cn_name LIKE '%Film%' OR g.cn_name LIKE '%Warner%')
  AND g.ct_kind = 'production companies'
  AND g.lt_link LIKE '%follow%'
  AND g.mc_name_note IS NULL
  AND g.mi_info IN ('Sweden', 'Norway', 'Germany', 'Denmark', 'Swedish',
                    'Denish', 'Norwegian', 'German')
  AND g.t_production_year >= 1950
  AND g.t_production_year <= 2000
  AND g.mc_name_id = g.mc_type_id;
