SELECT g.t_name
FROM GRAPH_TABLE (graph
  MATCH
    (pa:PERSON)-[:KNOWS]-(p1:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(ps:POST)-[:HASTAG]->(t:TAG)
  COLUMNS (
    t.name as t_name,
    p1.id as p1_id,
    ps.creationDate as ps_creationDate
  )
) g
WHERE g.p1_id = $Id
  AND g.ps_creationDate >= $CreationDateStart AND g.ps_creationDate < $CreationDateEnd;
