SELECT
    g.b_id          AS "otherPerson.id",
    g.b_firstName   AS "otherPerson.firstName",
    g.b_lastName    AS "otherPerson.lastName",
    g.company_name  AS "company.name",
    g.workFrom      AS "workAt.workFrom"
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[:KNOWS*1..2]->(b:Person),
        (b:Person)-[c:WORKAT]->(d:Organisation),
        (d:Organisation)-[:IS_LOCATED_IN]->(e:Place)
    COLUMNS (
        a.id        AS a_id,
        b.id        AS b_id,
        b.firstName AS b_firstName,
        b.lastName  AS b_lastName,
        c.workFrom  AS workFrom,
        d.name      AS company_name,
        e.name      AS country_name
    )
) AS g
WHERE
    g.a_id        = $personId         -- anchor person
    AND g.b_id   <> g.a_id            -- exclude self
    AND g.country_name = $countryName -- company country
    AND g.workFrom     < $workFromYear
ORDER BY
    g.workFrom     ASC,
    g.b_id         ASC,
    g.company_name DESC
LIMIT 10;
