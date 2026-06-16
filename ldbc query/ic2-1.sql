SELECT g.p2_id, g.c_creationDate
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(c:COMMENT)
  COLUMNS (
    p2.id as p2_id,
    c.creationDate as c_creationDate,
    p1.id as p1_id
  )
) g
WHERE g.p1_id = $Id
  AND g.c_creationDate < $CreationDate;
