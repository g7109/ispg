SELECT g.p2_firstName, g.c_creationDate
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(pa:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(c:COMMENT)
  COLUMNS (
    p2.firstName as p2_firstName,
    c.creationDate as c_creationDate,
    p1.id as p1_id
  )
) g
WHERE g.p1_id = $Id
  AND g.c_creationDate < $CreationDate;
