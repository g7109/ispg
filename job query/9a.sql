SELECT MIN(g.an_name) AS alternative_name,
       MIN(g.chn_name) AS character_name,
       MIN(g.t_title) AS movie
FROM GRAPH_TABLE (graph
  MATCH
    (an:AKA_NAME)-[:ALSO_KNOWN_AS_NAME]->(n:NAME),
    (n)-[ci_name_role:CAST_INFO_NAME_ROLE]->(rt:ROLE_TYPE),
    (n)-[ci_name_char:CAST_INFO_NAME_CHAR]->(chn:CHAR_NAME),
    (n)-[ci_name_title:CAST_INFO_NAME_TITLE]->(t:TITLE)
  COLUMNS (
    t.id AS t_id,
    an.name AS an_name,
    chn.name AS chn_name,
    t.title AS t_title,
    ci_name_title.note AS ci_name_title_note,
    n.gender AS n_gender,
    n.name AS n_name,
    rt.role AS rt_role,
    t.production_year AS t_production_year,
    ci_name_role.id AS ci_name_role_id,
    ci_name_char.id AS ci_name_char_id,
    ci_name_title.id AS ci_name_title_id
  ) g
)
JOIN movie_companies mc_name ON mc_name.movie_id = g.t_id
  AND mc_name.note IS NOT NULL
  AND (mc_name.note LIKE '%(USA)%' OR mc_name.note LIKE '%(worldwide)%')
JOIN company_name cn ON cn.id = mc_name.company_id AND cn.country_code = '[us]'
WHERE g.ci_name_title_note IN ('(voice)',
                               '(voice: Japanese version)',
                               '(voice) (uncredited)',
                               '(voice: English version)')
  AND g.n_gender = 'f'
  AND g.n_name LIKE '%Ang%'
  AND g.rt_role = 'actress'
  AND g.t_production_year >= 2005
  AND g.t_production_year <= 2015
  AND g.ci_name_role_id = g.ci_name_char_id
  AND g.ci_name_title_id = g.ci_name_char_id;
