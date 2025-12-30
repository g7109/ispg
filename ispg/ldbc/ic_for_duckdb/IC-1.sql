WITH g AS (
    SELECT *
    FROM GRAPH_TABLE (
        G
        MATCH
            (a:Person)-[k:KNOWS_1_3]->(b:Person),
            (b:Person)-[w:WORKAT]->(c:Organisation),
            (c:Organisation)-[ol:ORG_IS_LOCATED_IN]->(d:Place)
        COLUMNS (
            a.id        AS a_id,
            b.id        AS b_id,
            b.firstName AS b_firstName,
            b.lastName  AS b_lastName,
            k.hops      AS distance,
            c.name      AS company_name,
            w.workFrom  AS work_from,
            d.name      AS company_country_name
        )
    )
),
x AS (
    SELECT
        b_id AS other_person_id,
        b_lastName AS other_last_name,
        distance AS distance_from_person,
        p.birthday AS birthday,
        p.creationDate AS creation_date,
        p.gender AS gender,
        p.browserUsed AS browser_used,
        p.locationIP AS location_ip,
        pe.email AS email,
        ps.language AS language,
        loc.name AS locationCity_name,
        u.name AS university_name,
        pso.classYear AS university_classYear,
        ucity.name AS university_city_name,
        company_name AS company_name,
        work_from AS company_workFrom,
        company_country_name AS company_country_name
    FROM g
    JOIN Person p ON p.id = g.b_id
    LEFT JOIN person_isLocatedIn_place pip ON pip.personId = p.id
    LEFT JOIN Place loc ON loc.id = pip.placeId
    LEFT JOIN person_email_emailaddress pe ON pe.Person_id = p.id
    LEFT JOIN person_speaks_language ps ON ps.Person_id = p.id
    LEFT JOIN person_studyAt_organisation pso ON pso.personId = p.id
    LEFT JOIN Organisation u ON u.id = pso.organisationId
    LEFT JOIN organisation_isLocatedIn_place oip ON oip.organisationId = u.id
    LEFT JOIN Place ucity ON ucity.id = oip.placeId
    WHERE
        a_id = $personId
        AND b_firstName = $firstName
        AND b_id <> $personId
)
SELECT
    agg.other_person_id      AS "otherPerson.id",
    agg.other_last_name      AS "otherPerson.lastName",
    agg.distance_from_person AS "distanceFromPerson",
    agg.birthday             AS "otherPerson.birthday",
    agg.creation_date        AS "otherPerson.creationDate",
    agg.gender               AS "otherPerson.gender",
    agg.browser_used         AS "otherPerson.browserUsed",
    agg.location_ip          AS "otherPerson.locationIP",
    agg.emails               AS "otherPerson.email",
    agg.speaks               AS "otherPerson.speaks",
    agg.locationCity_name    AS "locationCity.name",
    agg.universities         AS "universities",
    agg.companies            AS "companies"
FROM (
    SELECT
        other_person_id,
        other_last_name,
        distance_from_person,
        birthday,
        creation_date,
        gender,
        browser_used,
        location_ip,
        ARRAY_AGG(DISTINCT email) AS emails,
        ARRAY_AGG(DISTINCT language) AS speaks,
        MIN(locationCity_name) AS locationCity_name,
        ARRAY_AGG(DISTINCT ROW(university_name, university_classYear, university_city_name)) AS universities,
        ARRAY_AGG(DISTINCT ROW(company_name, company_workFrom, company_country_name)) AS companies
    FROM x
    GROUP BY
        other_person_id,
        other_last_name,
        distance_from_person,
        birthday,
        creation_date,
        gender,
        browser_used,
        location_ip
) AS agg
ORDER BY
    agg.distance_from_person ASC,
    agg.other_last_name ASC,
    agg.other_person_id ASC
LIMIT 20;
