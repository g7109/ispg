SELECT MIN(g.an_name) AS cool_actor_pseudonym,
       MIN(g.t_title) AS series_named_after_char
FROM GRAPH_TABLE (graph
  MATCH
    (an:AKA_NAME)-[:ALSO_KNOWN_AS_NAME]->(n:NAME)-[ci_name:CAST_INFO_NAME_TITLE]->(t:TITLE),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t)
  COLUMNS (
    t.id AS t_id,
    an.name AS an_name,
    t.title AS t_title,
    cn.country_code AS cn_country_code,
    t.episode_nr AS t_episode_nr
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'character-name-in-title'
WHERE g.cn_country_code = '[us]'
  AND g.t_episode_nr >= 50
  AND g.t_episode_nr < 100;
