# ISPG

ISPG is a cost-driven query plan generator for SQL/PGQ (SPJM) queries, built on top of [GLogS](https://github.com/TatianaJin/glogs) structural cardinality estimates. It supports the LDBC SNB interactive-complex (IC) benchmark and the IMDB JOB benchmark.

## Repository layout

```
.
├── setup.sh                  # One-shot deployment script
├── requirements.txt          # Python dependencies (duckdb, sqlglot)
├── glogs/                    # GLogS source (Rust) — do not modify
├── scripts/glogs/
│   └── estimate.sh           # Thin shell wrapper around pattern_count
├── schemas/
│   └── dummy_schema.json     # Minimal GLogS storage schema
├── catalogs/
│   └── ldbc_small/glogs/
│       └── ldbc_sf0.003.bincode   # Pre-built LDBC catalog (committed)
├── patterns/job/             # JOB GLogS pattern definitions
└── ispg/
    ├── core/
    │   └── estimator.py      # Shared GLogsEstimator + SchemaInfo
    ├── ldbc/
    │   ├── ic/
    │   │   └── ldbc_query_optimizer.py   # LDBC IC plan generator (main entry)
    │   ├── ldbc_ic_compiler.py           # Compiles SQL/PGQ → filter JSON
    │   ├── query_filters/                # Pre-computed per-query selectivities
    │   ├── query_pattern/                # Per-query MATCH/SQL pattern definitions
    │   └── query_plan/                   # Generated plan output
    └── imdb/
        └── job/
            ├── job_query_optimizer.py    # JOB plan generator
            ├── imdb_job_query_compiler.py
            ├── query_filters/
            └── query_plan/
```

## Quick start (fresh environment)

### 1  Prerequisites

| Tool | Minimum version | Notes |
|------|-----------------|-------|
| Python | 3.10 | `python3 --version` |
| Rust / Cargo | stable | `curl https://sh.rustup.rs -sSf \| sh` |

Ubuntu packages needed to build GLogS:
```bash
sudo apt-get install -y build-essential clang cmake protobuf-compiler uuid-dev openjdk-8-jdk
```

### 2  Run the deployment script

```bash
cd <repo-root>
bash setup.sh
```

This will:
1. Build the GLogS Rust binaries (`glogs/ir/cargo build --release`)
2. Create a Python virtual environment (`.venv/`)
3. Install Python dependencies (`duckdb`, `sqlglot`)
4. Verify the pre-built LDBC catalog

### 3  Run the LDBC IC optimizer

```bash
source .venv/bin/activate

# Generate plans for all 12 IC queries:
python ispg/ldbc/ic/ldbc_query_optimizer.py --all

# Generate a plan for a single query:
python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-1
```

Plans are written to `ispg/ldbc/query_plan/ic-*_ispg.plan`.

### 4  Run the IMDB JOB optimizer

```bash
python ispg/imdb/job/job_query_optimizer.py --all
```

Plans are written to `ispg/imdb/job/query_plan/`.

## Building the LDBC catalog from scratch

> **Skip this step** if you are using the pre-committed catalog at  
> `catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode`.

Prepare the input data:
```
datasets/ldbc/sf0.003_vid/   ← flattened LDBC SF0.003 with re-assigned vertex IDs
```

Then run:
```bash
bash ispg/ldbc/build_ldbc_small_graph.sh 0.003
bash ispg/ldbc/build_ldbc_small_catalog.sh 0.003 32
```

Output:
- `graphs/ldbc_small/glogs/ldbc_sf0.003` — compiled graph
- `catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode` — GLogS catalog

## Regenerating query filter / pattern JSON

The `query_filters/` and `query_pattern/` directories are pre-computed and
committed. To regenerate them from raw SQL/PGQ source (requires the LDBC SF1
dataset at `datasets/ldbc/sf1/`):

```bash
python ispg/ldbc/ldbc_ic_compiler.py --all
```

## Key optimizer flags

| Flag | Default | Description |
|------|---------|-------------|
| `--query` | — | Query name(s) to optimize, e.g. `ic-1` |
| `--all` | off | Optimize all queries found in the filter directory |
| `--glogs` | `catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode` | GLogS catalog path (relative to repo root) |
| `--script` | `scripts/glogs/estimate.sh` | GLogS estimate wrapper script |
| `--cost-scale` | `0.1` | Multiplicative cost scaling factor |
| `--knows-alpha` | `-0.5` | Power-law correction for `Person_knows_Person` edges |
