"""O(1) estimator over the relational statistics catalog (query-time half of the
StatsProvider).

Loads the compact JSON produced by build_catalog.py and answers, using
histograms / MCV / NDV, in O(1):
  - selectivity(table, column, op, value):  predicate selectivity sel(theta | ell)
  - fanout(edge, by):                        relation fanout fo(R')
  - estimate(table, preds, how):             multi-predicate conjunction/disjunction
                                             (independence assumption)
It never touches the raw data, satisfying the ms-level latency goal. The catalog JSON is
produced by build_catalog.py.
"""
from __future__ import annotations

import json
import os

DEFAULT_PATH = os.environ.get(
    "ISPG_RELSTATS",
    os.path.join(os.path.dirname(__file__), "catalogs", "ldbc_sf1_relstats.json"),
)

# Neutral estimates used when the catalog file is not present.
_FALLBACK_SEL = 1.0
_FALLBACK_FANOUT = 1.0


class RelCatalog:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self.fallback = not os.path.exists(path)
        if self.fallback:
            self.cat = {"dataset": "(unavailable)", "hist_buckets": 1, "tables": {}}
        else:
            with open(path) as f:
                self.cat = json.load(f)
        self.tables = self.cat["tables"]
        self.B = self.cat["hist_buckets"]

    # ---------- basics ----------
    def cardinality(self, table: str) -> int:
        if table not in self.tables:
            return 0
        return self.tables[table]["cardinality"]

    def fanout(self, edge: str, by: str = "src") -> float:
        if edge not in self.tables:
            return _FALLBACK_FANOUT
        t = self.tables[edge]
        return t["fanout_src"] if by == "src" else t["fanout_dst"]

    def _col(self, table: str, column: str) -> dict:
        return self.tables[table]["columns"][column]

    # ---------- histogram: fraction of whole table with col < v (nulls excluded) ----------
    def _lt(self, c: dict, v) -> float:
        nn = 1.0 - c.get("null_frac", 0.0)        # non-null mass
        hist = c.get("hist")
        if hist is None:                          # no histogram: linear interpolation on min/max
            lo, hi = c.get("min"), c.get("max")
            if lo is None or hi is None or hi == lo:
                return 0.0
            if v <= lo:
                return 0.0
            if v >= hi:
                return nn
            return (v - lo) / (hi - lo) * nn
        B = self.B
        if v <= hist[0]:
            return 0.0
        if v >= hist[-1]:
            return nn
        for i in range(B):
            if hist[i] <= v < hist[i + 1]:
                width = hist[i + 1] - hist[i]
                frac = (v - hist[i]) / width if width else 0.0
                return (i + frac) / B * nn
        return nn

    # ---------- selectivity ----------
    def selectivity(self, table: str, column: str, op: str, value=None) -> float:
        if self.fallback or table not in self.tables:
            return _FALLBACK_SEL
        cols = self.tables[table]["columns"]
        if column not in cols:
            # un-profiled column (e.g. primary-key id): equality ~ 1/cardinality (unique),
            # otherwise a conservative heuristic.
            card = self.tables[table]["cardinality"]
            if op.lower().strip() in ("=", "=="):
                return 1.0 / card if card else 0.0
            return 0.3
        c = self._col(table, column)
        nn = 1.0 - c.get("null_frac", 0.0)
        op = op.lower().strip()
        if op in ("is null", "isnull"):
            return c.get("null_frac", 0.0)
        if op in ("is not null", "notnull"):
            return nn
        if op in ("=", "=="):
            mcv = c.get("mcv", {})
            key = str(value)
            if key in mcv:
                return mcv[key]
            mcv_mass = sum(mcv.values())
            ndv = max(1, c.get("ndv", 1))
            rem_ndv = max(1, ndv - len(mcv))
            return max(0.0, (nn - mcv_mass)) / rem_ndv
        if op in ("!=", "<>"):
            return max(0.0, nn - self.selectivity(table, column, "=", value))
        if op == "<":
            return self._lt(c, value)
        if op == "<=":
            return self._lt(c, value)            # continuous approximation
        if op == ">":
            return max(0.0, nn - self._lt(c, value))
        if op == ">=":
            return max(0.0, nn - self._lt(c, value))
        if op == "between":                       # value = (lo, hi)
            lo, hi = value
            return max(0.0, self._lt(c, hi) - self._lt(c, lo))
        if op == "in":                            # value = [..]
            return min(nn, sum(self.selectivity(table, column, "=", v) for v in value))
        if op == "like":                          # crude heuristic (to be refined)
            return 0.05
        raise ValueError(f"unknown operator: {op}")

    def estimate(self, table: str, preds: list[tuple], how: str = "and") -> float:
        """Combine multiple predicates (independence assumption). preds = [(col, op, value), ...]"""
        sels = [self.selectivity(table, col, op, val) for col, op, val in preds]
        if not sels:
            return 1.0
        if how == "and":
            p = 1.0
            for s in sels:
                p *= s
            return p
        # or: 1 - prod(1-s)
        p = 1.0
        for s in sels:
            p *= (1 - s)
        return 1 - p


if __name__ == "__main__":
    import time

    from relstats import RelStats

    rc = RelCatalog()
    rs = RelStats()   # only for exact ground-truth comparison

    cases = [
        ("person", "gender", "=", "male"),
        ("person", "gender", "=", "female"),
        ("person", "birthday", "<", 315532800000),     # before 1980
        ("person", "birthday", "<", 500000000000),      # ~1985
        ("person", "birthday", ">", 600000000000),
        ("person", "language", "=", "en"),
        ("comment", "length", ">", 100),
        ("comment", "length", "<", 50),
        ("comment", "creationDate", "<", 1313591219961),
        ("post", "language", "=", "uz"),
        ("place", "type", "=", "country"),
        ("place", "type", "=", "city"),
        ("organisation", "type", "=", "company"),
        ("person_knows_person", "creationDate", ">", 1300000000000),
        ("forum_hasMember_person", "joinDate", ">", 1300000000000),
    ]

    op_sql = {"=": "=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}
    print(f"{'table.col op val':52s} {'est':>9s} {'exact':>9s} {'abs_err':>9s}")
    t_est = 0.0
    max_err = 0.0
    for tbl, col, op, val in cases:
        t0 = time.perf_counter()
        est = rc.selectivity(tbl, col, op, val)
        t_est += time.perf_counter() - t0
        vsql = f"'{val}'" if isinstance(val, str) else val
        true = rs.selectivity(tbl, f'"{col}" {op_sql[op]} {vsql}')
        err = abs(est - true)
        max_err = max(max_err, err)
        label = f"{tbl}.{col} {op} {val}"
        print(f"{label:52s} {est:9.4f} {true:9.4f} {err:9.4f}")
    print(f"\nmax abs error = {max_err:.4f}")
    print(f"total time for 15 estimates = {t_est*1000:.3f} ms  (~{t_est/len(cases)*1e6:.1f} us each)")

    print("\n-- fanout O(1) sample --")
    for e in ("person_knows_person", "person_likes_message", "comment_hasCreator_person"):
        print(f"  {e:30s} fo_src={rc.fanout(e,'src'):7.2f} fo_dst={rc.fanout(e,'dst'):7.2f}")
