SELECT MIN(mi.info) AS release_date,
       MIN(g.t_title) AS internet_movie
FROM GRAPH_TABLE (graph
  MATCH
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t:TITLE)-[mk:MOVIE_KEYWORD]->(k:KEYWORD),
    (t)<-[:ALSO_KNOWN_AS_TITLE]-(at:AKA_TITLE),
    (t)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    cn.country_code AS cn_country_code,
    mc_name.note AS mc_name_note,
    t.production_year AS t_production_year,
    mc_name.id AS mc_name_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN movie_info mi ON mi.movie_id = g.t_id
  AND mi.note LIKE '%internet%'
  AND mi.info LIKE 'USA:% 200%'
JOIN info_type it1 ON it1.id = mi.info_type_id AND it1.info = 'release dates'
WHERE g.cn_country_code = '[us]'
  AND g.mc_name_note LIKE '%(200%)%'
  AND g.mc_name_note LIKE '%(worldwide)%'
  AND g.t_production_year > 2000
  AND g.mc_name_id = g.mc_type_id;
