# ISPG
This repository contains the ISPG query plan generator (built on top of GLogS estimates).

## Project Structure
```
.
├── README.md
├── requirements.txt
├── ispg/                   # ISPG code (IMDB + LDBC)
├── glogs/                  # GLogS source code (build required binaries)
├── scripts/glogs/          # wrapper scripts (estimate.sh)
├── patterns/job/           # JOB patterns (used by IMDB optimizer)
└── schemas/                # schemas used by graph serialization
```

## Environment
1. Ubuntu 22.04 or newer.
2. Make sure you have the following packages installed:
- openjdk-8-jdk
- protobuf-compiler
- build-essential
- clang
- cmake
- python3-pip
- uuid
3. Make sure you have Rust installed (see https://www.rust-lang.org/tools/install for more details)
4. Make sure you have set up and activate a python virtual environment:
```bash
$ python3 -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt

# (Optional) open a DuckDB file if you need it
$ ~/.duckdb/cli/latest/duckdb imdb_pgq.duckdb
```
5. Make sure you have Julia installed (see https://julialang.org/downloads/ for more details)

## Get Started
This section explains how to build GLogS binaries and generate the catalogs required by ISPG.

### 1) Build GLogS (required)
```bash
$ cd glogs/ir
$ cargo build -r
$ cd ../..
```

After this step, you should have these binaries:
- glogs/ir/target/release/pattern_count
- glogs/ir/target/release/build_graph
- glogs/ir/target/release/build_catalog

### 2) Generate LDBC GLogS graph + catalog
Prepare the input dataset directory:
- datasets/ldbc/sf0.003_vid

Then run:
```bash
$ bash ispg/ldbc/build_ldbc_small_graph.sh 0.003
$ bash ispg/ldbc/build_ldbc_small_catalog.sh 0.003 32
```

This should produce:
- graphs/ldbc_small/glogs/ldbc_sf0.003
- catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode

### 3) Run LDBC ISPG optimizer
```bash
$ python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-1
# or generate all IC plans:
$ python ispg/ldbc/ic/ldbc_query_optimizer.py --all
```

Plans are written to:
- ispg/ldbc/query_plan/

### 4) (Optional) IMDB pipeline (graph + catalog)
If you want to run the IMDB components, prepare:
- datasets/imdb/imdb (processed IMDB graph-style CSVs)

Then you can run:
```bash
$ bash ispg/imdb/build_imdb_small_graph.sh
$ bash ispg/imdb/build_imdb_small_catalog.sh 32
```

