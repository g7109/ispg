WITH RECURSIVE valid_tagclasses AS (
    SELECT id
    FROM TagClass
    WHERE name = $tagClassName

    UNION ALL

    SELECT tis.subclassId
    FROM tagclass_isSubclassOf_tagclass tis, valid_tagclasses AS vtc
    WHERE tis.superclassId = vtc.id
)
SELECT
    b_id        AS "friend.id",
    b_firstName AS "friend.firstName",
    b_lastName  AS "friend.lastName",
    ARRAY_AGG(DISTINCT e_name ORDER BY e_name)
                  AS "tagNames",
    COUNT(DISTINCT c_id)
                  AS "replyCount"
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[k:KNOWS]->(b:Person),
        (b:Person)-[hc:HAS_CREATED_COMMENT]->(c:Comment),
        (c:Comment)-[ro:REPLY_OF]->(d:Post),
        (d:Post)-[ht:POST_HAS_TAG]->(e:Tag)
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
) 
JOIN tag_hasType_tagclass AS thtt
    ON thtt.tagId = e_id
JOIN TagClass AS tc
    ON tc.id = thtt.tagClassId
JOIN valid_tagclasses AS vtc
    ON vtc.id = tc.id
WHERE
    a_id = $personId
GROUP BY
    b_id,
    b_firstName,
    b_lastName
HAVING
    COUNT(DISTINCT c_id) > 0
ORDER BY
    "replyCount" DESC,
    "friend.id"  ASC
LIMIT 20;
