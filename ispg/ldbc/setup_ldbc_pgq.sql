-- Idempotent setup for LDBC sf1 SQL/PGQ in DuckDB
-- - Loads sf1 dynamic/static CSVs
-- - Creates relational-style views with convenient column names (personId/postId/tagId...)
-- - Defines PROPERTY GRAPH G used by GRAPH_TABLE

LOAD duckpgq;
PRAGMA threads=1;
PRAGMA temp_directory='/home/liyw/tmp/duckdb';

-- -----------------------------
-- Vertex tables (keep original columns; add vid=id)
-- -----------------------------
CREATE TABLE IF NOT EXISTS Person AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Message AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/dynamic/message_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Post AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/dynamic/post_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Comment AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/dynamic/comment_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Forum AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/dynamic/forum_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Organisation AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/static/organisation_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Place AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/static/place_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS Tag AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/static/tag_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS TagClass AS
SELECT id::BIGINT AS vid, *
FROM read_csv_auto('datasets/ldbc/sf1/static/tagclass_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

-- -----------------------------
-- Raw edge tables (as read from CSV)
-- -----------------------------
CREATE TABLE IF NOT EXISTS person_knows_person_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_knows_person_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS person_workAt_organisation_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_workAt_organisation_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS person_studyAt_organisation_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_studyAt_organisation_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS person_isLocatedIn_place_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_isLocatedIn_place_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS organisation_isLocatedIn_place_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/static/organisation_isLocatedIn_place_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS message_hasCreator_person_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/message_hasCreator_person_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS comment_hasCreator_person_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/comment_hasCreator_person_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS post_hasCreator_person_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/post_hasCreator_person_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS post_hasTag_tag_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/post_hasTag_tag_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS message_isLocatedIn_place_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/message_isLocatedIn_place_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS forum_containerOf_post_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/forum_containerOf_post_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS forum_hasMember_person_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/forum_hasMember_person_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS person_hasInterest_tag_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_hasInterest_tag_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS person_likes_message_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/person_likes_message_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS comment_replyOf_message_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/comment_replyOf_message_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS comment_replyOf_post_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/dynamic/comment_replyOf_post_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS tag_hasType_tagclass_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/static/tag_hasType_tagclass_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS tagclass_isSubclassOf_tagclass_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/static/tagclass_isSubclassOf_tagclass_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

CREATE TABLE IF NOT EXISTS place_isPartOf_place_raw AS
SELECT * FROM read_csv_auto('datasets/ldbc/sf1/static/place_isPartOf_place_0_0.csv', delim='|', header=true, ignore_errors=true, sample_size=-1);

-- -----------------------------
-- Relational convenience views (match your handwritten SQL column names)
-- -----------------------------
CREATE OR REPLACE VIEW person_knows_person AS
SELECT
  "Person.id"::BIGINT      AS person1Id,
  "Person.id_1"::BIGINT    AS person2Id,
  creationDate::BIGINT     AS creationDate
FROM person_knows_person_raw;

CREATE OR REPLACE VIEW person_workAt_organisation AS
SELECT
  "Person.id"::BIGINT        AS personId,
  "Organisation.id"::BIGINT  AS organisationId,
  workFrom::INT              AS workFrom
FROM person_workAt_organisation_raw;

CREATE OR REPLACE VIEW person_studyAt_organisation AS
SELECT
  "Person.id"::BIGINT        AS personId,
  "Organisation.id"::BIGINT  AS organisationId,
  classYear::INT             AS classYear
FROM person_studyAt_organisation_raw;

CREATE OR REPLACE VIEW person_isLocatedIn_place AS
SELECT
  "Person.id"::BIGINT      AS personId,
  "Place.id"::BIGINT       AS placeId
FROM person_isLocatedIn_place_raw;

CREATE OR REPLACE VIEW organisation_isLocatedIn_place AS
SELECT
  "Organisation.id"::BIGINT AS organisationId,
  "Place.id"::BIGINT        AS placeId
FROM organisation_isLocatedIn_place_raw;

-- Note: message_hasCreator_person CSV uses Post.id as the message id column name.
CREATE OR REPLACE VIEW message_hasCreator_person AS
SELECT
  "Post.id"::BIGINT   AS postId,
  "Person.id"::BIGINT AS personId
FROM message_hasCreator_person_raw;

CREATE OR REPLACE VIEW post_hasCreator_person AS
SELECT
  "Post.id"::BIGINT   AS postId,
  "Person.id"::BIGINT AS personId
FROM post_hasCreator_person_raw;

CREATE OR REPLACE VIEW comment_hasCreator_person AS
SELECT
  "Comment.id"::BIGINT AS commentId,
  "Person.id"::BIGINT  AS personId
FROM comment_hasCreator_person_raw;

CREATE OR REPLACE VIEW post_hasTag_tag AS
SELECT
  "Post.id"::BIGINT AS postId,
  "Tag.id"::BIGINT  AS tagId
FROM post_hasTag_tag_raw;

CREATE OR REPLACE VIEW message_isLocatedIn_place AS
SELECT
  "Post.id"::BIGINT  AS postId,
  "Place.id"::BIGINT AS placeId
FROM message_isLocatedIn_place_raw;

CREATE OR REPLACE VIEW forum_containerOf_post AS
SELECT
  "Forum.id"::BIGINT AS forumId,
  "Post.id"::BIGINT  AS postId
FROM forum_containerOf_post_raw;

CREATE OR REPLACE VIEW forum_hasMember_person AS
SELECT
  "Forum.id"::BIGINT  AS forumId,
  "Person.id"::BIGINT AS personId,
  joinDate::BIGINT     AS joinDate
FROM forum_hasMember_person_raw;

CREATE OR REPLACE VIEW person_hasInterest_tag AS
SELECT
  "Person.id"::BIGINT AS personId,
  "Tag.id"::BIGINT    AS tagId
FROM person_hasInterest_tag_raw;

CREATE OR REPLACE VIEW person_likes_message AS
SELECT
  "Person.id"::BIGINT AS personId,
  "Post.id"::BIGINT   AS postId,
  creationDate::BIGINT AS creationDate
FROM person_likes_message_raw;

CREATE OR REPLACE VIEW comment_replyOf_message AS
SELECT
  "Comment.id"::BIGINT     AS commentId,
  "Comment.id_1"::BIGINT   AS messageId
FROM comment_replyOf_message_raw;

CREATE OR REPLACE VIEW comment_replyOf_post AS
SELECT
  "Comment.id"::BIGINT AS commentId,
  "Post.id"::BIGINT    AS postId
FROM comment_replyOf_post_raw;

CREATE OR REPLACE VIEW tag_hasType_tagclass AS
SELECT
  "Tag.id"::BIGINT      AS tagId,
  "TagClass.id"::BIGINT AS tagClassId
FROM tag_hasType_tagclass_raw;

CREATE OR REPLACE VIEW tagclass_isSubclassOf_tagclass AS
SELECT
  "TagClass.id"::BIGINT     AS superclassId,
  "TagClass.id_1"::BIGINT   AS subclassId
FROM tagclass_isSubclassOf_tagclass_raw;

CREATE OR REPLACE VIEW place_isPartOf_place AS
SELECT
  "Place.id"::BIGINT     AS placeId,
  "Place.id_1"::BIGINT   AS parentPlaceId
FROM place_isPartOf_place_raw;

-- Multi-valued person.language / person.email are stored as ';' separated strings in sf1.
CREATE OR REPLACE VIEW person_speaks_language AS
SELECT
  p.id::BIGINT AS Person_id,
  lang AS language
FROM Person p,
LATERAL UNNEST(string_split(COALESCE(p.language, ''), ';')) AS t(lang)
WHERE lang IS NOT NULL AND lang <> '';

CREATE OR REPLACE VIEW person_email_emailaddress AS
SELECT
  p.id::BIGINT AS Person_id,
  em AS email
FROM Person p,
LATERAL UNNEST(string_split(COALESCE(p.email, ''), ';')) AS t(em)
WHERE em IS NOT NULL AND em <> '';

-- -----------------------------
-- Edge tables for PROPERTY GRAPH G (src_vid/dst_vid + properties)
-- -----------------------------
CREATE TABLE IF NOT EXISTS person_knows_person_e AS
SELECT
  "Person.id"::BIGINT    AS src_vid,
  "Person.id_1"::BIGINT  AS dst_vid,
  creationDate::BIGINT   AS creationDate
FROM person_knows_person_raw;

-- Derived KNOWS edges to support multi-hop queries without UNION (duckpgq can segfault on UNION of GRAPH_TABLE)
-- NOTE: duckpgq currently requires EDGE TABLES to be backed by physical tables (views are not supported).
-- - KNOWS_2: exactly 2 hops (excluding direct neighbors)
-- - KNOWS_1_2: 1 or 2 hops (keeps minimal hops per (src,dst))
-- - KNOWS_1_3: 1..3 hops (keeps minimal hops per (src,dst))
DROP TABLE IF EXISTS person_knows_person_2_e;
DROP TABLE IF EXISTS person_knows_person_1_2_e;
DROP TABLE IF EXISTS person_knows_person_1_3_e;
DROP VIEW IF EXISTS person_knows_person_2_e;
DROP VIEW IF EXISTS person_knows_person_1_2_e;
DROP VIEW IF EXISTS person_knows_person_1_3_e;

CREATE OR REPLACE TABLE person_knows_person_2_e AS
SELECT
  k1.src_vid AS src_vid,
  k2.dst_vid AS dst_vid,
  2 AS hops
FROM person_knows_person_e k1
JOIN person_knows_person_e k2
  ON k1.dst_vid = k2.src_vid
WHERE k1.src_vid <> k2.dst_vid
  AND NOT EXISTS (
    SELECT 1
    FROM person_knows_person_e k0
    WHERE k0.src_vid = k1.src_vid
      AND k0.dst_vid = k2.dst_vid
  );

CREATE OR REPLACE TABLE person_knows_person_1_2_e AS
SELECT
  src_vid,
  dst_vid,
  MIN(hops) AS hops
FROM (
  SELECT src_vid, dst_vid, 1 AS hops FROM person_knows_person_e
  UNION ALL
  SELECT src_vid, dst_vid, hops FROM person_knows_person_2_e
) t
GROUP BY src_vid, dst_vid;

CREATE OR REPLACE TABLE person_knows_person_1_3_e AS
SELECT
  src_vid,
  dst_vid,
  MIN(hops) AS hops
FROM (
  SELECT src_vid, dst_vid, 1 AS hops FROM person_knows_person_e
  UNION ALL
  SELECT k1.src_vid AS src_vid, k2.dst_vid AS dst_vid, 2 AS hops
  FROM person_knows_person_e k1
  JOIN person_knows_person_e k2 ON k1.dst_vid = k2.src_vid
  WHERE k1.src_vid <> k2.dst_vid
  UNION ALL
  SELECT k1.src_vid AS src_vid, k3.dst_vid AS dst_vid, 3 AS hops
  FROM person_knows_person_e k1
  JOIN person_knows_person_e k2 ON k1.dst_vid = k2.src_vid
  JOIN person_knows_person_e k3 ON k2.dst_vid = k3.src_vid
  WHERE k1.src_vid <> k3.dst_vid
) t
GROUP BY src_vid, dst_vid;

-- HAS_CREATED: swap HasCreator edges (Message/Post/Comment -> Person) into Person -> (Message/Post/Comment)
CREATE TABLE IF NOT EXISTS person_hasCreated_message_e AS
SELECT
  "Person.id"::BIGINT AS src_vid,
  "Post.id"::BIGINT   AS dst_vid
FROM message_hasCreator_person_raw;

CREATE TABLE IF NOT EXISTS person_hasCreated_post_e AS
SELECT
  "Person.id"::BIGINT AS src_vid,
  "Post.id"::BIGINT   AS dst_vid
FROM post_hasCreator_person_raw;

CREATE TABLE IF NOT EXISTS person_hasCreated_comment_e AS
SELECT
  "Person.id"::BIGINT  AS src_vid,
  "Comment.id"::BIGINT AS dst_vid
FROM comment_hasCreator_person_raw;

-- HAS_CREATOR: keep Comment -> Person direction for IC-8
CREATE TABLE IF NOT EXISTS comment_hasCreator_person_e AS
SELECT
  "Comment.id"::BIGINT AS src_vid,
  "Person.id"::BIGINT  AS dst_vid
FROM comment_hasCreator_person_raw;

-- WORKAT (Person -> Organisation)
CREATE TABLE IF NOT EXISTS person_workAt_organisation_e AS
SELECT
  "Person.id"::BIGINT        AS src_vid,
  "Organisation.id"::BIGINT  AS dst_vid,
  workFrom::INT              AS workFrom
FROM person_workAt_organisation_raw;

-- IS_LOCATED_IN (multiple edge tables share the same label)
CREATE TABLE IF NOT EXISTS person_isLocatedIn_place_e AS
SELECT
  "Person.id"::BIGINT AS src_vid,
  "Place.id"::BIGINT  AS dst_vid
FROM person_isLocatedIn_place_raw;

CREATE TABLE IF NOT EXISTS organisation_isLocatedIn_place_e AS
SELECT
  "Organisation.id"::BIGINT AS src_vid,
  "Place.id"::BIGINT        AS dst_vid
FROM organisation_isLocatedIn_place_raw;

CREATE TABLE IF NOT EXISTS message_isLocatedIn_place_e AS
SELECT
  "Post.id"::BIGINT  AS src_vid,
  "Place.id"::BIGINT AS dst_vid
FROM message_isLocatedIn_place_raw;

-- HAS_TAG (Post -> Tag)
CREATE TABLE IF NOT EXISTS post_hasTag_tag_e AS
SELECT
  "Post.id"::BIGINT AS src_vid,
  "Tag.id"::BIGINT  AS dst_vid
FROM post_hasTag_tag_raw;

-- likes (Person -> Message)
CREATE TABLE IF NOT EXISTS person_likes_message_e AS
SELECT
  "Person.id"::BIGINT AS src_vid,
  "Post.id"::BIGINT   AS dst_vid,
  creationDate::BIGINT AS creationDate
FROM person_likes_message_raw;

-- HAS_REPLY: swap ReplyOf (Comment -> Message) into Message -> Comment for IC-8
CREATE TABLE IF NOT EXISTS message_hasReply_comment_e AS
SELECT
  "Comment.id_1"::BIGINT  AS src_vid,
  "Comment.id"::BIGINT    AS dst_vid
FROM comment_replyOf_message_raw;

-- REPLY_OF: Comment -> Post
CREATE TABLE IF NOT EXISTS comment_replyOf_post_e AS
SELECT
  "Comment.id"::BIGINT AS src_vid,
  "Post.id"::BIGINT    AS dst_vid
FROM comment_replyOf_post_raw;

-- CONTAINER_OF: Forum -> Post
CREATE TABLE IF NOT EXISTS forum_containerOf_post_e AS
SELECT
  "Forum.id"::BIGINT AS src_vid,
  "Post.id"::BIGINT  AS dst_vid
FROM forum_containerOf_post_raw;

ANALYZE;

-- -----------------------------
-- Property graph definition
-- -----------------------------
CREATE OR REPLACE PROPERTY GRAPH G
VERTEX TABLES (
  Person,
  Message,
  Post,
  Comment,
  Forum,
  Organisation,
  Place,
  Tag,
  TagClass
)
EDGE TABLES (
  person_knows_person_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Person (vid)
    LABEL KNOWS,

  person_knows_person_1_2_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Person (vid)
    LABEL KNOWS_1_2,

  person_knows_person_1_3_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Person (vid)
    LABEL KNOWS_1_3,

  person_knows_person_2_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Person (vid)
    LABEL KNOWS_2,

  person_hasCreated_message_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Message (vid)
    LABEL HAS_CREATED_MESSAGE,

  person_hasCreated_post_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Post (vid)
    LABEL HAS_CREATED_POST,

  person_hasCreated_comment_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Comment (vid)
    LABEL HAS_CREATED_COMMENT,

  comment_hasCreator_person_e
    SOURCE KEY (src_vid) REFERENCES Comment (vid)
    DESTINATION KEY (dst_vid) REFERENCES Person (vid)
    LABEL HAS_CREATOR,

  person_workAt_organisation_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Organisation (vid)
    LABEL WORKAT,

  person_isLocatedIn_place_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Place (vid)
    LABEL PERSON_IS_LOCATED_IN,

  organisation_isLocatedIn_place_e
    SOURCE KEY (src_vid) REFERENCES Organisation (vid)
    DESTINATION KEY (dst_vid) REFERENCES Place (vid)
    LABEL ORG_IS_LOCATED_IN,

  message_isLocatedIn_place_e
    SOURCE KEY (src_vid) REFERENCES Message (vid)
    DESTINATION KEY (dst_vid) REFERENCES Place (vid)
    LABEL MESSAGE_IS_LOCATED_IN,

  post_hasTag_tag_e
    SOURCE KEY (src_vid) REFERENCES Post (vid)
    DESTINATION KEY (dst_vid) REFERENCES Tag (vid)
    LABEL POST_HAS_TAG,

  person_likes_message_e
    SOURCE KEY (src_vid) REFERENCES Person (vid)
    DESTINATION KEY (dst_vid) REFERENCES Message (vid)
    LABEL LIKES_MESSAGE,

  message_hasReply_comment_e
    SOURCE KEY (src_vid) REFERENCES Message (vid)
    DESTINATION KEY (dst_vid) REFERENCES Comment (vid)
    LABEL HAS_REPLY,

  comment_replyOf_post_e
    SOURCE KEY (src_vid) REFERENCES Comment (vid)
    DESTINATION KEY (dst_vid) REFERENCES Post (vid)
    LABEL REPLY_OF,

  forum_containerOf_post_e
    SOURCE KEY (src_vid) REFERENCES Forum (vid)
    DESTINATION KEY (dst_vid) REFERENCES Post (vid)
    LABEL CONTAINER_OF
);
