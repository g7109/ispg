SELECT
    tag_name      AS name,
    COUNT(DISTINCT post_id) AS postCount
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[k:KNOWS]->(b:Person),
        (b:Person)-[hc:HAS_CREATED_POST]->(c:Post),
        (c:Post)-[ht:POST_HAS_TAG]->(d:Tag)
    COLUMNS (
        a.id           AS a_id,
        b.id           AS b_id,
        c.id           AS post_id,
        c.creationDate AS post_creation,
        d.id           AS tag_id,
        d.name         AS tag_name
    )
) 
LEFT JOIN person_knows_person ke
    ON ke.person1Id = a_id
LEFT JOIN Person e
    ON e.id = ke.person2Id
LEFT JOIN post_hasCreator_person hc
     ON hc.personId = e.id
LEFT JOIN Post f
     ON f.id = hc.postId
 AND f.creationDate < $startDate
LEFT JOIN post_hasTag_tag pht_old
    ON pht_old.postId = f.id
 AND pht_old.tagId = tag_id
WHERE
    a_id          = $personId
    AND post_creation >= $startDate
    AND post_creation <  $endDate
    AND pht_old.tagId IS NULL
GROUP BY
    tag_id,
    tag_name
ORDER BY
    postCount DESC,
    tag_name ASC
LIMIT 10;
