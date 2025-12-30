SELECT
    op.id          AS "otherPerson.id",
    op.firstName   AS "otherPerson.firstName",
    op.lastName    AS "otherPerson.lastName",
    m.id           AS "message.id",
    CASE
        WHEN m.content IS NOT NULL THEN m.content
        ELSE m.imageFile
    END            AS "message.contentOrImage",
    m.creationDate AS "message.creationDate"
FROM GRAPH_TABLE(
    MATCH
        (a:Person)-[:KNOWS*1..2]->(b:Person),
        (b:Person)-[:HAS_CREATED]->(c:Message)
    COLUMNS (
        a.id          AS a_id,
        b.id          AS other_id,
        c.id          AS message_id,
        c.creationDate AS message_creationDate
    )
) AS g
JOIN Person  op ON op.id = g.other_id
JOIN Message m  ON m.id = g.message_id
WHERE g.a_id = $personId
  AND g.other_id <> $personId
  AND g.message_creationDate < $maxDate
ORDER BY
    m.creationDate DESC,
    m.id           ASC
LIMIT 20;
