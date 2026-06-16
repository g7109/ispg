SELECT MIN(g.cn_name) AS movie_company,
       MIN(mi_idx.info) AS rating,
       MIN(g.t_title) AS complete_euro_dark_movie
FROM GRAPH_TABLE (graph
  MATCH
    (cct1:COMP_CAST_TYPE)<-[cc_subject:COMPLETE_CAST_SUBJECT]-(t:TITLE)-[cc_status:COMPLETE_CAST_STATUS]->(cct2:COMP_CAST_TYPE),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE),
    (t)-[mi:MOVIE_INFO]->(it1:INFO_TYPE),
    (t)-[mk:MOVIE_KEYWORD]->(k:KEYWORD),
    (t)-[:KIND_TYPE_TITLE]->(kt:KIND_TYPE)
  COLUMNS (
    t.id AS t_id,
    cn.name AS cn_name,
    t.title AS t_title,
    cct1.kind AS cct1_kind,
    cct2.kind AS cct2_kind,
    cn.country_code AS cn_country_code,
    it1.info AS it1_info,
    k.keyword AS k_keyword,
    kt.kind AS kt_kind,
    mc_name.note AS mc_name_note,
    mi.info AS mi_info,
    t.production_year AS t_production_year,
    cc_subject.id AS cc_subject_id,
    cc_status.id AS cc_status_id,
    mc_name.id AS mc_name_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id AND mi_idx.info < '8.5'
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'rating'
WHERE g.cct1_kind = 'crew'
  AND g.cct2_kind <> 'complete+verified'
  AND g.cn_country_code <> '[us]'
  AND g.it1_info = 'countries'
  AND g.k_keyword IN ('murder', 'murder-in-title', 'blood', 'violence')
  AND g.kt_kind IN ('movie', 'episode')
  AND g.mc_name_note NOT LIKE '%(USA)%'
  AND g.mc_name_note LIKE '%(200%)%'
  AND g.mi_info IN ('Sweden', 'Norway', 'Germany', 'Denmark', 'Swedish',
                    'Danish', 'Norwegian', 'German', 'USA', 'American')
  AND g.t_production_year > 2000
  AND g.cc_subject_id = g.cc_status_id
  AND g.mc_name_id = g.mc_type_id;
