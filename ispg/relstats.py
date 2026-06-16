"""Relational-side statistics (the relational half of the StatsProvider).

Reads the raw LDBC SNB datagen CSVs directly with DuckDB (pipe-delimited, with
attribute columns) and provides, for the ISPG cost model:
  - sel(theta | ell):  fraction of tuples of relation `ell` satisfying predicate theta
  - fo(R'):            relation cardinality / distinct join-key values  (fanout)
plus vertex/edge table cardinalities and column summaries.

This module is OFFLINE only: it is used by build_catalog.py to generate the compact
relational statistics catalog (catalogs/<dataset>_relstats.json). Query-time plan
generation reads that JSON via statscatalog.py and never touches the raw data or DuckDB.
Place the raw dataset under the path below (or set ISPG_DATA_DIR).

Note: this is the *relational* statistics pipeline. It is independent of GLogS, which
supplies the *structural* statistics F(P'), sigma_e. GLogS does not handle predicates;
sel/fo always come from here.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from functools import lru_cache

import duckdb

_PROJ_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.environ.get("ISPG_DATA_DIR", os.path.join(_PROJ_ROOT, "data", "ldbc", "sf1"))

# LDBC datagen vertex table names (single lowercase token). Edge tables are <src>_<rel>_<dst>.
VERTEX_NAMES = {
    "person", "comment", "post", "message", "forum",
    "tag", "tagclass", "place", "organisation",
}


@dataclass
class TableInfo:
    name: str                 # filename without _0_0.csv, e.g. person / person_knows_person
    path: str
    columns: list[str]
    kind: str                 # "vertex" | "edge"
    # vertex: label = capitalized label name (Person);  edge: src/dst = endpoint vertex names, rel = relation name
    label: str | None = None
    src: str | None = None
    dst: str | None = None
    rel: str | None = None
    src_key: str | None = None  # FK column referencing the src vertex
    dst_key: str | None = None  # FK column referencing the dst vertex
    edge_attrs: list[str] = field(default_factory=list)


def _cap(name: str) -> str:
    return name[:1].upper() + name[1:]


def _parse_edge(name: str, columns: list[str]) -> tuple[str, str, str]:
    """Split <src>_<rel>_<dst> into (src, rel, dst). Vertex names are single tokens, so
    the first/last token are the endpoints."""
    parts = name.split("_")
    src = parts[0]
    dst = parts[-1]
    rel = "_".join(parts[1:-1])
    return src, rel, dst


class RelStats:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.con = duckdb.connect()
        self.tables: dict[str, TableInfo] = {}
        self._discover_and_register()

    # ---------- discovery & registration ----------
    def _read_header(self, path: str) -> list[str]:
        rel = self.con.execute(
            f"SELECT * FROM read_csv('{path}', delim='|', header=true, sample_size=1) LIMIT 0"
        )
        return [d[0] for d in rel.description]

    def _discover_and_register(self) -> None:
        files = sorted(
            glob.glob(os.path.join(self.data_dir, "dynamic", "*.csv"))
            + glob.glob(os.path.join(self.data_dir, "static", "*.csv"))
        )
        for path in files:
            name = os.path.basename(path).replace("_0_0.csv", "")
            cols = self._read_header(path)
            # register as a view (a view does not scan immediately; data is read at query time)
            self.con.execute(
                f'CREATE OR REPLACE VIEW "{name}" AS '
                f"SELECT * FROM read_csv('{path}', delim='|', header=true, "
                f"auto_detect=true, ignore_errors=true)"
            )
            if name in VERTEX_NAMES:
                info = TableInfo(name=name, path=path, columns=cols, kind="vertex",
                                 label=_cap(name))
            else:
                src, rel, dst = _parse_edge(name, cols)
                # endpoint FK columns = first two columns (LDBC header is X.id / Y.id or X.id_1)
                src_key, dst_key = cols[0], cols[1]
                edge_attrs = cols[2:]
                info = TableInfo(name=name, path=path, columns=cols, kind="edge",
                                 src=src, dst=dst, rel=rel,
                                 src_key=src_key, dst_key=dst_key,
                                 edge_attrs=list(edge_attrs))
            self.tables[name] = info

    # ---------- basic statistics ----------
    @lru_cache(maxsize=4096)
    def cardinality(self, table: str) -> int:
        return self.con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]

    @lru_cache(maxsize=4096)
    def distinct(self, table: str, column: str) -> int:
        return self.con.execute(
            f'SELECT count(DISTINCT "{column}") FROM "{table}"'
        ).fetchone()[0]

    # ---------- the two core quantities ISPG needs ----------
    def fanout(self, edge_table: str, by: str = "src") -> float:
        """fo: edge cardinality / endpoint distinct values = average rows per key value.

        by="src": per source vertex (average out-degree when expanding from the src vertex)
        by="dst": per target vertex (in-degree)
        """
        info = self.tables[edge_table]
        assert info.kind == "edge", f"{edge_table} is not an edge table"
        key = info.src_key if by == "src" else info.dst_key
        card = self.cardinality(edge_table)
        ndv = self.distinct(edge_table, key)
        return card / ndv if ndv else 0.0

    def selectivity(self, table: str, where_sql: str) -> float:
        """sel(theta | ell): fraction of tuples of `table` satisfying where_sql (exact scan)."""
        total = self.cardinality(table)
        if total == 0:
            return 0.0
        hit = self.con.execute(
            f'SELECT count(*) FROM "{table}" WHERE {where_sql}'
        ).fetchone()[0]
        return hit / total

    def column_summary(self, table: str, column: str) -> dict:
        """Column summary: NDV, min, max, null fraction. Used as a default when no concrete
        value is given."""
        total = self.cardinality(table)
        row = self.con.execute(
            f'SELECT approx_count_distinct("{column}"), min("{column}"), '
            f'max("{column}"), count("{column}") FROM "{table}"'
        ).fetchone()
        ndv, lo, hi, non_null = row
        return {
            "ndv": ndv, "min": lo, "max": hi,
            "null_frac": (total - non_null) / total if total else 0.0,
        }


if __name__ == "__main__":
    rs = RelStats()
    print(f"== discovered {len(rs.tables)} tables ==")
    verts = [t for t in rs.tables.values() if t.kind == "vertex"]
    edges = [t for t in rs.tables.values() if t.kind == "edge"]

    print("\n-- vertex table cardinalities --")
    for t in verts:
        print(f"  {t.label:14s} {rs.cardinality(t.name):>10,}  cols={t.columns}")

    print("\n-- edge table cardinality / fanout(src->dst) --")
    for t in edges:
        c = rs.cardinality(t.name)
        fo_s = rs.fanout(t.name, "src")
        fo_d = rs.fanout(t.name, "dst")
        attr = f"  edge_attrs={t.edge_attrs}" if t.edge_attrs else ""
        print(f"  {t.name:34s} {c:>10,}  fo_src={fo_s:6.2f} fo_dst={fo_d:6.2f}{attr}")

    print("\n-- predicate selectivity examples (exact scan) --")
    examples = [
        ("person", "gender = 'male'"),
        ("person", "birthday < 315532800000"),          # born before 1980 (epoch ms)
        ("person", "language LIKE '%en%'"),
        ("comment", "length > 100"),
        ("post", "language = 'en'"),
        ("place", "type = 'country'"),
        ("place", "type = 'city'"),
        ("organisation", "type = 'company'"),
        ("person_knows_person", "creationDate > 1300000000000"),  # edge predicate
    ]
    for tbl, pred in examples:
        sel = rs.selectivity(tbl, pred)
        print(f"  sel[{tbl}: {pred}] = {sel:.4f}")
