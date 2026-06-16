SELECT g.p2_id, g.o_name
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(p2:PERSON)-[pc:WORKAT]->(o:ORGANISATION)-[:ISLOCATEDIN]->(pl:PLACE)
  COLUMNS (
    p2.id as p2_id,
    o.name as o_name,
    p1.id as p1_id,
    pc.workFrom as pc_workFrom
  )
) g
WHERE g.p1_id = $Id
  AND g.pc_workFrom < $WorkFromYear;
