SELECT
    pa.id            AS "commentAuthor.id",
    pa.firstName     AS "commentAuthor.firstName",
    pa.lastName      AS "commentAuthor.lastName",
    c.creationDate   AS "comment.creationDate",
    c.id             AS "comment.id",
    c.content        AS "comment.content"
FROM GRAPH_TABLE(
    G
    MATCH
        (a:Person)-[hc:HAS_CREATED_MESSAGE]->(b:Message),
        (b:Message)-[hr:HAS_REPLY]->(c:Comment),
        (c:Comment)-[cr:HAS_CREATOR]->(d:Person)
    COLUMNS (
        a.id AS a_id,
        c.id AS comment_id,
        d.id AS author_id
    )
)
JOIN Comment c
    ON c.id = comment_id
JOIN Person pa
    ON pa.id = author_id
WHERE a_id = $personId
ORDER BY
    c.creationDate DESC,
    c.id          ASC
LIMIT 20;
