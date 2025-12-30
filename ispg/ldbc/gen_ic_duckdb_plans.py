#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
IC_SRC_DIR = BASE / "ic_for_duckdb"
PARAMS_PATH = BASE / "ic" / "ic_params.json"
SETUP_SQL_PATH = BASE / "setup_ldbc_pgq.sql"
DB_PATH = ROOT / "ldbc_pgq_sf1.duckdb"
OUT_DIR = BASE / "query_plan_duckdb"
TIMING_CSV_PATH = OUT_DIR / "plan_generation_time_ms.csv"


@dataclass
class ParamResolver:
    params: Dict[str, Any]

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    def resolve(self, name: str) -> Tuple[Optional[Any], Optional[str]]:
        needle = self._norm(name)
        for key, value in self.params.items():
            variants = {
                key,
                key.lower(),
                key.replace("_", ""),
                key.replace("_", "").lower(),
            }
            for v in list(variants):
                # snake_to_camel + snake_to_pascal like
                parts = key.split("_")
                if parts:
                    camel = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
                    pascal = "".join(p[:1].upper() + p[1:] for p in parts)
                    variants.add(camel)
                    variants.add(pascal)
            for v in variants:
                if self._norm(v) == needle:
                    return value, key
        return None, None


_PARAM_RE = re.compile(r"\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    # treat as string
    s = str(value)
    s = s.replace("'", "''")
    return f"'{s}'"


def substitute_params(sql: str, resolver: ParamResolver) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group("name")
        value, _ = resolver.resolve(name)
        if value is None:
            raise KeyError(f"Missing parameter: ${name}")
        return _sql_literal(value)

    return _PARAM_RE.sub(repl, sql)


def _find_duckdb_cli() -> str:
    # Prefer user-installed duckdb, fallback to PATH
    preferred = str(Path.home() / ".duckdb" / "cli" / "1.4.3" / "duckdb")
    for cand in [preferred, "duckdb", str(Path.home() / ".duckdb" / "cli" / "latest" / "duckdb")]:
        try:
            proc = subprocess.run([cand, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if proc.returncode == 0:
                return cand
        except FileNotFoundError:
            continue
    raise FileNotFoundError("duckdb CLI not found")


def _append_timing_row(query: str, plan_ms: float, used_fallback: bool) -> None:
    header = "query,plan_generation_ms,used_fallback"
    line = f"{query},{plan_ms:.3f},{1 if used_fallback else 0}"
    if not TIMING_CSV_PATH.exists():
        TIMING_CSV_PATH.write_text(header + "\n" + line + "\n", encoding="utf-8")
        return
    with TIMING_CSV_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_duckdb_script(db_path: Path, script: str) -> subprocess.CompletedProcess[bytes]:
    duckdb_cli = _find_duckdb_cli()
    return subprocess.run(
        [duckdb_cli, str(db_path)],
        input=script.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def ensure_db() -> None:
    Path("/home/liyw/tmp/duckdb").mkdir(parents=True, exist_ok=True)
    setup_sql = SETUP_SQL_PATH.read_text(encoding="utf-8")
    proc = run_duckdb_script(
        DB_PATH,
        setup_sql + "\n",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "DuckDB setup failed\n"
            f"db={DB_PATH}\n"
            f"stdout:\n{proc.stdout.decode('utf-8', errors='replace')}\n"
            f"stderr:\n{proc.stderr.decode('utf-8', errors='replace')}\n"
        )


def explain_sql(sql: str) -> str:
    # Use CLI meta-commands to avoid truncation.
    script = """
LOAD duckpgq;
PRAGMA threads=1;
PRAGMA temp_directory='/home/liyw/tmp/duckdb';
PRAGMA explain_output='physical_only';
.mode line
.maxwidth 1000000

EXPLAIN
""" + sql.strip() + "\n"

    proc = run_duckdb_script(DB_PATH, script)
    if proc.returncode != 0:
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            "DuckDB EXPLAIN failed\n"
            f"returncode={proc.returncode}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}\n"
        )
    return proc.stdout.decode("utf-8", errors="replace")


def _find_matching_paren(s: str, open_idx: int) -> int:
    depth = 0
    in_str = False
    i = open_idx
    while i < len(s):
        ch = s[i]
        if ch == "'":
            # handle '' escaping
            if in_str and i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            in_str = not in_str
            i += 1
            continue
        if in_str:
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced parentheses")


_WITH_CTE_RE = re.compile(r"^\s*WITH\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.IGNORECASE)


def _split_first_cte(sql: str) -> Optional[Tuple[str, str, str]]:
    m = _WITH_CTE_RE.match(sql)
    if not m:
        return None
    name = m.group("name")
    open_idx = m.end() - 1  # points at '('
    close_idx = _find_matching_paren(sql, open_idx)
    cte_body = sql[open_idx + 1 : close_idx].strip()
    rest = sql[close_idx + 1 :].lstrip()
    if rest.startswith(","):
        rest = ("WITH" + rest[1:]).lstrip()
    elif rest.lower().startswith("with"):
        # already another WITH
        pass
    else:
        # rest should start with SELECT
        pass
    return name, cte_body, rest


_FROM_GT_RE = re.compile(r"\bFROM\s+GRAPH_TABLE\s*\(", re.IGNORECASE)


def _replace_from_graph_table(sql: str, tmp_table: str) -> Optional[Tuple[str, str]]:
    m = _FROM_GT_RE.search(sql)
    if not m:
        return None
    open_idx = m.end() - 1
    close_idx = _find_matching_paren(sql, open_idx)
    gt_call = sql[m.start() + len("FROM ") : close_idx + 1]
    graph_select = f"SELECT * FROM {gt_call}"
    rewritten = sql[: m.start()] + f"FROM {tmp_table} " + sql[close_idx + 1 :]
    return graph_select, rewritten


def _infer_schema_from_graph_select(graph_select: str) -> list[tuple[str, str]]:
    # Extract COLUMNS(...) from GRAPH_TABLE(...) and infer a usable schema.
    m = re.search(r"\bCOLUMNS\s*\(", graph_select, flags=re.IGNORECASE)
    if not m:
        raise ValueError("GRAPH_TABLE COLUMNS(...) not found")
    open_idx = m.end() - 1
    close_idx = _find_matching_paren(graph_select, open_idx)
    cols_body = graph_select[open_idx + 1 : close_idx]

    items: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str = False
    i = 0
    while i < len(cols_body):
        ch = cols_body[i]
        if ch == "'":
            if in_str and i + 1 < len(cols_body) and cols_body[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_str = not in_str
            buf.append(ch)
            i += 1
            continue
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                item = "".join(buf).strip()
                if item:
                    items.append(item)
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)

    schema: list[tuple[str, str]] = []
    for item in items:
        # Prefer explicit AS alias
        m_as = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", item, flags=re.IGNORECASE)
        if m_as:
            name = m_as.group(1)
            expr = item[: m_as.start()].strip()
        else:
            # Fallback: last identifier
            parts = re.split(r"\s+", item.strip())
            name = parts[-1]
            expr = item

        e = expr.lower()
        if any(tok in e for tok in [".id", "_id", "personid", "postid", "commentid", "forumid", "tagid", "placeid", "organisationid"]):
            typ = "BIGINT"
        elif any(tok in e for tok in ["creationdate", "workfrom", "joindate", "birthday"]):
            # LDBC timestamps tend to be BIGINT millis
            typ = "BIGINT"
        elif any(tok in e for tok in ["firstname", "lastname", "name", "title", "content", "imagefile", "language", "email"]):
            typ = "VARCHAR"
        elif re.fullmatch(r"\d+", expr.strip()):
            typ = "INTEGER"
        else:
            typ = "VARCHAR"
        schema.append((name, typ))

    if not schema:
        raise ValueError("empty schema inferred")
    return schema


def explain_sql_with_fallback(sql: str) -> str:
    try:
        return explain_sql(sql)
    except RuntimeError as exc:
        msg = str(exc)
        # Heuristic: segfault/crash often yields empty stdout/stderr with returncode 139/-11
        if "returncode=139" not in msg and "returncode=-11" not in msg:
            raise

        tmp_table = "__gt"
        split = _split_first_cte(sql)
        if split is not None:
            cte_name, cte_body, rest = split
            plan_graph = explain_sql(cte_body)
            schema = _infer_schema_from_graph_select(cte_body)
            cols_sql = ", ".join(f"{n} {t}" for n, t in schema)
            create_stmt = f"CREATE OR REPLACE TEMP TABLE {cte_name} ({cols_sql});"
            script = f"""
LOAD duckpgq;
PRAGMA threads=1;
PRAGMA temp_directory='/home/liyw/tmp/duckdb';
{create_stmt}
PRAGMA explain_output='physical_only';
.mode line
.maxwidth 1000000

EXPLAIN
{rest.strip()}
"""
            proc = run_duckdb_script(DB_PATH, script)
            if proc.returncode != 0:
                raise
            plan_sql = proc.stdout.decode("utf-8", errors="replace")
            return (
                "-- NOTE: DuckDB/duckpgq crashed on one-shot EXPLAIN; using fallback (create empty TEMP TABLE, do not execute GRAPH_TABLE)\n\n"
                + "-- [GRAPH_TABLE PLAN]\n"
                + plan_graph
                + "\n\n-- [RELATIONAL PLAN (against empty TEMP TABLE)]\n"
                + plan_sql
            )

        rep = _replace_from_graph_table(sql, tmp_table)
        if rep is None:
            raise
        graph_select, rewritten = rep
        plan_graph = explain_sql(graph_select)
        schema = _infer_schema_from_graph_select(graph_select)
        cols_sql = ", ".join(f"{n} {t}" for n, t in schema)
        script = f"""
LOAD duckpgq;
PRAGMA threads=1;
PRAGMA temp_directory='/home/liyw/tmp/duckdb';
CREATE OR REPLACE TEMP TABLE {tmp_table} ({cols_sql});
PRAGMA explain_output='physical_only';
.mode line
.maxwidth 1000000

EXPLAIN
{rewritten.strip()}
"""
        proc = run_duckdb_script(DB_PATH, script)
        if proc.returncode != 0:
            raise
        plan_sql = proc.stdout.decode("utf-8", errors="replace")
        return (
            "-- NOTE: DuckDB/duckpgq crashed on one-shot EXPLAIN; using fallback (create empty TEMP TABLE, do not execute GRAPH_TABLE)\n\n"
            + "-- [GRAPH_TABLE PLAN]\n"
            + plan_graph
            + "\n\n-- [RELATIONAL PLAN (against empty TEMP TABLE)]\n"
            + plan_sql
        )


def main() -> None:
    if not IC_SRC_DIR.exists():
        raise SystemExit(f"Missing directory: {IC_SRC_DIR}")

    params_all = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))

    ensure_db()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sql_files = sorted(IC_SRC_DIR.glob("IC-*.sql"))
    if not sql_files:
        raise SystemExit(f"No IC sql files in {IC_SRC_DIR}")

    failures: list[str] = []

    for path in sql_files:
        m = re.match(r"IC-(\d+)\.sql$", path.name)
        if not m:
            continue
        qid = int(m.group(1))
        key = f"ic-{qid}"
        params = params_all.get(key, {})
        resolver = ParamResolver(params=params)

        raw_sql = path.read_text(encoding="utf-8")
        try:
            sql = substitute_params(raw_sql, resolver)
            t0 = time.perf_counter()
            plan = explain_sql_with_fallback(sql)
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0
            used_fallback = plan.lstrip().startswith("-- NOTE: DuckDB/duckpgq crashed")
            out_path = OUT_DIR / f"ic-{qid}_duckdb.plan"
            out_path.write_text(sql.strip() + "\n\n" + plan, encoding="utf-8")
            print(f"[OK] {key} -> {out_path}")
            # Timing excludes file writes (plan output + CSV itself).
            _append_timing_row(key, elapsed_ms, used_fallback)
            print(
                f"[TIME] {key}: plan_generation_ms={elapsed_ms:.3f}, used_fallback={1 if used_fallback else 0} -> {TIMING_CSV_PATH}"
            )
        except Exception as e:
            failures.append(f"{key}: {e}")

    if failures:
        print("\n[FAIL] Some queries failed:")
        for f in failures:
            print("  " + f)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
