SELECT MIN(g.chn_name) AS uncredited_voiced_character,
       MIN(g.t_title) AS russian_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[mc_type:MOVIE_COMPANIES_TYPE]->(ct:COMPANY_TYPE),
    (t)-[ci_title_char:CAST_INFO_TITLE_CHAR]->(chn:CHAR_NAME),
    (t)-[ci_title_role:CAST_INFO_TITLE_ROLE]->(rt:ROLE_TYPE)
  COLUMNS (
    t.id AS t_id,
    chn.name AS chn_name,
    t.title AS t_title,
    ci_title_char.note AS ci_title_char_note,
    rt.role AS rt_role,
    t.production_year AS t_production_year,
    ci_title_char.id AS ci_title_char_id,
    ci_title_role.id AS ci_title_role_id,
    mc_type.id AS mc_type_id
  ) g
)
JOIN movie_companies mc_name ON mc_name.movie_id = g.t_id
JOIN company_name cn ON cn.id = mc_name.company_id AND cn.country_code = '[ru]'
WHERE g.ci_title_char_note LIKE '%(voice)%'
  AND g.ci_title_char_note LIKE '%(uncredited)%'
  AND g.rt_role = 'actor'
  AND g.t_production_year > 2005
  AND g.ci_title_char_id = g.ci_title_role_id
  AND mc_name.id = g.mc_type_id;
