SELECT g.f_id, g.f_firstName
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(f:PERSON)<-[:HASCREATOR]-(c:COMMENT)-[:REPLYOF]->(ps:POST)-[:HASTAG]->(t:TAG)
  COLUMNS (
    f.id as f_id,
    f.firstName as f_firstName,
    t.id as t_id,
    p1.id as p1_id
  )
) g
JOIN tag_hasType_tagclass thtt ON thtt.tagId = g.t_id
JOIN tagclass tc ON tc.id = thtt.tagClassId AND tc.name = $TagClassName
WHERE g.p1_id = $Id;
