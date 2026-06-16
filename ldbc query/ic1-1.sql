SELECT g.p2_id, pl.name AS pl_name
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(p2:PERSON)
  COLUMNS (
    p2.id as p2_id,
    p1.id as p1_id,
    p2.firstName as p2_firstName
  )
) g
JOIN person_isLocatedIn_place pip ON pip.personId = g.p2_id
JOIN place pl ON pl.id = pip.placeId
WHERE g.p1_id = $Id
  AND g.p2_firstName = $FirstName;
