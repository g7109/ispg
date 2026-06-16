SELECT MIN(g.n_name) AS member_in_charnamed_american_movie,
       MIN(g.n_name) AS a1
FROM GRAPH_TABLE (graph
  MATCH
    (n:NAME)-[ci_name_title:CAST_INFO_NAME_TITLE]->(t:TITLE),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t)
  COLUMNS (
    t.id AS t_id,
    n.name AS n_name,
    cn.country_code AS cn_country_code
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'character-name-in-title'
WHERE g.cn_country_code = '[us]'
  AND g.n_name LIKE 'B%';
