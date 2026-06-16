SELECT MIN(g.chn_name) AS voiced_char_name,
       MIN(g.n_name) AS voicing_actress_name,
       MIN(g.t_title) AS voiced_action_movie_jap_eng
FROM GRAPH_TABLE (graph
  MATCH
    (rt:ROLE_TYPE)<-[ci_role:CAST_INFO_NAME_ROLE]-(n:NAME)-[:ALSO_KNOWN_AS_NAME]->(an:AKA_NAME),
    (n)-[ci_char:CAST_INFO_NAME_CHAR]->(chn:CHAR_NAME),
    (n)-[ci_name:CAST_INFO_NAME_TITLE]->(t:TITLE)-[mk:MOVIE_KEYWORD]->(k:KEYWORD),
    (t)-[mc_name:MOVIE_COMPANIES_NAME]->(cn:COMPANY_NAME)
  COLUMNS (
    t.id AS t_id,
    chn.name AS chn_name,
    n.name AS n_name,
    t.title AS t_title,
    ci_role.note AS ci_role_note,
    cn.country_code AS cn_country_code,
    k.keyword AS k_keyword,
    n.gender AS n_gender,
    rt.role AS rt_role,
    t.production_year AS t_production_year,
    ci_role.id AS ci_role_id,
    ci_char.id AS ci_char_id,
    ci_name.id AS ci_name_id
  ) g
)
JOIN movie_info mi ON mi.movie_id = g.t_id
  AND mi.info IS NOT NULL
  AND (mi.info LIKE 'Japan:%201%' OR mi.info LIKE 'USA:%201%')
JOIN info_type it ON it.id = mi.info_type_id AND it.info = 'release dates'
WHERE g.ci_role_note IN ('(voice)', '(voice: Japanese version)', '(voice) (uncredited)', '(voice: English version)')
  AND g.cn_country_code = '[us]'
  AND g.k_keyword IN ('hero', 'martial-arts', 'hand-to-hand-combat')
  AND g.n_gender = 'f'
  AND g.n_name LIKE '%An%'
  AND g.rt_role = 'actress'
  AND g.t_production_year > 2010
  AND g.ci_role_id = g.ci_char_id
  AND g.ci_char_id = g.ci_name_id;
