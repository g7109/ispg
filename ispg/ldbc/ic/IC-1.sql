SELECT
    agg.other_person_id             AS "otherPerson.id",
    agg.other_last_name             AS "otherPerson.lastName",
    agg.distance_from_person        AS "distanceFromPerson",
    agg.birthday                    AS "otherPerson.birthday",
    agg.creation_date               AS "otherPerson.creationDate",
    agg.gender                      AS "otherPerson.gender",
    agg.browser_used                AS "otherPerson.browserUsed",
    agg.location_ip                 AS "otherPerson.locationIP",
    agg.emails                      AS "otherPerson.email",
    agg.speaks                      AS "otherPerson.speaks",
    agg.locationCity_name           AS "locationCity.name",
    agg.universities                AS "universities",
    agg.companies                   AS "companies"
FROM (
    -- Aggregation layer corresponding to reduceByKey(b.id, distance, ...)
    SELECT
        x.other_person_id,
        x.other_last_name,
        x.distance_from_person,
        x.birthday,
        x.creation_date,
        x.gender,
        x.browser_used,
        x.location_ip,

        ARRAY_AGG(DISTINCT x.email)      AS emails,
        ARRAY_AGG(DISTINCT x.language)   AS speaks,

        MIN(x.locationCity_name)         AS locationCity_name,

        ARRAY_AGG(
            DISTINCT ROW(
                x.university_name,
                x.university_classYear,
                x.university_city_name
            )
        )                                AS universities,

        ARRAY_AGG(
            DISTINCT ROW(
                x.company_name,
                x.company_workFrom,
                x.company_country_name
            )
        )                                AS companies
    FROM (
        -- Detail layer: one MATCH, the rest are JOINs
        SELECT
            g."b.id"            AS other_person_id,
            g."b.firstName"     AS other_first_name,
            g."b.lastName"      AS other_last_name,
            g."distance"        AS distance_from_person,

            p.birthday          AS birthday,
            p.creationDate      AS creation_date,
            p.gender            AS gender,
            p.browserUsed       AS browser_used,
            p.locationIP        AS location_ip,

            pe.email            AS email,
            ps.language         AS language,

            loc.name            AS locationCity_name,

            u.name              AS university_name,
            pso.classYear       AS university_classYear,
            ucity.name          AS university_city_name,

            g.company_name      AS company_name,
            g.work_from         AS company_workFrom,
            g.company_country_name AS company_country_name
        FROM GRAPH_TABLE (
            social_graph
            MATCH
                -- VarExpand knows 1..3 hops: a -> b
                PATH kn_path = (a:Person)-[:knows*1..3]->(b:Person),

                -- Workplace and its country for b: b -> c(Company) -> d(Country)
                (b)-[w:workAt]->(c:Organisation),
                (c:Organisation)-[:isLocatedIn]->(d:Place)
            COLUMNS (
                a.id                   AS "a.id",
                b.id                   AS "b.id",
                b.firstName            AS "b.firstName",
                b.lastName             AS "b.lastName",
                CARDINALITY(kn_path)   AS "distance",

                c.id                   AS "c.id",
                c.name                 AS "company_name",
                w.workFrom             AS "work_from",
                d.name                 AS "company_country_name"
            )
        ) AS g

         -- Person scalar attributes
        JOIN Person p
          ON p.id = g."b.id"

         -- City where b is located: person_isLocatedIn_place + Place
        LEFT JOIN person_isLocatedIn_place pip
               ON pip.Person_id = p.id
        LEFT JOIN Place loc
               ON loc.id = pip.Place_id

         -- email / speaks
        LEFT JOIN person_email_emailaddress pe
               ON pe.Person_id = p.id
        LEFT JOIN person_speaks_language ps
               ON ps.Person_id = p.id

         -- University: b -[studyAt]-> org -> city
        LEFT JOIN person_studyAt_organisation pso
               ON pso.Person_id = p.id
        LEFT JOIN Organisation u
               ON u.id = pso.Organisation_id
        LEFT JOIN organisation_isLocatedIn_place oip
               ON oip.Organisation_id = u.id
        LEFT JOIN Place ucity
               ON ucity.id = oip.Place_id

        WHERE
            g."a.id"         = $personId         -- Anchor person id
        AND g."b.firstName"  = $firstName        -- Filter by target firstName
        AND g."b.id"        <> $personId         -- Exclude the anchor person (per LDBC spec)
    ) AS x
    GROUP BY
        x.other_person_id,
        x.other_last_name,
        x.distance_from_person,
        x.birthday,
        x.creation_date,
        x.gender,
        x.browser_used,
        x.location_ip
) AS agg
ORDER BY
    agg.distance_from_person ASC,
    agg.other_last_name      ASC,
    agg.other_person_id      ASC
LIMIT 20;
