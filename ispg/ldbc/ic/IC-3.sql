SELECT
    gt.b_id            AS otherPersonId,
    gt.b_firstName     AS otherPersonFirstName,
    gt.b_lastName      AS otherPersonLastName,
    COUNT(DISTINCT CASE WHEN g.name = $countryXName THEN gt.e_id END) AS xCount,
    COUNT(DISTINCT CASE WHEN g.name = $countryYName THEN gt.e_id END) AS yCount,
    COUNT(DISTINCT gt.e_id)                                           AS count
FROM GRAPH_TABLE (
  -- Graph side: a -> b (knows*1..2), b -> e (hasCreated), and e -> f (isLocatedIn)
    MATCH (a:Person)-[:KNOWS*1..2]->(b:Person),
          (b:Person)-[:HAS_CREATED]->(e:Message),
          (e:Message)-[:IS_LOCATED_IN]->(f:Place)

    COLUMNS (
        a.id           AS a_id,
        b.id           AS b_id,
        b.firstName    AS b_firstName,
        b.lastName     AS b_lastName,
        e.id           AS e_id,
        e.creationDate AS e_creationDate,
        f.id           AS f_id
    )
) AS gt
    -- Everything below are relationship joins outside MATCH (RelGo/ISPG may reorder them)

    -- Message country: e -> f(city) -> g(country)
    JOIN place_isPartOf_place pf
      ON pf.placeId = gt.f_id
    JOIN place g
      ON g.id = pf.parentPlaceId      -- g = messageCountry

    -- Person country: b -> c(city) -> d(country)
    JOIN person_isLocatedIn_place pe
      ON pe.personId = gt.b_id
    JOIN place c
      ON c.id = pe.placeId
    JOIN place_isPartOf_place pc
      ON pc.placeId = c.id
    JOIN place d
      ON d.id = pc.parentPlaceId      -- d = personCountry
WHERE
    -- Anchor personId is constrained only in WHERE
    gt.a_id = $personId

    -- Time window: message creationDate in [startDate, endDate)
    AND gt.e_creationDate >= $startDate
    AND gt.e_creationDate <  $endDate

    -- Messages must be posted in either country X or country Y
    AND g.name IN ($countryXName, $countryYName)

    -- People must be "foreigners": residence country is not X/Y
    AND d.name NOT IN ($countryXName, $countryYName)
GROUP BY
    gt.b_id, gt.b_firstName, gt.b_lastName
HAVING
    -- Require at least one message in both countries X and Y
    COUNT(DISTINCT CASE WHEN g.name = $countryXName THEN gt.e_id END) > 0
    AND COUNT(DISTINCT CASE WHEN g.name = $countryYName THEN gt.e_id END) > 0
ORDER BY
    count DESC,
    gt.b_id ASC
LIMIT 20;
