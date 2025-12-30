SELECT
    b_id        AS "foafPerson.id",
    b_firstName AS "foafPerson.firstName",
    b_lastName  AS "foafPerson.lastName",
    SUM(CASE WHEN x.hit = 1 THEN 1 ELSE -1 END) AS "commonInterestScore",
    b_gender    AS "foafPerson.gender",
    city_name   AS "city.name"
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[k:KNOWS_2]->(b:Person),
        (b:Person)-[hc:HAS_CREATED_POST]->(c:Post),
        (b:Person)-[pl:PERSON_IS_LOCATED_IN]->(e:Place)
    COLUMNS (
        a.id        AS a_id,
        b.id        AS b_id,
        b.firstName AS b_firstName,
        b.lastName  AS b_lastName,
        to_timestamp(b.birthday::DOUBLE / 1000.0) AS b_birthday_ts,
        b.gender    AS b_gender,
        c.id        AS c_id,
        e.name      AS city_name
    )
)
JOIN (
    SELECT
        pht.postId AS x_c_id,
        MAX(CASE WHEN hi.tagId IS NOT NULL THEN 1 ELSE 0 END) AS hit
    FROM post_hasTag_tag pht
    LEFT JOIN person_hasInterest_tag hi
      ON hi.personId = $personId
     AND hi.tagId    = pht.tagId
    GROUP BY
        pht.postId
) AS x
  ON x.x_c_id = c_id
WHERE
    a_id = $personId
    AND b_id <> a_id
    AND (
        (EXTRACT(MONTH FROM b_birthday_ts) = $month
         AND EXTRACT(DAY   FROM b_birthday_ts) >= 21)
        OR
        (EXTRACT(MONTH FROM b_birthday_ts) = (($month % 12) + 1)
         AND EXTRACT(DAY   FROM b_birthday_ts) < 22)
    )
GROUP BY
    b_id,
    b_firstName,
    b_lastName,
    b_gender,
    city_name
ORDER BY
    "commonInterestScore" DESC,
    "foafPerson.id"       ASC
LIMIT 10;
