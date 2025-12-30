WITH gt AS MATERIALIZED (
    SELECT *
    FROM GRAPH_TABLE (
        G
        MATCH
            (a:Person)-[k:KNOWS_1_2]->(b:Person),
            (b:Person)-[hc:HAS_CREATED_MESSAGE]->(e:Message),
            (e:Message)-[il:MESSAGE_IS_LOCATED_IN]->(f:Place)
        COLUMNS (
            a.id           AS a_id,
            b.id           AS b_id,
            b.firstName    AS b_firstName,
            b.lastName     AS b_lastName,
            e.id           AS e_id,
            e.creationDate AS e_creationDate,
            f.id           AS f_id
        )
    )
)
SELECT
    gt.b_id        AS otherPersonId,
    gt.b_firstName AS otherPersonFirstName,
    gt.b_lastName  AS otherPersonLastName,
    COUNT(DISTINCT CASE WHEN g.name = $countryXName THEN gt.e_id END) AS xCount,
    COUNT(DISTINCT CASE WHEN g.name = $countryYName THEN gt.e_id END) AS yCount,
    COUNT(DISTINCT gt.e_id)                                           AS count
FROM gt
JOIN place_isPartOf_place pf
  ON pf.placeId = gt.f_id
JOIN Place g
  ON g.id = pf.parentPlaceId
JOIN person_isLocatedIn_place pe
  ON pe.personId = gt.b_id
JOIN Place c
  ON c.id = pe.placeId
JOIN place_isPartOf_place pc
  ON pc.placeId = c.id
JOIN Place d
  ON d.id = pc.parentPlaceId
WHERE
    gt.a_id = $personId
    AND gt.e_creationDate >= $startDate
    AND gt.e_creationDate <  $endDate
    AND g.name IN ($countryXName, $countryYName)
    AND d.name NOT IN ($countryXName, $countryYName)
GROUP BY
    gt.b_id, gt.b_firstName, gt.b_lastName
HAVING
    COUNT(DISTINCT CASE WHEN g.name = $countryXName THEN gt.e_id END) > 0
    AND COUNT(DISTINCT CASE WHEN g.name = $countryYName THEN gt.e_id END) > 0
ORDER BY
    count DESC,
    gt.b_id ASC
LIMIT 20;
