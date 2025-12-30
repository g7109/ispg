WITH gt AS (
    SELECT *
    FROM GRAPH_TABLE(
        G
        MATCH
            (a:Person)-[k:KNOWS_1_2]->(b:Person),
            (b:Person)-[hc:HAS_CREATED_MESSAGE]->(c:Message)
        COLUMNS (
            a.id           AS a_id,
            b.id           AS other_id,
            c.id           AS message_id,
            c.creationDate AS message_creationDate
        )
    )
)
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
FROM gt
JOIN Person  op ON op.id = gt.other_id
JOIN Message m  ON m.id = gt.message_id
WHERE gt.a_id = $personId
    AND gt.other_id <> $personId
    AND gt.message_creationDate < $maxDate
ORDER BY
    m.creationDate DESC,
    m.id           ASC
LIMIT 20;
