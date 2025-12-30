SELECT
    friend_id              AS "friend.id",
    friend_firstName       AS "friend.firstName",
    friend_lastName        AS "friend.lastName",
    like_creationDate      AS "likes.creationDate",
    message_id             AS "message.id",
    message_contentOrImage AS "message.contentOrImage",
    CAST((like_creationDate - message_creationDate) / 60000 AS INTEGER)
                           AS "minutesLatency",
    FALSE                  AS "isNew"
FROM GRAPH_TABLE (
    G
    MATCH
        (a:Person)-[k:KNOWS]->(c:Person),
        (c:Person)-[e:LIKES_MESSAGE]->(b:Message)
    COLUMNS (
        a.id           AS a_id,
        b.id           AS message_id,
        b.creationDate AS message_creationDate,
        COALESCE(b.content, b.imageFile) AS message_contentOrImage,
        c.id           AS friend_id,
        c.firstName    AS friend_firstName,
        c.lastName     AS friend_lastName,
        e.creationDate AS like_creationDate
    )
)
JOIN message_hasCreator_person hc
  ON hc.personId = a_id
 AND hc.postId   = message_id
WHERE
    a_id = $personId
ORDER BY
    "likes.creationDate" DESC,
    "friend.id"          ASC
LIMIT 20;
