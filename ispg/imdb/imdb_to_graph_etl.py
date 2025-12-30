#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMDB -> GLogS-style graph ETL

- Read raw IMDB CSV files (datasets/imdb/imdb_raw)
- Parse table/column names from schematext.sql (ignore types)
- Use DuckDB to load each table as an all-VARCHAR staging table, then rename columns
- Build vertex/edge tables that match imdb_glogs_schema.json
- Export results to datasets/imdb/imdb_graph
"""

import argparse
import os
import re
from pathlib import Path

import duckdb  # pip install duckdb


# ------------------------------
# 1. Parse schematext.sql
# ------------------------------

def parse_schema(schema_path: Path):
    """
    Parse {table_name: [col1, col2, ...]} from schematext.sql.
    Only consider column definitions inside CREATE TABLE xxx (...), and ignore constraints/indexes.
    """
    text = schema_path.read_text(encoding="utf-8", errors="ignore")

    table_pattern = re.compile(
        r"CREATE TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*?)\);",
        re.S | re.I,
    )
    tables = {}

    for m in table_pattern.finditer(text):
        tname = m.group(1)
        body = m.group(2)

        cols = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip trailing comma
            if line.endswith(","):
                line = line[:-1].strip()

            # Skip constraints
            upper = line.upper()
            if upper.startswith("PRIMARY KEY") or \
               upper.startswith("UNIQUE") or \
               upper.startswith("FOREIGN KEY") or \
               upper.startswith("CHECK") or \
               upper.startswith("CONSTRAINT"):
                continue

            # Column definition: name type ...
            m_col = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)\s+.+", line)
            if not m_col:
                continue
            col_name = m_col.group(1)
            cols.append(col_name)

        if cols:
            tables[tname] = cols

    return tables


# ------------------------------
# 2. Load raw CSVs -> staging tables
# ------------------------------

def load_raw_tables(con: duckdb.DuckDBPyConnection,
                    schema_spec: dict,
                    raw_dir: Path):
    """
    For each table in schematext, look for the same-named CSV under raw_dir.
    Load it into DuckDB as {table}_raw (auto column names column0..), then rename
    columns to the formal table {table} using the schematext column order.
    All columns are cast to VARCHAR.
    """
    raw_dir = raw_dir.resolve()
    existing_csvs = {p.name for p in raw_dir.glob("*.csv")}

    for table, cols in schema_spec.items():
        csv_name = f"{table}.csv"
        csv_path = raw_dir / csv_name
        if csv_name not in existing_csvs:
            # Some small tables may have no corresponding CSV; skip.
            print(f"[WARN] CSV for table '{table}' not found, skip.")
            continue

        print(f"[INFO] Loading table '{table}' from {csv_path} ...")

        # Load as a staging table; DuckDB auto-generates column names (column0, column1, ...)
        con.execute(f"""
            CREATE OR REPLACE TABLE {table}_raw AS
            SELECT *
            FROM read_csv(
                '{csv_path.as_posix()}',
                delim=',',
                quote='"',
                escape='\\',
                header=false,
                null_padding=true,
                ignore_errors=true,
                auto_detect=true
            );
        """)

        # Fetch staging table column names
        raw_cols = [
            row[1]
            for row in con.execute(
                f"PRAGMA table_info('{table}_raw');"
            ).fetchall()
        ]
        n_raw = len(raw_cols)
        n_schema = len(cols)

        if n_raw != n_schema:
            print(
                f"[WARN] Column count mismatch for '{table}': "
                f"schema={n_schema}, csv={n_raw}. "
                f"Will map by min(n_schema, n_raw), extra columns padded/ignored."
            )

        # Build SELECT projection with renamed columns
        select_exprs = []
        for i, colname in enumerate(cols):
            if i < n_raw:
                select_exprs.append(f"{raw_cols[i]}::VARCHAR AS {colname}")
            else:
                # CSV has fewer columns; pad with NULL
                select_exprs.append(f"NULL::VARCHAR AS {colname}")

        select_list = ",\n       ".join(select_exprs)

        con.execute(f"""
            CREATE OR REPLACE TABLE {table} AS
            SELECT {select_list}
            FROM {table}_raw;
        """)

        # Raw table no longer needed
        con.execute(f"DROP TABLE {table}_raw;")

    print("[INFO] All raw tables loaded.")


# ------------------------------
# 3. Build vertex tables
# ------------------------------

def create_vertex_tables(con: duckdb.DuckDBPyConnection):
    print("[INFO] Creating vertex tables ...")

    # akaName
    con.execute("""
        CREATE OR REPLACE TABLE akaName_v AS
        SELECT
            id            AS vid,
            person_id,
            name,
            imdb_index,
            name_pcode_cf,
            name_pcode_nf,
            surname_pcode,
            md5sum
        FROM aka_name;
    """)

    # akaTitle
    con.execute("""
        CREATE OR REPLACE TABLE akaTitle_v AS
        SELECT
            id            AS vid,
            movie_id,
            title,
            imdb_index,
            kind_id,
            production_year,
            phonetic_code,
            episode_of_id,
            season_nr,
            episode_nr,
            note,
            md5sum
        FROM aka_title;
    """)

    # castInfoVertex (cast_info)
    con.execute("""
        CREATE OR REPLACE TABLE castInfoVertex_v AS
        SELECT
            id            AS vid,
            person_id,
            movie_id,
            person_role_id,
            role_id,
            note,
            nr_order
        FROM cast_info;
    """)

    # character (char_name)
    con.execute("""
        CREATE OR REPLACE TABLE character_v AS
        SELECT
            id            AS vid,
            name,
            imdb_index,
            imdb_id,
            name_pcode_nf,
            surname_pcode,
            md5sum
        FROM char_name;
    """)

    # companyName (company_name)
    con.execute("""
        CREATE OR REPLACE TABLE companyName_v AS
        SELECT
            id            AS vid,
            name,
            country_code,
            imdb_id,
            name_pcode_nf,
            name_pcode_sf,
            md5sum
        FROM company_name;
    """)

    # complCastInfoVertex (complete_cast + comp_cast_type, twice)
    con.execute("""
        CREATE OR REPLACE TABLE complCastInfoVertex_v AS
        SELECT
            cc.id         AS vid,
            cc.movie_id,
            cc.subject_id,
            cc.status_id,
            cct1.kind     AS subject_kind,
            cct2.kind     AS status_kind
        FROM complete_cast cc
        JOIN comp_cast_type cct1 ON cc.subject_id = cct1.id
        JOIN comp_cast_type cct2 ON cc.status_id = cct2.id;
    """)

    # infoVertex (movie_info + info_type)
    con.execute("""
        CREATE OR REPLACE TABLE infoVertex_v AS
        SELECT
            mi.id         AS vid,
            mi.movie_id,
            mi.info_type_id,
            it.info       AS info_type_info,
            mi.info       AS info_value,
            mi.note       AS note
        FROM movie_info mi
        JOIN info_type it ON mi.info_type_id = it.id;
    """)

    # infoIdxVertex (movie_info_idx + info_type)
    con.execute("""
        CREATE OR REPLACE TABLE infoIdxVertex_v AS
        SELECT
            mi.id         AS vid,
            mi.movie_id,
            mi.info_type_id,
            it.info       AS info_type_info,
            mi.info       AS info_value,
            mi.note       AS note
        FROM movie_info_idx mi
        JOIN info_type it ON mi.info_type_id = it.id;
    """)

    # keyword
    con.execute("""
        CREATE OR REPLACE TABLE keyword_v AS
        SELECT
            id            AS vid,
            keyword,
            phonetic_code
        FROM keyword;
    """)

    # person (name)
    con.execute("""
        CREATE OR REPLACE TABLE person_v AS
        SELECT
            id            AS vid,
            name,
            imdb_index,
            imdb_id,
            gender,
            name_pcode_cf,
            name_pcode_nf,
            surname_pcode,
            md5sum
        FROM name;
    """)

    # personInfoVertex (person_info + info_type)
    con.execute("""
        CREATE OR REPLACE TABLE personInfoVertex_v AS
        SELECT
            pi.id         AS vid,
            pi.person_id,
            pi.info_type_id,
            it.info       AS info_type_info,
            pi.info       AS info_value,
            pi.note       AS note
        FROM person_info pi
        JOIN info_type it ON pi.info_type_id = it.id;
    """)

    # title
    con.execute("""
        CREATE OR REPLACE TABLE title_v AS
        SELECT
            id            AS vid,
            title,
            imdb_index,
            kind_id,
            production_year,
            imdb_id,
            phonetic_code,
            episode_of_id,
            season_nr,
            episode_nr,
            series_years,
            md5sum
        FROM title;
    """)

    print("[INFO] Vertex tables created.")


# ------------------------------
# 4. Build edge tables
# ------------------------------

def create_edge_tables(con: duckdb.DuckDBPyConnection):
    print("[INFO] Creating edge tables ...")

    # person_akaNameEdge_akaName
    con.execute("""
        CREATE OR REPLACE TABLE person_akaNameEdge_akaName_e AS
        SELECT
            person_id  AS src_vid,
            id         AS dst_vid
        FROM aka_name;
    """)

    # title_akaTitleEdge_akaTitle
    con.execute("""
        CREATE OR REPLACE TABLE title_akaTitleEdge_akaTitle_e AS
        SELECT
            movie_id   AS src_vid,
            id         AS dst_vid
        FROM aka_title;
    """)

    # castInfoVertex_castInfoEdge_person
    con.execute("""
        CREATE OR REPLACE TABLE castInfoVertex_castInfoEdge_person_e AS
        SELECT
            id         AS src_vid,
            person_id  AS dst_vid
        FROM cast_info;
    """)

    # castInfoVertex_castInfoEdge_title
    con.execute("""
        CREATE OR REPLACE TABLE castInfoVertex_castInfoEdge_title_e AS
        SELECT
            id         AS src_vid,
            movie_id   AS dst_vid
        FROM cast_info;
    """)

    # castInfoVertex_castInfoEdge_character
    con.execute("""
        CREATE OR REPLACE TABLE castInfoVertex_castInfoEdge_character_e AS
        SELECT
            id             AS src_vid,
            person_role_id AS dst_vid
        FROM cast_info
        WHERE person_role_id IS NOT NULL;
    """)

    # complCastInfoVertex_complCastInfoEdge_title
    con.execute("""
        CREATE OR REPLACE TABLE complCastInfoVertex_complCastInfoEdge_title_e AS
        SELECT
            id         AS src_vid,
            movie_id   AS dst_vid
        FROM complete_cast
        WHERE movie_id IS NOT NULL;
    """)

    # title_episodeOfEdge_title
    con.execute("""
        CREATE OR REPLACE TABLE title_episodeOfEdge_title_e AS
        SELECT
            id             AS src_vid,
            episode_of_id  AS dst_vid
        FROM title
        WHERE episode_of_id IS NOT NULL;
    """)

    # title_infoEdge_infoVertex (movie_info)
    con.execute("""
        CREATE OR REPLACE TABLE title_infoEdge_infoVertex_e AS
        SELECT
            movie_id   AS src_vid,
            id         AS dst_vid
        FROM movie_info;
    """)

    # title_infoEdge_infoIdxVertex (movie_info_idx)
    con.execute("""
        CREATE OR REPLACE TABLE title_infoEdge_infoIdxVertex_e AS
        SELECT
            movie_id   AS src_vid,
            id         AS dst_vid
        FROM movie_info_idx;
    """)

    # title_keywordEdge_keyword
    con.execute("""
        CREATE OR REPLACE TABLE title_keywordEdge_keyword_e AS
        SELECT
            movie_id     AS src_vid,
            keyword_id   AS dst_vid
        FROM movie_keyword;
    """)

    # title_linkTypeEdge_title (movie_link + link_type)
    con.execute("""
        CREATE OR REPLACE TABLE title_linkTypeEdge_title_e AS
        SELECT
            ml.movie_id        AS src_vid,
            ml.linked_movie_id AS dst_vid,
            lt.link            AS link
        FROM movie_link ml
        JOIN link_type lt ON ml.link_type_id = lt.id;
    """)

    # title_movieCompanies_companyName (movie_companies + company_type)
    con.execute("""
        CREATE OR REPLACE TABLE title_movieCompanies_companyName_e AS
        SELECT
            mc.movie_id        AS src_vid,
            mc.company_id      AS dst_vid,
            ct.kind            AS company_type_kind,
            mc.note            AS note
        FROM movie_companies mc
        JOIN company_type ct ON mc.company_type_id = ct.id;
    """)

    # person_personInfoEdge_personInfoVertex
    con.execute("""
        CREATE OR REPLACE TABLE person_personInfoEdge_personInfoVertex_e AS
        SELECT
            person_id   AS src_vid,
            id          AS dst_vid
        FROM person_info;
    """)

    print("[INFO] Edge tables created.")


# ------------------------------
# 5. Export to CSV
# ------------------------------

def export_tables(con: duckdb.DuckDBPyConnection,
                  out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Vertex tables & edge tables to export
    vertex_tables = [
        "akaName_v",
        "akaTitle_v",
        "castInfoVertex_v",
        "character_v",
        "companyName_v",
        "complCastInfoVertex_v",
        "infoVertex_v",
        "infoIdxVertex_v",
        "keyword_v",
        "person_v",
        "personInfoVertex_v",
        "title_v",
    ]

    edge_tables = [
        "person_akaNameEdge_akaName_e",
        "title_akaTitleEdge_akaTitle_e",
        "castInfoVertex_castInfoEdge_person_e",
        "castInfoVertex_castInfoEdge_title_e",
        "castInfoVertex_castInfoEdge_character_e",
        "complCastInfoVertex_complCastInfoEdge_title_e",
        "title_episodeOfEdge_title_e",
        "title_infoEdge_infoVertex_e",
        "title_infoEdge_infoIdxVertex_e",
        "title_keywordEdge_keyword_e",
        "title_linkTypeEdge_title_e",
        "title_movieCompanies_companyName_e",
        "person_personInfoEdge_personInfoVertex_e",
    ]

    for t in vertex_tables + edge_tables:
        out_path = out_dir / f"{t}.csv"
        print(f"[INFO] Exporting {t} -> {out_path}")
        con.execute(f"""
            COPY {t}
            TO '{out_path.as_posix()}'
            WITH (FORMAT CSV, HEADER TRUE);
        """)

    print(f"[INFO] All graph tables exported to: {out_dir}")


# ------------------------------
# 6. main
# ------------------------------

def main():
    repo_root = Path(__file__).resolve()
    while repo_root.name != "ispg" and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    repo_root = repo_root.parent if repo_root.name == "ispg" else Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(description="IMDB -> GLogS-style graph ETL")
    parser.add_argument(
        "--raw-dir",
        type=str,
        default=str(repo_root / "datasets/imdb/imdb_raw"),
        help="Directory containing original IMDB CSV files",
    )
    parser.add_argument(
        "--schema-file",
        type=str,
        default=str(repo_root / "datasets/imdb/imdb_raw/schematext.sql"),
        help="Path to schematext.sql",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(repo_root / "datasets/imdb/imdb_graph"),
        help="Directory to write graph CSVs",
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    schema_file = Path(args.schema_file)
    out_dir = Path(args.out_dir)

    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw dir not found: {raw_dir}")

    print(f"[INFO] Parsing schema from {schema_file}")
    schema_spec = parse_schema(schema_file)

    print("[INFO] Connecting to DuckDB (in-memory)")
    con = duckdb.connect(database=":memory:")

    # 1) Load all raw CSVs -> relational tables
    load_raw_tables(con, schema_spec, raw_dir)

    # 2) Build graph vertex/edge tables
    create_vertex_tables(con)
    create_edge_tables(con)

    # 3) Export as CSV
    export_tables(con, out_dir)

    print("[INFO] ETL finished.")


if __name__ == "__main__":
    main()
