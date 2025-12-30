WITH g AS (
    SELECT *
    FROM GRAPH_TABLE (
        G
        MATCH
            (a:Person)-[k:KNOWS_1_2]->(b:Person),
            (b:Person)-[hc:HAS_CREATED_POST]->(c:Post),
            (c:Post)-[ht:POST_HAS_TAG]->(e:Tag)
        COLUMNS (
            a.id   AS a_id,
            b.id   AS b_id,
            c.id   AS post_id,
            e.id   AS otherTag_id,
            e.name AS otherTag_name
        )
    )
)
SELECT
    g.otherTag_name           AS otherTag_name,
    COUNT(DISTINCT g.post_id) AS postCount
FROM g
JOIN post_hasTag_tag pht_given
  ON pht_given.postId = g.post_id
JOIN Tag t_given
  ON t_given.id = pht_given.tagId
WHERE
    g.a_id = $personId
    AND g.b_id <> g.a_id
    AND t_given.name = $tagName
    AND g.otherTag_name <> $tagName
GROUP BY
    g.otherTag_name
ORDER BY
    postCount DESC,
    g.otherTag_name ASC
LIMIT 10;
