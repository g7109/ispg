-- IC2: Recent messages by your friends

SELECT
  gt."b.id"                AS personId,
  gt."b.firstName"         AS personFirstName,
  gt."b.lastName"          AS personLastName,
  gt."c.id"                AS messageId,
  gt."c.contentOrImage"    AS messageContentOrImage,
  gt."c.creationDate"      AS messageCreationDate
FROM GRAPH_TABLE (
  MATCH
    (a:Person)-[:knows]->(b:Person),
    (b:Person)-[:hasCreated]->(c:Message)
  COLUMNS (
    a.id                    AS "a.id",
    b.id                    AS "b.id",
    b.firstName             AS "b.firstName",
    b.lastName              AS "b.lastName",
    c.id                    AS "c.id",
    COALESCE(c.content, c.imageFile)
                             AS "c.contentOrImage",
    c.creationDate          AS "c.creationDate"
  )
) AS gt
WHERE
  gt."a.id"           = $personId     -- corresponds to nodeByIDScan(a:person) in the .txt plan
  AND gt."c.creationDate" < $maxDate  -- corresponds to filter(func) in the .txt plan
ORDER BY
  gt."c.creationDate" DESC,
  gt."c.id"           ASC            -- corresponds to top("c.creationDate=desc,c.id=asc", 20) in the .txt plan
LIMIT 20;
