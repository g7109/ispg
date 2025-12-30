WITH g AS (
    SELECT *
    FROM GRAPH_TABLE (
        G
        MATCH
            (a:Person)-[k:KNOWS_1_2]->(b:Person),
            (b:Person)-[hc:HAS_CREATED_POST]->(p:Post),
            (f:Forum)-[co:CONTAINER_OF]->(p:Post)
        COLUMNS (
            a.id    AS a_id,
            b.id    AS b_id,
            p.id    AS post_id,
            f.id    AS forum_id,
            f.title AS forum_title
        )
    )
)
SELECT
    g.forum_title             AS forum_title,
    COUNT(DISTINCT g.post_id) AS postCount
FROM g
JOIN Forum_hasMember_person fm
  ON fm.forumId  = g.forum_id
 AND fm.personId = g.b_id
WHERE
    g.a_id      = $personId
    AND g.b_id <> g.a_id
    AND fm.joinDate > $minDate
GROUP BY
    g.forum_id,
    g.forum_title
ORDER BY
    postCount DESC,
    g.forum_id ASC
LIMIT 20;
