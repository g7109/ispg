WITH RECURSIVE valid_tagclasses AS (
    -- Seed: the given TagClass
    SELECT id
    FROM tagclass
    WHERE name = $tagClassName

    UNION ALL

    -- Recursion: all descendant TagClasses
    SELECT tagclass_isSubclassOf_tagclass.subclassId
    FROM tagclass_isSubclassOf_tagclass, valid_tagclasses AS vtc
    WHERE tagclass_isSubclassOf_tagclass.superclassId = vtc.id
)
SELECT
    g.b_id        AS "friend.id",
    g.b_firstName AS "friend.firstName",
    g.b_lastName  AS "friend.lastName",
    ARRAY_AGG(DISTINCT g.e_name ORDER BY g.e_name)
                  AS "tagNames",
    COUNT(DISTINCT g.c_id)
                  AS "replyCount"
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[:KNOWS]->(b:Person),
        (b:Person)-[:HAS_CREATED]->(c:Comment),
        (c:Comment)-[:REPLY_OF]->(d:Post),
        (d:Post)-[:HAS_TAG]->(e:Tag)
    COLUMNS (
        a.id        AS a_id,
        b.id        AS b_id,
        b.firstName AS b_firstName,
        b.lastName  AS b_lastName,
        c.id        AS c_id,
        d.id        AS d_id,
        e.id        AS e_id,
        e.name      AS e_name
    )
) AS g
JOIN tag_hasType_tagclass AS thtt
    ON thtt.tagId = g.e_id                    -- SQL side: expand from (e:Tag) to TagClass
JOIN tagclass AS tc
    ON tc.id = thtt.tagClassId                -- expose SQL vertex f:TagClass
JOIN valid_tagclasses AS vtc
    ON vtc.id = tc.id                         -- keep only descendants of the given TagClass
WHERE
    g.a_id = $personId
GROUP BY
    g.b_id,
    g.b_firstName,
    g.b_lastName
HAVING
    COUNT(DISTINCT g.c_id) > 0
ORDER BY
    "replyCount" DESC,
    "friend.id"  ASC
LIMIT 20;
