-- IC2: Recent messages by your friends

SELECT
  b_id             AS personId,
  b_firstName      AS personFirstName,
  b_lastName       AS personLastName,
  c_id             AS messageId,
  c_contentOrImage AS messageContentOrImage,
  c_creationDate   AS messageCreationDate
FROM GRAPH_TABLE (
  G
  MATCH
    (a:Person)-[k:KNOWS]->(b:Person),
    (b:Person)-[hc:HAS_CREATED_MESSAGE]->(c:Message)
  COLUMNS (
    a.id           AS a_id,
    b.id           AS b_id,
    b.firstName    AS b_firstName,
    b.lastName     AS b_lastName,
    c.id           AS c_id,
    COALESCE(c.content, c.imageFile) AS c_contentOrImage,
    c.creationDate AS c_creationDate
  )
)
WHERE
  a_id = $personId
  AND c_creationDate < $maxDate
ORDER BY
  c_creationDate DESC,
  c_id ASC
LIMIT 20;
