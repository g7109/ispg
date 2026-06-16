SELECT MIN(g.mc_note) AS production_note,
       MIN(g.t_title) AS movie_title,
       MIN(g.t_production_year) AS movie_year
FROM GRAPH_TABLE (graph
  MATCH
    (ct:COMPANY_TYPE)<-[mc_type:MOVIE_COMPANIES_TYPE]-(t:TITLE)
  COLUMNS (
    t.id AS t_id,
    ct.kind AS ct_kind,
    mc_type.note AS mc_note,
    t.title AS t_title,
    t.production_year AS t_production_year
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id
JOIN info_type it ON it.id = mi_idx.info_type_id AND it.info = 'top 250 rank'
WHERE g.ct_kind = 'production companies'
  AND g.mc_note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'
  AND (g.mc_note LIKE '%(co-production)%'
       OR g.mc_note LIKE '%(presents)%');
