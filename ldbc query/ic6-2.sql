SELECT g.t2_name
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(pa:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(m:POST)-[:HASTAG]->(t2:TAG)
  COLUMNS (
    m.id as m_id,
    t2.name as t2_name,
    p1.id as p1_id
  )
) g
JOIN post_hasTag_tag pht ON pht.postId = g.m_id
JOIN tag tg ON tg.id = pht.tagId AND tg.name = $TagName
WHERE g.p1_id = $Id
  AND g.t2_name <> $TagName;
