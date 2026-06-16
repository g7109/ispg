SELECT MIN(g.an1_name) AS actress_pseudonym,
       MIN(g.t_title) AS japanese_movie_dubbed
FROM GRAPH_TABLE (graph
  MATCH
    (an1:AKA_NAME)-[:ALSO_KNOWN_AS_NAME]->(n1:NAME),
    (n1)-[ci_name_role:CAST_INFO_NAME_ROLE]->(rt:ROLE_TYPE),
    (n1)-[ci_name_title:CAST_INFO_NAME_TITLE]->(t:TITLE)
  COLUMNS (
    t.id AS t_id,
    an1.name AS an1_name,
    t.title AS t_title,
    ci_name_title.note AS ci_name_title_note,
    n1.name AS n1_name,
    rt.role AS rt_role,
    ci_name_role.id AS ci_name_role_id,
    ci_name_title.id AS ci_name_title_id
  ) g
)
JOIN movie_companies mc_name ON mc_name.movie_id = g.t_id
  AND mc_name.note LIKE '%(Japan)%'
  AND mc_name.note NOT LIKE '%(USA)%'
JOIN company_name cn ON cn.id = mc_name.company_id AND cn.country_code = '[jp]'
WHERE g.ci_name_title_note = '(voice: English version)'
  AND g.n1_name LIKE '%Yo%'
  AND g.n1_name NOT LIKE '%Yu%'
  AND g.rt_role = 'actress'
  AND g.ci_name_role_id = g.ci_name_title_id;
