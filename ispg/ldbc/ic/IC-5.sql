SELECT
    g.forum_title          AS forum_title,
    COUNT(DISTINCT g.post_id) AS postCount
FROM GRAPH_TABLE (
    G
    MATCH
        -- a: anchor person
        -- b: friends / friends-of-friends
        -- p: posts created by b
        -- f: forum containing the post
        (a:Person)-[:Knows*1..2]->(b:Person),
        (b:Person)-[:HasCreated]->(p:Post),
        (f:Forum)-[:ContainerOf]->(p:Post)
    COLUMNS (
        a.id    AS a_id,
        b.id    AS b_id,
        p.id    AS post_id,
        f.id    AS forum_id,
        f.title AS forum_title
    )
) AS g
JOIN Forum_hasMember_person fm
  ON fm.forumId  = g.forum_id
 AND fm.personId = g.b_id              -- only forums joined by otherPerson
WHERE
        g.a_id       = $personId           -- anchor person
        AND g.b_id  <> g.a_id              -- exclude self
        AND fm.joinDate > $minDate         -- forums joined after minDate
GROUP BY
    g.forum_id,
    g.forum_title
ORDER BY
    postCount DESC,
    g.forum_id ASC
LIMIT 20;
