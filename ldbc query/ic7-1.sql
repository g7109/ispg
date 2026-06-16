SELECT g.p2_id, g.c_content
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(p2:PERSON)-[:LIKES]->(c:MESSAGE)
  COLUMNS (
    p1.id as p1_id,
    p2.id as p2_id,
    c.id as c_id,
    c.content as c_content
  )
) g
JOIN message_hasCreator_person hc
  ON hc.postId = g.c_id AND hc.personId = g.p1_id
WHERE g.p1_id = $Id;
