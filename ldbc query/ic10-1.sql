SELECT g.p2_id, g.p2_firstName, g.e_name
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(c:POST),
    (p2)-[:ISLOCATEDIN]->(e:PLACE),
    (p1)-[:HASINTEREST]->(d:TAG)
  COLUMNS (
    p2.id as p2_id,
    p2.firstName as p2_firstName,
    e.name as e_name,
    c.id as c_id,
    d.id as d_id,
    p1.id as p1_id
  )
) g
JOIN post_hasTag_tag pht
  ON pht.postId = g.c_id AND pht.tagId = g.d_id
WHERE g.p1_id = $Id;
