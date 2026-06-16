SELECT MIN(g.chn_name) AS voiced_char,
       MIN(g.n_name) AS voicing_actress,
       MIN(g.t_title) AS voiced_animation
FROM GRAPH_TABLE (graph
  MATCH
    (cct1:COMP_CAST_TYPE)<-[cc_subject:COMPLETE_CAST_SUBJECT]-(t:TITLE)-[cc_status:COMPLETE_CAST_STATUS]->(cct2:COMP_CAST_TYPE),
    (chn:CHAR_NAME)<-[ci_char:CAST_INFO_TITLE_CHAR]-(t)<-[ci_name:CAST_INFO_NAME_TITLE]-(n:NAME),
    (cn:COMPANY_NAME)<-[mc_name:MOVIE_COMPANIES_NAME]-(t),
    (t)-[mi:MOVIE_INFO]->(it:INFO_TYPE),
    (n)-[pi:PERSON_INFO]->(it3:INFO_TYPE),
    (n)-[ci_role:CAST_INFO_NAME_ROLE]->(rt:ROLE_TYPE),
    (n)<-[:ALSO_KNOWN_AS_NAME]->(an:AKA_NAME)
  COLUMNS (
    t.id AS t_id,
    chn.name AS chn_name,
    n.name AS n_name,
    t.title AS t_title,
    cct1.kind AS cct1_kind,
    cct2.kind AS cct2_kind,
    ci_char.note AS ci_char_note,
    cn.country_code AS cn_country_code,
    it.info AS it_info,
    it3.info AS it3_info,
    mi.info AS mi_info,
    n.gender AS n_gender,
    rt.role AS rt_role,
    t.production_year AS t_production_year,
    cc_subject.id AS cc_subject_id,
    cc_status.id AS cc_status_id,
    ci_char.id AS ci_char_id,
    ci_name.id AS ci_name_id,
    ci_role.id AS ci_role_id
  ) g
)
JOIN movie_keyword mk ON mk.movie_id = g.t_id
JOIN keyword k ON k.id = mk.keyword_id AND k.keyword = 'computer-animation'
WHERE g.cct1_kind = 'cast'
  AND g.cct2_kind = 'complete+verified'
  AND g.chn_name = 'Queen'
  AND g.ci_char_note IN ('(voice)', '(voice) (uncredited)', '(voice: English version)')
  AND g.cn_country_code = '[us]'
  AND g.it_info = 'release dates'
  AND g.it3_info = 'trivia'
  AND g.mi_info IS NOT NULL
  AND (g.mi_info LIKE 'Japan:%200%' OR g.mi_info LIKE 'USA:%200%')
  AND g.n_gender = 'f'
  AND g.n_name LIKE '%An%'
  AND g.rt_role = 'actress'
  AND g.t_title = 'Shrek 2'
  AND g.t_production_year >= 2000
  AND g.t_production_year <= 2010
  AND g.cc_subject_id = g.cc_status_id
  AND g.ci_char_id = g.ci_name_id
  AND g.ci_name_id = g.ci_role_id;
