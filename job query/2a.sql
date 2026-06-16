SELECT MIN(g.t_title) as movie_title
FROM GRAPH_TABLE (graph
  MATCH
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t:TITLE)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    cn.country_code AS cn_country_code
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'character-name-in-title'
WHERE g.cn_country_code = '[de]';
