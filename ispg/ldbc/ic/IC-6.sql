SELECT
    g.otherTag_name AS otherTag_name,
    COUNT(DISTINCT g.post_id) AS postCount
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[:Knows*1..2]->(b:Person),
        (b:Person)-[:HasCreated]->(c:Post),
        (c:Post)-[:HasTag]->(e:Tag)
    COLUMNS (
        a.id   AS a_id,
        b.id   AS b_id,
        c.id   AS post_id,
        e.id   AS otherTag_id,
        e.name AS otherTag_name
    )
) AS g
JOIN post_hasTag_tag pht_given
  ON pht_given.postId = g.post_id
JOIN tag t_given
  ON t_given.id = pht_given.tagId
WHERE
    g.a_id          = $personId          -- anchor Person
    AND g.b_id     <> g.a_id             -- exclude self; keep friends/foaf only
    AND t_given.name = $tagName          -- the post must contain the given tag
    AND g.otherTag_name <> $tagName      -- otherTag must not be the given tag itself
GROUP BY
    g.otherTag_name
ORDER BY
    postCount      DESC,
    g.otherTag_name ASC
LIMIT 10;
