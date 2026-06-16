"""Offline build of the relational statistics catalog (one-off).

Scans the raw dataset once and precomputes, per column, compact statistics sufficient
for O(1) selectivity estimation:
  - numeric columns: min/max/ndv/null_frac + an equi-depth histogram (approx_quantile bounds)
  - string columns: ndv/null_frac + (when low-cardinality) an MCV most-common-values table
  - edge tables: cardinality + fanout_src/fanout_dst
The product is a small JSON loaded at query time by statscatalog.py, which never touches
the raw data again.

Run this once after placing the raw dataset (see relstats.py for the expected data path)
to produce the relational statistics catalog read at query time by statscatalog.py.
Output path can be overridden with ISPG_RELSTATS.
"""
from __future__ import annotations

import json
import os
import time

from relstats import RelStats

HIST_BUCKETS = 32      # equi-depth histogram buckets
MCV_MAX_NDV = 1024     # build an MCV only when a column's distinct count <= this
MCV_TOPK = 32          # keep at most this many most-common values per column

NUMERIC_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
    "FLOAT", "DOUBLE", "DECIMAL", "REAL",
}

DEFAULT_OUT = os.environ.get(
    "ISPG_RELSTATS",
    os.path.join(os.path.dirname(__file__), "catalogs", "ldbc_sf1_relstats.json"),
)


def _col_types(con, view: str) -> dict[str, str]:
    rows = con.execute(f'DESCRIBE "{view}"').fetchall()
    return {r[0]: r[1].split("(")[0].upper() for r in rows}


def profile_column(rs: RelStats, table: str, col: str, dtype: str, card: int) -> dict:
    con = rs.con
    q = lambda s: con.execute(s).fetchone()
    non_null = q(f'SELECT count("{col}") FROM "{table}"')[0]
    ndv = q(f'SELECT approx_count_distinct("{col}") FROM "{table}"')[0]
    out = {
        "dtype": dtype,
        "ndv": int(ndv),
        "null_frac": (card - non_null) / card if card else 0.0,
    }
    is_numeric = dtype in NUMERIC_TYPES
    if is_numeric and non_null > 0:
        lo, hi = q(f'SELECT min("{col}"), max("{col}") FROM "{table}"')
        out["min"], out["max"] = lo, hi
        if lo != hi:
            probs = [i / HIST_BUCKETS for i in range(HIST_BUCKETS + 1)]
            arr = "[" + ",".join(str(p) for p in probs) + "]"
            bounds = con.execute(
                f'SELECT approx_quantile("{col}", {arr}) FROM "{table}"'
            ).fetchone()[0]
            out["hist"] = [float(b) for b in bounds]   # length = HIST_BUCKETS+1
    # low-cardinality columns (string or numeric): record MCV
    if 0 < ndv <= MCV_MAX_NDV:
        rows = con.execute(
            f'SELECT "{col}" AS v, count(*) c FROM "{table}" '
            f'WHERE "{col}" IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT {MCV_TOPK}'
        ).fetchall()
        out["mcv"] = {str(v): c / card for v, c in rows}
    return out


def build(out_path: str, dataset: str = "ldbc_sf1") -> dict:
    rs = RelStats()
    catalog = {"dataset": dataset, "hist_buckets": HIST_BUCKETS, "tables": {}}
    for name, info in rs.tables.items():
        card = rs.cardinality(name)
        entry = {"kind": info.kind, "cardinality": card}
        types = _col_types(rs.con, name)
        if info.kind == "vertex":
            entry["label"] = info.label
            cols_to_profile = info.columns
        else:
            entry.update(src=info.src, dst=info.dst, rel=info.rel,
                         fanout_src=rs.fanout(name, "src"),
                         fanout_dst=rs.fanout(name, "dst"))
            cols_to_profile = info.edge_attrs   # for edges, only profile edge attributes (skip FKs)
        col_stats = {}
        for col in cols_to_profile:
            if col in ("id",) or "." in col:    # skip primary/foreign key id columns
                continue
            col_stats[col] = profile_column(rs, name, col, types.get(col, "VARCHAR"), card)
        entry["columns"] = col_stats
        catalog["tables"][name] = entry
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(catalog, f, indent=1)
    return catalog


if __name__ == "__main__":
    out = DEFAULT_OUT
    t0 = time.time()
    cat = build(out)
    dt = time.time() - t0
    size = os.path.getsize(out)
    ncols = sum(len(t["columns"]) for t in cat["tables"].values())
    print(f"catalog built: {out}")
    print(f"  {len(cat['tables'])} tables, {ncols} columns, {size/1024:.1f} KB, {dt:.1f}s")
