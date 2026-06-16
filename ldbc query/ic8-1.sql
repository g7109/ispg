SELECT g.p2_id, g.c_content
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)<-[:HASCREATOR]-(ps:POST)<-[:REPLYOF]-(c:COMMENT)-[:HASCREATOR]->(p2:PERSON)
  COLUMNS (
    p2.id as p2_id,
    c.content as c_content,
    p1.id as p1_id
  )
) g
WHERE g.p1_id = $Id;
