SELECT
    pa.id            AS "commentAuthor.id",
    pa.firstName     AS "commentAuthor.firstName",
    pa.lastName      AS "commentAuthor.lastName",
    c.creationDate   AS "comment.creationDate",
    c.id             AS "comment.id",
    c.content        AS "comment.content"
FROM GRAPH_TABLE(
    MATCH
        (a:Person)-[:HAS_CREATED]->(b:Message),
        (b:Message)-[:HAS_REPLY]->(c:Comment),
        (c:Comment)-[:HAS_CREATOR]->(d:Person)
    COLUMNS (
        a.id AS a_id,
        c.id AS comment_id,
        d.id AS author_id
    )
) AS g
JOIN Comment c
  ON c.id = g.comment_id
JOIN Person pa
  ON pa.id = g.author_id
WHERE g.a_id = $personId
ORDER BY
    c.creationDate DESC,
    c.id          ASC
LIMIT 20;
