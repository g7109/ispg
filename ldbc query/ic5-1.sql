SELECT g.f_title
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(m:POST),
    (f:FORUM)-[:CONTAINEROF]->(m)
  COLUMNS (
    f.id as f_id,
    f.title as f_title,
    p2.id as p2_id,
    p1.id as p1_id
  )
) g
JOIN forum_hasMember_person fm
  ON fm.forumId = g.f_id AND fm.personId = g.p2_id AND fm.joinDate >= $JoinDate
WHERE g.p1_id = $Id;
