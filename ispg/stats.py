"""StatsProvider: the fused statistics catalog of the paper (Def. 3).

Two independent halves, combined into one frequency measure:
  - relational side  : selectivity / fanout from statscatalog (a compact JSON derived
                       from the dataset; ratios, hence scale-free).
  - structural side  : F(P') from GLogS, queried by shelling out to the `pattern_count`
                       binary against a prebuilt GLogS catalog (.bincode).

Because sel/fo are scale-free ratios, F(U) = F_struct * prod(sel) * prod(fo) is a
relative estimate consistent for plan comparison (Def. 3), regardless of the catalog
scale factor.

Artifact locations are anchored under the PathCE submodule at <project_root>/ref, and can
be overridden with the ISPG_REF_DIR / ISPG_GLOGS_* environment variables.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

from statscatalog import RelCatalog

VLABEL2TABLE = {
    "PERSON": "person", "COMMENT": "comment", "POST": "post", "MESSAGE": "message",
    "FORUM": "forum", "TAG": "tag", "TAGCLASS": "tagclass",
    "PLACE": "place", "ORGANISATION": "organisation",
}

# ---- artifact locations, anchored inside the project (PathCE submodule `ref/`) ----
_PKG_DIR = os.path.dirname(__file__)                       # <root>/ispg
_PROJ_ROOT = os.path.dirname(_PKG_DIR)                      # <root>
_REF = os.environ.get("ISPG_REF_DIR", os.path.join(_PROJ_ROOT, "ref"))

GLOGS_BIN = os.environ.get(
    "ISPG_GLOGS_BIN", os.path.join(_REF, "glogs", "ir", "target", "release", "pattern_count"))
GLOGS_CATALOG = os.environ.get(
    "ISPG_GLOGS_CATALOG", os.path.join(_REF, "catalogs", "ldbc", "glogs", "ldbc_sf0.003.bincode"))
GLOGS_SCHEMA = os.environ.get(
    "ISPG_GLOGS_SCHEMA", os.path.join(_REF, "schemas", "ldbc", "ldbc_glogs_schema.json"))


def _load_schema(path: str):
    """Load a GLogS schema; return (ent_id, ent_name, rel_id) or empty maps if absent."""
    if not os.path.exists(path):
        return {}, {}, {}
    sd = json.load(open(path))
    ent_id = {e["label"]["name"].upper(): e["label"]["id"] for e in sd["entities"]}
    ent_name = {e["label"]["name"].lower(): e["label"]["name"] for e in sd["entities"]}
    rel_id = {r["label"]["name"]: r["label"]["id"] for r in sd["relations"]}
    return ent_id, ent_name, rel_id


class Stats:
    def __init__(self, catalog_path: str | None = None, glogs_catalog: str | None = None,
                 glogs_schema: str | None = None, glogs_bin: str | None = None):
        self.rc = RelCatalog(catalog_path) if catalog_path else RelCatalog()
        self.edge_index: dict[tuple[str, str, str], str] = {}
        for name, t in self.rc.tables.items():
            if t["kind"] != "edge":
                continue
            rel = t["rel"].upper()
            s, d = t["src"].upper(), t["dst"].upper()
            self.edge_index[(rel, s, d)] = name
            self.edge_index.setdefault((rel, d, s), name)

        self.glogs_schema = glogs_schema or GLOGS_SCHEMA
        self.ent_id, self.ent_name, self.rel_id = _load_schema(self.glogs_schema)
        self.glogs_catalog = glogs_catalog or GLOGS_CATALOG
        self.glogs_bin = glogs_bin or GLOGS_BIN
        # Structural estimates need both the GLogS schema and the relational tables (to
        # resolve an edge's endpoint labels).
        self.struct_ok = bool(self.ent_id) and not self.rc.fallback
        self._glogs_cache: dict[str, float] = {}

    def selectivity(self, table: str, column: str, op: str, value=None) -> float:
        return self.rc.selectivity(table, column, op, value)

    def fanout(self, edge_table: str, by: str = "src") -> float:
        return self.rc.fanout(edge_table, by)

    def resolve_edge(self, rel_label: str, src_label: str, dst_label: str) -> str:
        key = (rel_label.upper(), src_label.upper(), dst_label.upper())
        if key not in self.edge_index:
            if self.rc.fallback:
                return ""
            raise KeyError(f"unknown edge: {key}")
        return self.edge_index[key]

    def _glogs(self, pattern: dict) -> float:
        """Query the GLogS pattern_count binary for the pattern's structural frequency.
        Returns 1.0 if the query cannot be evaluated."""
        key = json.dumps(pattern, sort_keys=True)
        if key in self._glogs_cache:
            return self._glogs_cache[key]
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(pattern, tmp)
        tmp.close()
        try:
            r = subprocess.run([self.glogs_bin, "-c", self.glogs_catalog, "-p", tmp.name],
                               capture_output=True, text=True, check=True)
            tok = r.stdout.strip().splitlines()[0].replace(",", " ").split()
            val = max(float(tok[0]), 1.0)
        except Exception:
            val = 1.0
        finally:
            os.unlink(tmp.name)
        self._glogs_cache[key] = val
        return val

    def vlabel_card(self, label: str) -> float:
        if not self.struct_ok or label.upper() not in self.ent_id:
            return 1.0
        return self._glogs({"vertices": [{"tag_id": 0, "label_id": self.ent_id[label.upper()]}],
                            "edges": []})

    def structural_freq(self, var_label: dict[str, str],
                        edges: list[tuple[str, str, str]]) -> float:
        """Structural frequency F(P') of a subpattern from GLogS. Returns 1.0 when the
        structural statistics do not cover the requested labels/edges."""
        if not var_label or not self.struct_ok:
            return 1.0
        try:
            vs = sorted(var_label)
            tmap = {v: i for i, v in enumerate(vs)}
            gv = [{"tag_id": tmap[v], "label_id": self.ent_id[var_label[v].upper()]} for v in vs]
            ge = []
            for i, (s, d, tbl) in enumerate(edges):
                t = self.rc.tables[tbl]
                sname, dname = self.ent_name[t["src"]], self.ent_name[t["dst"]]
                rid = self.rel_id[f"{sname}_{t['rel']}_{dname}"]
                if var_label[s].lower() == t["src"]:
                    gs, gd = tmap[s], tmap[d]
                else:
                    gs, gd = tmap[d], tmap[s]
                ge.append({"tag_id": i, "src": gs, "dst": gd, "label_id": rid})
        except (KeyError, IndexError):
            return 1.0
        return self._glogs({"vertices": gv, "edges": ge})
