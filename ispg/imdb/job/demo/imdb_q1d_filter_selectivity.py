#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute predicate selectivities for IMDB JOB Q1d from the raw IMDB CSV data,
and write the results to q1_filter.json.

Usage (example):
    cd <repo-root>
    python ispg/imdb/job/demo/imdb_q1d_filter_selectivity.py

Assumes the raw data directory looks like:
    datasets/imdb/imdb_raw/
        schematext.sql
        title.csv
        company_type.csv
        movie_companies.csv
        info_type.csv

This script does not use DuckDB; it scans CSVs using Python's csv module.
"""

import csv
import json
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[4]


BASE_DIR = _repo_root() / "datasets/imdb/imdb_raw"

OUT_PATH = Path(__file__).resolve().parent / "q1_filter.json"


def safe_open_csv(path: Path):
    # errors='ignore' prevents rare bad characters from breaking the parse.
    return path.open("r", encoding="utf-8", errors="ignore", newline="")


def compute_title_selectivity() -> float:
    """
    t.production_year > 2000
    Table: title
    Column order (from schematext.sql):
        0 id
        1 title
        2 imdb_index
        3 kind_id
        4 production_year
        5 imdb_id
        6 phonetic_code
        7 episode_of_id
        8 season_nr
        9 episode_nr
        10 series_years
        11 md5sum
    """
    path = BASE_DIR / "title.csv"
    total = 0
    match = 0
    with safe_open_csv(path) as f:
        reader = csv.reader(f, delimiter=",", quotechar='"', escapechar="\\")
        for row in reader:
            if not row:
                continue
            total += 1
            if len(row) <= 4:
                # Corrupted row: keep total but skip counting.
                continue
            v = row[4].strip()
            if not v or v == "\\N":
                continue
            try:
                year = int(v)
            except ValueError:
                continue
            if year > 2000:
                match += 1
    return (match / total) if total else 1.0


def compute_info_type_selectivity() -> float:
    """
    it.info = 'bottom 10 rank'
    Table: info_type
    schema:
        0 id
        1 info
    """
    path = BASE_DIR / "info_type.csv"
    total = 0
    match = 0
    target = "bottom 10 rank"
    with safe_open_csv(path) as f:
        reader = csv.reader(f, delimiter=",", quotechar='"', escapechar="\\")
        for row in reader:
            if not row:
                continue
            total += 1
            if len(row) <= 1:
                continue
            info = row[1].strip()
            if info == target:
                match += 1
    return (match / total) if total else 1.0


def compute_company_type_selectivity() -> float:
    """
    ct.kind = 'production companies'
    Table: company_type
    schema:
        0 id
        1 kind
    """
    path = BASE_DIR / "company_type.csv"
    total = 0
    match = 0
    target = "production companies"
    with safe_open_csv(path) as f:
        reader = csv.reader(f, delimiter=",", quotechar='"', escapechar="\\")
        for row in reader:
            if not row:
                continue
            total += 1
            if len(row) <= 1:
                continue
            kind = row[1].strip()
            if kind == target:
                match += 1
    return (match / total) if total else 1.0


def compute_movie_companies_selectivity() -> float:
    """
    mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'
    Table: movie_companies
    schema:
        0 id
        1 movie_id
        2 company_id
        3 company_type_id
        4 note
    """
    path = BASE_DIR / "movie_companies.csv"
    total = 0
    match = 0
    bad_substr = "(as Metro-Goldwyn-Mayer Pictures)"
    with safe_open_csv(path) as f:
        reader = csv.reader(f, delimiter=",", quotechar='"', escapechar="\\")
        for row in reader:
            if not row:
                continue
            total += 1
            if len(row) <= 4:
                # Missing note column: treat as NULL -> satisfies NOT LIKE.
                match += 1
                continue
            note = row[4]
            note_stripped = note.strip()
            if note_stripped == "" or note_stripped == "\\N":
                # NULL also satisfies NOT LIKE.
                match += 1
            elif bad_substr not in note_stripped:
                match += 1
            # Otherwise: contains bad_substr -> not counted.
    return (match / total) if total else 1.0


def main() -> None:
    sels = {}
    sels["t.production_year > 2000"] = compute_title_selectivity()
    sels["it.info = 'bottom 10 rank'"] = compute_info_type_selectivity()
    sels["ct.kind = 'production companies'"] = compute_company_type_selectivity()
    sels["mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'"] = (
        compute_movie_companies_selectivity()
    )

    OUT_PATH.write_text(json.dumps(sels, indent=2), encoding="utf-8")

    print(f"Filter selectivities written to: {OUT_PATH}")
    for k, v in sels.items():
        print(f"  {k}: {v:.6f}")


if __name__ == "__main__":
    main()
