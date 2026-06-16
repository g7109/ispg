SELECT MIN(g.t_title) AS complete_downey_ironman_movie
FROM GRAPH_TABLE (graph
  MATCH
    (t:TITLE)-[kt:KIND_TYPE_TITLE]->(kind_type:KIND_TYPE),
    (t)-[cc_subject:COMPLETE_CAST_SUBJECT]->(cct1:COMP_CAST_TYPE),
    (t)-[cc_status:COMPLETE_CAST_STATUS]->(cct2:COMP_CAST_TYPE),
    (chn:CHAR_NAME)<-[ci_char:CAST_INFO_TITLE_CHAR]-(t),
    (n:NAME)-[ci_name:CAST_INFO_NAME_TITLE]->(t)
  COLUMNS (
    t.id AS t_id,
    t.title AS t_title,
    cct1.kind AS cct1_kind,
    cct2.kind AS cct2_kind,
    chn.name AS chn_name,
    kind_type.kind AS kind_type_kind,
    t.production_year AS t_production_year,
    cc_subject.id AS cc_subject_id,
    cc_status.id AS cc_status_id,
    ci_char.id AS ci_char_id,
    ci_name.id AS ci_name_id
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id
  AND k.keyword IN ('superhero', 'sequel', 'second-part', 'marvel-comics',
                    'based-on-comic', 'tv-special', 'fight', 'violence')
WHERE g.cct1_kind = 'cast'
  AND g.cct2_kind LIKE '%complete%'
  AND g.chn_name NOT LIKE '%Sherlock%'
  AND (g.chn_name LIKE '%Tony%Stark%' OR g.chn_name LIKE '%Iron%Man%')
  AND g.kind_type_kind = 'movie'
  AND g.t_production_year > 1950
  AND g.cc_subject_id = g.cc_status_id
  AND g.ci_char_id = g.ci_name_id;
