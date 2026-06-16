# ISPG: Cost-Based Interleaved Plan Generation for SQL/PGQ Queries

Reference implementation of **ISPG** (Interleaved SPJM Plan Generation). Given an SPJM
query (Select-Project-Join-Match), ISPG searches a *unified operator space* in which graph
operators (Scan / Expand / EdgeCheck) and relational operators (Get / Join / Resolve /
Merge) are interleaved, and produces a low-cost plan that may begin on either the graph
side or the relational side. It offers both the exhaustive cost-based optimizer (Alg. 1)
and a polynomial-time greedy variant (Alg. 2). For comparison it also produces the
**RelGo** baseline plan (MATCH-first: the graph match is optimized and materialized in full
before any SPJ operator runs).

The same optimizer plans both the LDBC SNB and the JOB (over IMDB) workloads.

## Layout

```
ispg/                 the implementation (pure Python)
  ir.py               SPJM data model (Vertex / Edge / Relation / SPJMQuery)
  optimizer.py        interleaved DP optimizer (Alg. 1) + greedy variant (Alg. 2) + RelGo baseline
  stats.py            fused statistics catalog (Def. 3): structural F(P') from GLogS,
                      relational sel/fanout from the relational catalog
  statscatalog.py     O(1) relational selectivity/fanout over a compact JSON
  relstats.py         offline relational statistics (DuckDB over raw CSV)
  build_catalog.py    offline build of the relational statistics catalog (JSON)
  queries.py          LDBC SNB Interactive Complex queries (IC1-12) as SPJM IR
  queries_demo.py     demo variants (SPJ-side / relation-rooted entry; Fig. 4)
  stats_imdb.py       IMDB/JOB statistics provider
  queries_job.py      JOB queries as SPJM IR
  main.py             generate ISPG / greedy / RelGo plans into plans/<bench>/{ispg,greedy,relgo}/
ldbc query/           the original LDBC SQL/PGQ queries (reference for the IR encoding)
job query/            the original JOB SQL/PGQ queries (reference for the IR encoding)
ref/                  PathCE (git submodule) -- the GLogS structural-statistics backend
```

## Generating plans

```bash
python ispg/main.py                 # all LDBC and JOB
python ispg/main.py ic7-1 ic3-1     # selected LDBC queries
python ispg/main.py --bench job     # JOB only
```

Each query yields three text plans, e.g. `plans/ldbc/ispg/ic7-1.txt`,
`plans/ldbc/greedy/ic7-1.txt` and `plans/ldbc/relgo/ic7-1.txt`. A plan lists its operators
with per-step and cumulative cost; SPJ-side operators are marked `(SPJ, dashed)`.

## Statistics

ISPG's frequency `F(U) = F(P') * prod(sel) * prod(fo)` combines two halves:

- **Structural** `F(P')` -- from **GLogS**, via the PathCE submodule `ref/`. Build GLogS and
  the graph catalog through PathCE's scripts, e.g. for LDBC
  `ref/scripts/glogs/build_ldbc_graph.sh` then `build_ldbc_catalog.sh`, producing
  `ref/catalogs/ldbc/glogs/ldbc_sf0.003.bincode`. Paths can be overridden with `ISPG_GLOGS_*`.
- **Relational** `sel`, `fo` -- a compact JSON produced by `build_catalog.py` over the raw
  dataset. Place the raw LDBC dataset under `data/ldbc/sf1` (or set `ISPG_DATA_DIR`) and run
  `python ispg/build_catalog.py`.

The statistics catalogs and raw datasets are large and are produced by the steps above;
they live under `ref/` and `data/` and are not part of this repository's source tree.

### IMDB / JOB

`stats_imdb.py` and `queries_job.py` plan the JOB queries through the same optimizer, using
the JOB-table-to-graph mapping in `stats_imdb.TABLE_TO_LABEL` / `NONVERTEX_TO_EDGE`. The
GLogS IMDB catalog is built from the IMDB dataset through PathCE; IMDB paths are configured
via `ISPG_IMDB_*`.

## Relationship to PathCE

`ref/` is the PathCE artifact repository
([wzzzzd/pathce](https://github.com/wzzzzd/pathce)), included as a git submodule. ISPG uses
PathCE as the GLogS structural-statistics backend; the interleaved optimizer, cost model,
and SPJM modelling in `ispg/` are this project's contribution.
