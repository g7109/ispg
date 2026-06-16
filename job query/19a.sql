SELECT MIN(g.n_name) AS voicing_actress,
       MIN(g.t_title) AS voiced_movie
FROM GRAPH_TABLE (graph
  MATCH
    (n:NAME)-[ci_name:CAST_INFO_NAME_TITLE]->(t:TITLE),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t),
    (n)-[:ALSO_KNOWN_AS_NAME]->(an:AKA_NAME),
    (n)-[ci_role:CAST_INFO_NAME_ROLE]->(rt:ROLE_TYPE),
    (chn:CHAR_NAME)<-[ci_char:CAST_INFO_NAME_CHAR]-(n)
  COLUMNS (
    t.id AS t_id,
    n.name AS n_name,
    t.title AS t_title,
    ci_name.note AS ci_name_note,
    cn.country_code AS cn_country_code,
    mc_name.note AS mc_name_note,
    n.gender AS n_gender,
    rt.role AS rt_role,
    t.production_year AS t_production_year
  ) g
)
JOIN movie_info mi ON mi.movie_id = g.t_id
  AND mi.info IS NOT NULL
  AND (mi.info LIKE 'Japan:%200%' OR mi.info LIKE 'USA:%200%')
JOIN info_type it ON it.id = mi.info_type_id AND it.info = 'release dates'
WHERE g.ci_name_note IN ('(voice)',
                         '(voice: Japanese version)',
                         '(voice) (uncredited)',
                         '(voice: English version)')
  AND g.cn_country_code = '[us]'
  AND g.mc_name_note IS NOT NULL
  AND (g.mc_name_note LIKE '%(USA)%' OR g.mc_name_note LIKE '%(worldwide)%')
  AND g.n_gender = 'f'
  AND g.n_name LIKE '%Ang%'
  AND g.rt_role = 'actress'
  AND g.t_production_year >= 2005
  AND g.t_production_year <= 2009;
