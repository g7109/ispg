SELECT
    g.friend_id                  AS "friend.id",
    g.friend_firstName           AS "friend.firstName",
    g.friend_lastName            AS "friend.lastName",
    g.like_creationDate          AS "likes.creationDate",
    g.message_id                 AS "message.id",
    g.message_contentOrImage     AS "message.contentOrImage",
    -- Latency in minutes: like time - message time
    (EXTRACT(EPOCH FROM (g.like_creationDate - g.message_creationDate)) / 60)::INT
                                 AS "minutesLatency",
    -- KNOWS is guaranteed in MATCH, so isNew is always FALSE
    FALSE                         AS "isNew"
FROM GRAPH_TABLE (
    G
    MATCH
        -- a: anchor person
        -- c: friend (connected to a via KNOWS)
        -- b: message liked by friend
        (a:Person)-[:KNOWS]->(c:Person),
        (c:Person)-[e:likes]->(b:Message)
    COLUMNS (
        a.id                      AS a_id,
        b.id                      AS message_id,
        b.creationDate            AS message_creationDate,
        COALESCE(b.content, b.imageFile)
                                  AS message_contentOrImage,
        c.id                      AS friend_id,
        c.firstName               AS friend_firstName,
        c.lastName                AS friend_lastName,
        e.creationDate            AS like_creationDate
    )
) AS g
-- Close the triangle: require the message to be created by a
JOIN message_hasCreator_person hc
  ON hc.personId = g.a_id
 AND hc.postId   = g.message_id
WHERE
    g.a_id = $personId                 -- anchor personId (kept in WHERE)
ORDER BY
    "likes.creationDate" DESC,
    "friend.id"          ASC
LIMIT 20;
