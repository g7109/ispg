# ISPG

ISPG (Interleaved SPJM Plan Generation) is a cost-driven query-plan generator
for SQL/PGQ (SPJM) queries, built on top of
[GLogS](https://github.com/TatianaJin/glogs) structural cardinality estimates.

Unlike a MATCH-first optimizer, ISPG decomposes both the MATCH and the SPJ side
of a query into fine-grained operators in a single space, so a plan may start on
either side and interleave the two. Cyclic sub-patterns whose closing edge is
written on the SPJ side are matched *inside* the matching via an EdgeCheck, so a
triangle is enumerated within its AGM bound rather than as a binary join.

It supports the LDBC SNB interactive-complex (IC) benchmark and the IMDB JOB
benchmark.

## Repository layout

```
.
├── setup.sh                  # One-shot deployment script (build GLogS + venv)
├── requirements.txt          # Python deps (duckdb, sqlglot — only the compiler needs them)
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
    │   │   ├── ldbc_query_optimizer.py  # CLI entry point
    │   │   ├── optimizer.py             # ISPGOptimizer — Algorithm 1 (§5.5)
    │   │   └── plan.py                   # Plan data structures + rendering
    │   ├── gen_fixed_hop_subqueries.py  # Expand VarExpand queries into fixed-hop sub-queries
    │   ├── ldbc_ic_compiler.py          # SQL/PGQ → filter JSON (local-only, not shipped)
    │   ├── ldbc_glogs_schema.json       # LDBC GLogS schema
    │   ├── query_filters/               # Per-query selectivities + structure (committed)
    │   ├── query_pattern/               # Per-query MATCH/SQL pattern definitions (committed)
    │   └── query_plan/                  # Generated plan output (git-ignored)
    └── imdb/job/                        # IMDB JOB optimizer + compiler
```

The optimizer's three core modules:

| Module | Role |
|--------|------|
| `ispg/core/estimator.py` | Wraps the GLogS `pattern_count` binary to return `F(p')` |
| `ispg/ldbc/ic/optimizer.py` | Bottom-up DP over covered variable sets (Algorithm 1) |
| `ispg/ldbc/ic/plan.py` | `PlanNode` tree + execution-step / tree rendering |

## Quick start (fresh environment)

### 1  Prerequisites

| Tool | Minimum version | Notes |
|------|-----------------|-------|
| Python | 3.10 | `python3 --version` (the LDBC optimizer uses only the standard library) |
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

This builds the GLogS Rust binaries (`glogs/ir/cargo build --release`), creates
a Python venv, installs the Python deps, and verifies the committed LDBC catalog.

> The committed catalog and per-query `query_filters/` / `query_pattern/` JSON
> are all that the LDBC optimizer needs at run time — no dataset download
> required.

### 3  Run the LDBC IC optimizer

Most IC queries are fixed-hop and run directly:

```bash
# A single query:
python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-2

# All runnable queries:
python ispg/ldbc/ic/ldbc_query_optimizer.py --all
```

Queries with a variable-length path (VarExpand, e.g. `knows*1..3`) are first
expanded into one fixed-hop sub-query per hop count (`ic-1-1`, `ic-1-2`, …).
These sub-queries are committed, so normally you can run them straight away:

```bash
python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-1-1 --query ic-1-2 --query ic-1-3
```

To regenerate the fixed-hop sub-queries from their parent MATCH/SQL patterns
(no dataset needed — it only rewrites the committed JSON):

```bash
python ispg/ldbc/gen_fixed_hop_subqueries.py
```

Plans are written to `ispg/ldbc/query_plan/ic-*_ispg.plan`.

### Reading a plan

Each plan is a linearised execution order plus an ASCII tree. Operators are
named after the paper's algebra (Table 2.1 / §5.4):

| Operator | Meaning |
|----------|---------|
| `Scan` / `Get` | Introduce a vertex / a relation (the two entry points) |
| `Expand` | Traverse one declared edge to a new vertex |
| `ExpandInt` | Expand fused with the `EdgeCheck`s that close the remaining edges onto the new vertex (§5.4) |
| `EdgeCheck` | Test a declared edge whose endpoints are already bound |
| `Select` | Apply a predicate (a vertex/edge filter, or an `x.id = y.id` key equality) |
| `Join` | Join a relation that has no key-mapping (declared edges stay `Expand`) |
| `Merge` | Combine two independently built states (bushy plan) |
| `π_A` | Final projection |

`ExpandInt` appears whenever a query closes a cycle (e.g. `ic-7`, `ic-4`,
`ic-9-2`). `Merge` builds a bushy plan by combining two independently grown
states on the variables they share. The fanout factor `fo(R')` (APU Frequency,
Def. 3; the `Orders` table of the paper's Fig. 1) estimates a non-graph relation
on the same footing as a vertex-expansion factor.

## Building the LDBC catalog from scratch

> **Skip this step** if you are using the committed catalog at
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

The `query_filters/` and `query_pattern/` directories are committed. To
regenerate them from raw SQL/PGQ source you need the local-only compiler
(`ispg/ldbc/ldbc_ic_compiler.py`, not shipped) and the LDBC SF1 dataset at
`datasets/ldbc/sf1/`:

```bash
python ispg/ldbc/ldbc_ic_compiler.py --all
```

## Key optimizer flags

| Flag | Default | Description |
|------|---------|-------------|
| `--query` | — | Query name(s) to optimize, e.g. `ic-1-2` (repeatable) |
| `--all` | off | Optimize all queries found in the filter directory |
| `--glogs` | `catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode` | GLogS catalog path (relative to repo root) |
| `--script` | `scripts/glogs/estimate.sh` | GLogS estimate wrapper script |
| `--json-dir` | `ispg/ldbc/query_filters` | Directory of per-query filter JSON |
| `--cost-scale` | `0.1` | Multiplicative cost scaling factor |
