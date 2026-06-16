SELECT MIN(g.chn_name) AS character_name,
       MIN(mi_idx.info) AS rating,
       MIN(g.n_name) AS playing_actor,
       MIN(g.t_title) AS complete_hero_movie
FROM GRAPH_TABLE (graph
  MATCH
    (cct1:COMP_CAST_TYPE)<-[cc_subject:COMPLETE_CAST_SUBJECT]-(t:TITLE)-[cc_status:COMPLETE_CAST_STATUS]->(cct2:COMP_CAST_TYPE),
    (t)-[:KIND_TYPE_TITLE]->(kt:KIND_TYPE),
    (chn:CHAR_NAME)<-[ci_char:CAST_INFO_TITLE_CHAR]-(t)<-[ci_name:CAST_INFO_NAME_TITLE]-(n:NAME),
    (t)-[mk:MOVIE_KEYWORD]->(k:KEYWORD)
  COLUMNS (
    t.id AS t_id,
    chn.name AS chn_name,
    n.name AS n_name,
    t.title AS t_title,
    cct1.kind AS cct1_kind,
    cct2.kind AS cct2_kind,
    k.keyword AS k_keyword,
    kt.kind AS kt_kind,
    t.production_year AS t_production_year,
    cc_subject.id AS cc_subject_id,
    cc_status.id AS cc_status_id,
    ci_char.id AS ci_char_id,
    ci_name.id AS ci_name_id
  ) g
)
JOIN movie_info_idx mi_idx ON mi_idx.movie_id = g.t_id AND mi_idx.info > '7.0'
JOIN info_type it2 ON it2.id = mi_idx.info_type_id AND it2.info = 'rating'
WHERE g.cct1_kind = 'cast'
  AND g.cct2_kind LIKE '%complete%'
  AND g.chn_name IS NOT NULL
  AND (g.chn_name LIKE '%man%' OR g.chn_name LIKE '%Man%')
  AND g.k_keyword IN ('superhero', 'marvel-comics', 'based-on-comic', 'tv-special',
                      'fight', 'violence', 'magnet', 'web', 'claw', 'laser')
  AND g.kt_kind = 'movie'
  AND g.t_production_year > 2000
  AND g.cc_subject_id = g.cc_status_id
  AND g.ci_char_id = g.ci_name_id;
