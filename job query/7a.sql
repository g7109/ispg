SELECT MIN(g.n_name) AS of_person,
       MIN(g.t_title) AS biography_movie
FROM GRAPH_TABLE (graph
  MATCH
    (an:AKA_NAME)-[:ALSO_KNOWN_AS_NAME]->(n:NAME)-[ci_name_title:CAST_INFO_NAME_TITLE]->(t:TITLE),
    (t)-[ml_movie:MOVIE_LINK_LINKED_TYPE]->(lt:LINK_TYPE)
  COLUMNS (
    n.id AS n_id,
    n.name AS n_name,
    t.title AS t_title,
    an.name AS an_name,
    lt.link AS lt_link,
    n.name_pcode_cf AS n_pcode,
    n.gender AS n_gender,
    t.production_year AS t_production_year
  ) g
)
JOIN person_info pi ON pi.person_id = g.n_id AND pi.note = 'Volker Boehm'
JOIN info_type it ON it.id = pi.info_type_id AND it.info = 'mini biography'
WHERE g.an_name LIKE '%a%'
  AND g.lt_link = 'features'
  AND g.n_pcode >= 'A'
  AND g.n_pcode <= 'F'
  AND (g.n_gender = 'm'
       OR (g.n_gender = 'f' AND g.n_name LIKE 'B%'))
  AND g.t_production_year >= 1980
  AND g.t_production_year <= 1995;
