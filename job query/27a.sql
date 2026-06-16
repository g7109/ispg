SELECT MIN(g.cn_name) AS producing_company,
       MIN(g.lt_link) AS link_type,
       MIN(g.t_title) AS complete_western_sequel
FROM GRAPH_TABLE (graph
  MATCH
    (cct2:COMP_CAST_TYPE)<-[cc_status:COMPLETE_CAST_STATUS]-(t:TITLE)-[cc_subject:COMPLETE_CAST_SUBJECT]->(cct1:COMP_CAST_TYPE),
    (lt:LINK_TYPE)<-[ml_type:MOVIE_LINK_TYPE]-(t),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE),
    (t)-[mi:MOVIE_INFO]->(:INFO_TYPE)
  COLUMNS (
    t.id AS t_id,
    cn.name AS cn_name,
    lt.link AS lt_link,
    t.title AS t_title,
    cct1.kind AS cct1_kind,
    cct2.kind AS cct2_kind,
    cn.country_code AS cn_country_code,
    ct.kind AS ct_kind,
    mc_name.note AS mc_name_note,
    mi.info AS mi_info,
    t.production_year AS t_production_year,
    cc_subject.id AS cc_subject_id,
    cc_status.id AS cc_status_id,
    mc_name.id AS mc_name_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'sequel'
WHERE g.cct1_kind IN ('cast', 'crew')
  AND g.cct2_kind = 'complete'
  AND g.cn_country_code <> '[pl]'
  AND (g.cn_name LIKE '%Film%' OR g.cn_name LIKE '%Warner%')
  AND g.ct_kind = 'production companies'
  AND g.lt_link LIKE '%follow%'
  AND g.mc_name_note IS NULL
  AND g.mi_info IN ('Sweden', 'Germany', 'Swedish', 'German')
  AND g.t_production_year >= 1950
  AND g.t_production_year <= 2000
  AND g.cc_subject_id = g.cc_status_id
  AND g.mc_name_id = g.mc_type_id;
