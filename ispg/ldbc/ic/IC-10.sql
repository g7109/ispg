SELECT
    g.b_id        AS "foafPerson.id",
    g.b_firstName AS "foafPerson.firstName",
    g.b_lastName  AS "foafPerson.lastName",

    -- commonInterestScore = (#posts matching interests) - (#posts not matching interests)
    SUM(
        CASE
            WHEN x.hit = 1 THEN 1
            ELSE -1
        END
    )             AS "commonInterestScore",

    g.b_gender    AS "foafPerson.gender",
    g.city_name   AS "city.name"
FROM GRAPH_TABLE (
    G
    MATCH
        -- Exactly two hops: keep only 2-hop neighbors (not 1..2)
        -- If your implementation does not support *2, replace with *2..2 or {2}
        (a:Person)-[:KNOWS*2]->(b:Person),
        (b:Person)-[:HAS_CREATED]->(c:Post),
        (b:Person)-[:IS_LOCATED_IN]->(e:Place)
    COLUMNS (
        a.id        AS a_id,
        b.id        AS b_id,
        b.firstName AS b_firstName,
        b.lastName  AS b_lastName,
        b.birthday  AS b_birthday,
        b.gender    AS b_gender,
        c.id        AS c_id,
        e.name      AS city_name
    )
) AS g
-- SQL side: implement (c:Post)-[:HAS_TAG]->(d:Tag) and check against a's interests
JOIN (
    SELECT
        pht.postId AS c_id,
        MAX(CASE WHEN hi.tagId IS NOT NULL THEN 1 ELSE 0 END) AS hit
    FROM post_hasTag_tag pht
    LEFT JOIN person_hasInterest_tag hi
      ON hi.personId = $personId
     AND hi.tagId    = pht.tagId
    GROUP BY
        pht.postId
) AS x
  ON x.c_id = g.c_id
WHERE
    g.a_id = $personId                 -- anchor person
    AND g.b_id <> g.a_id               -- exclude self

    -- Birthday falls into the given "zodiac window": from day 21 of month to day <22 of next month
    AND (
        (EXTRACT(MONTH FROM g.b_birthday) = $month
         AND EXTRACT(DAY   FROM g.b_birthday) >= 21)
        OR
        (EXTRACT(MONTH FROM g.b_birthday) = (($month % 12) + 1)
         AND EXTRACT(DAY   FROM g.b_birthday) < 22)
    )
GROUP BY
    g.b_id,
    g.b_firstName,
    g.b_lastName,
    g.b_gender,
    g.city_name
ORDER BY
    "commonInterestScore" DESC,
    "foafPerson.id"       ASC
LIMIT 10;
