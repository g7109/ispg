WITH g AS (
    SELECT *
    FROM GRAPH_TABLE (
        G
        MATCH
            (a:Person)-[k:KNOWS_1_2]->(b:Person),
            (b:Person)-[c:WORKAT]->(d:Organisation),
            (d:Organisation)-[ol:ORG_IS_LOCATED_IN]->(e:Place)
        COLUMNS (
            a.id        AS a_id,
            b.id        AS b_id,
            b.firstName AS b_firstName,
            b.lastName  AS b_lastName,
            c.workFrom  AS workFrom,
            d.name      AS company_name,
            e.name      AS country_name
        )
    )
)
SELECT
    g.b_id         AS "otherPerson.id",
    g.b_firstName  AS "otherPerson.firstName",
    g.b_lastName   AS "otherPerson.lastName",
    g.company_name AS "company.name",
    g.workFrom     AS "workAt.workFrom"
FROM g
WHERE
    g.a_id = $personId
    AND g.b_id <> g.a_id
    AND g.country_name = $countryName
    AND g.workFrom < $workFromYear
ORDER BY
    g.workFrom     ASC,
    g.b_id         ASC,
    g.company_name DESC
LIMIT 10;
