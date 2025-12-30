-- Idempotent setup for imdb_pgq.duckdb
-- Loads imdb_graph CSVs as tables (if missing) and defines PROPERTY GRAPH G.

LOAD duckpgq;
PRAGMA threads=1;

-- -----------------------------
-- Vertex tables
-- -----------------------------
CREATE TABLE IF NOT EXISTS akaName AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/akaName_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS akaTitle AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/akaTitle_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS castInfoVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/castInfoVertex_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS character AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/character_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS companyName AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/companyName_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS complCastInfoVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/complCastInfoVertex_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS infoVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/infoVertex_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS infoIdxVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/infoIdxVertex_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS keyword AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/keyword_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS person AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/person_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS personInfoVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/personInfoVertex_v.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_v.csv', ignore_errors=true);

-- -----------------------------
-- Edge tables
-- -----------------------------
CREATE TABLE IF NOT EXISTS person_akaNameEdge_akaName AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/person_akaNameEdge_akaName_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_akaTitleEdge_akaTitle AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_akaTitleEdge_akaTitle_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS castInfoVertex_castInfoEdge_person AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/castInfoVertex_castInfoEdge_person_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS castInfoVertex_castInfoEdge_title AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/castInfoVertex_castInfoEdge_title_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS castInfoVertex_castInfoEdge_character AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/castInfoVertex_castInfoEdge_character_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS complCastInfoVertex_complCastInfoEdge_title AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/complCastInfoVertex_complCastInfoEdge_title_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_episodeOfEdge_title AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_episodeOfEdge_title_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_infoEdge_infoVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_infoEdge_infoVertex_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_infoEdge_infoIdxVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_infoEdge_infoIdxVertex_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_keywordEdge_keyword AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_keywordEdge_keyword_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_linkTypeEdge_title AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_linkTypeEdge_title_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS title_movieCompanies_companyName AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/title_movieCompanies_companyName_e.csv', ignore_errors=true);

CREATE TABLE IF NOT EXISTS person_personInfoEdge_personInfoVertex AS
SELECT * FROM read_csv_auto('datasets/imdb/imdb_graph/person_personInfoEdge_personInfoVertex_e.csv', ignore_errors=true);

ANALYZE;

-- -----------------------------
-- Property graph definition
-- -----------------------------
CREATE OR REPLACE PROPERTY GRAPH G
VERTEX TABLES (
  title,
  companyName,
  keyword,
  infoVertex,
  infoIdxVertex,
  person,
  akaName,
  akaTitle,
  castInfoVertex,
  character,
  complCastInfoVertex,
  personInfoVertex
)
EDGE TABLES (
  title_movieCompanies_companyName
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES companyName (vid)
    LABEL movieCompanies,

  title_keywordEdge_keyword
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES keyword (vid)
    LABEL keywordEdge,

  title_infoEdge_infoVertex
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES infoVertex (vid)
    LABEL infoEdge,

  title_infoEdge_infoIdxVertex
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES infoIdxVertex (vid)
    LABEL infoIdxEdge,

  title_linkTypeEdge_title
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES title (vid)
    LABEL linkTypeEdge,

  title_episodeOfEdge_title
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES title (vid)
    LABEL episodeOfEdge,

  title_akaTitleEdge_akaTitle
    SOURCE KEY (src_vid) REFERENCES title (vid)
    DESTINATION KEY (dst_vid) REFERENCES akaTitle (vid)
    LABEL akaTitleEdge,

  person_akaNameEdge_akaName
    SOURCE KEY (src_vid) REFERENCES person (vid)
    DESTINATION KEY (dst_vid) REFERENCES akaName (vid)
    LABEL akaNameEdge,

  castInfoVertex_castInfoEdge_person
    SOURCE KEY (src_vid) REFERENCES castInfoVertex (vid)
    DESTINATION KEY (dst_vid) REFERENCES person (vid)
    LABEL castInfoPersonEdge,

  castInfoVertex_castInfoEdge_title
    SOURCE KEY (src_vid) REFERENCES castInfoVertex (vid)
    DESTINATION KEY (dst_vid) REFERENCES title (vid)
    LABEL castInfoTitleEdge,

  castInfoVertex_castInfoEdge_character
    SOURCE KEY (src_vid) REFERENCES castInfoVertex (vid)
    DESTINATION KEY (dst_vid) REFERENCES character (vid)
    LABEL castInfoCharacterEdge,

  complCastInfoVertex_complCastInfoEdge_title
    SOURCE KEY (src_vid) REFERENCES complCastInfoVertex (vid)
    DESTINATION KEY (dst_vid) REFERENCES title (vid)
    LABEL complCastTitleEdge,

  person_personInfoEdge_personInfoVertex
    SOURCE KEY (src_vid) REFERENCES person (vid)
    DESTINATION KEY (dst_vid) REFERENCES personInfoVertex (vid)
    LABEL personInfoEdge
);
