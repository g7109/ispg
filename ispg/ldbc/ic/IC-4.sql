SELECT
    g.tag_name      AS name,
    COUNT(DISTINCT g.post_id) AS postCount
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[:Knows]->(b:Person),
        (b:Person)-[:HasCreated]->(c:Post),
        (c:Post)-[:HasTag]->(d:Tag)
    COLUMNS (
        a.id           AS a_id,
        b.id           AS b_id,
        c.id           AS post_id,
        c.creationDate AS post_creation,
        d.id           AS tag_id,
        d.name         AS tag_name
    )
) AS g
LEFT JOIN person_knows_person ke
    ON ke.person1Id = g.a_id                    -- (a:Person)-[knows]->(e:Person)
LEFT JOIN person e
    ON e.id = ke.person2Id                      -- e: SQL vertex (friend)
LEFT JOIN post_hasCreator_person hc
     ON hc.personId = e.id                      -- (e:Person)-[:HasCreated]->(f:Post)
LEFT JOIN post f
     ON f.id = hc.postId
 AND f.creationDate < $startDate              -- only consider posts before the time window
LEFT JOIN post_hasTag_tag pht_old
    ON pht_old.postId = f.id
 AND pht_old.tagId = g.tag_id                 -- hit if an old post already contains this tag
WHERE
    g.a_id          = $personId                        -- anchor filter (nodeByIDScan(a))
    AND g.post_creation >= $startDate                  -- func_filter_by_post_one
    AND g.post_creation <  $endDate                    -- func_filter_by_post_two
        AND pht_old.tagId IS NULL                      -- a "new" topic not seen before
GROUP BY
    g.tag_id,
    g.tag_name
ORDER BY
    postCount DESC,
    g.tag_name ASC
LIMIT 10;
