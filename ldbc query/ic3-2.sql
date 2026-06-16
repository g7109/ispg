SELECT g.p2_id
FROM GRAPH_TABLE (graph
  MATCH
    (p1:PERSON)-[:KNOWS]-(pa:PERSON)-[:KNOWS]-(p2:PERSON)<-[:HASCREATOR]-(c1:COMMENT),
    (p2)<-[:HASCREATOR]-(c2:COMMENT)
  COLUMNS (
    p2.id as p2_id,
    c1.id as c1_id,
    c2.id as c2_id,
    p1.id as p1_id,
    c1.creationDate as c1_creationDate,
    c2.creationDate as c2_creationDate
  )
) g
JOIN comment_isLocatedIn_place cip1 ON cip1.commentId = g.c1_id
JOIN place pl1 ON pl1.id = cip1.placeId AND pl1.name = $Name1
JOIN comment_isLocatedIn_place cip2 ON cip2.commentId = g.c2_id
JOIN place pl2 ON pl2.id = cip2.placeId AND pl2.name = $Name2
WHERE g.p1_id = $Id
  AND g.c1_creationDate >= $CreationDateStart AND g.c1_creationDate < $CreationDateEnd
  AND g.c2_creationDate >= $CreationDateStart AND g.c2_creationDate < $CreationDateEnd;
