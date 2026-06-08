#!/usr/bin/env python3
"""CLI entry point for the ISPG Plan Optimizer.

Usage:
    # Fixed-hop sub-queries (recommended):
    python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-2
    python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-1-2
    python ispg/ldbc/ic/ldbc_query_optimizer.py --all

    # VarExpand queries require sub-query expansion first:
    python ispg/ldbc/gen_fixed_hop_subqueries.py
    python ispg/ldbc/ic/ldbc_query_optimizer.py --query ic-1-1 --query ic-1-2 --query ic-1-3
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ispg.core.estimator import GLogsEstimator, SchemaInfo, load_ldbc_schema   # noqa: E402
from ispg.ldbc.ic.optimizer import ISPGOptimizer                               # noqa: E402
from ispg.ldbc.ic.plan import plan_steps, plan_tree_str                        # noqa: E402

DEFAULT_GLOGS        = "catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode"
DEFAULT_GLOGS_SCRIPT = "scripts/glogs/estimate.sh"
DEFAULT_FILTER_DIR   = "ispg/ldbc/query_filters"


def _load_json(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _append_timing(timing_path: Path, query: str, elapsed_ms: float) -> None:
    header = "query,strategy,plan_generation_ms"
    line   = f"{query},ispg,{elapsed_ms:.3f}"
    if not timing_path.exists():
        timing_path.write_text(header + "\n" + line + "\n", encoding="utf-8")
    else:
        with timing_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def run_optimizer(
    query_name: str,
    repo_root:  Path,
    filter_dir: Path,
    estimator:  GLogsEstimator,
    cost_scale: float,
    schema:     SchemaInfo,
) -> None:
    qname       = query_name.lower()
    filter_path = filter_dir / f"{qname}_filters.json"
    filt        = _load_json(filter_path)

    output_dir  = repo_root / "ispg" / "ldbc" / "query_plan"
    output_dir.mkdir(parents=True, exist_ok=True)
    timing_path = output_dir / "plan_generation_time_ms.csv"

    t0  = time.perf_counter()
    opt = ISPGOptimizer(qname, filt, schema, estimator, cost_scale)
    plan = opt.optimize()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    out: List[str] = []
    out.append(f"[INFO] === Optimizing query {qname} (strategy=ispg) ===")
    out.append(
        f"[INFO] Input sources:\n"
        f"  filter_dir={filter_dir.relative_to(repo_root)}\n"
        f"  glogs_catalog={estimator.catalog_path.relative_to(repo_root)}\n"
        f"  glogs_script={estimator.script_path.relative_to(repo_root)}"
    )

    # Variable summary (singleton F values)
    out.append("[INFO] Variable F values (singleton estimate × selectivity):")
    for alias in sorted(opt.vertices):
        v = opt.vertices[alias]
        out.append(
            f"  alias={alias}, label={v.label}, domain={v.domain}, "
            f"F={opt._singleton_F[alias]:.6f}, sel={v.selectivity:.6f}"
        )

    if plan is None:
        out.append("[WARN] No plan found — check connectivity of the query graph.")
    else:
        out.append(f"\n=== ISPG best plan ({qname}, strategy=ispg) ===")
        out.append(f"  Total plan cost: {plan.total_cost:.6f}")
        out.extend(plan_steps(plan, opt))

        out.append("")
        out.append("[INFO] Plan tree:")
        out.extend("  " + ln for ln in plan_tree_str(plan))

        plan_type = "tree (bushy)" if plan.is_binary else "linear"
        out.append(f"\n[INFO] Plan shape: {plan_type}")

    output_path = output_dir / f"{qname}_ispg.plan"
    output_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[INFO] Plan output written to {output_path}")

    _append_timing(timing_path, qname, elapsed_ms)
    print(f"[INFO] Plan generation time (ms): {elapsed_ms:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ISPG Plan Optimizer — bottom-up DP, tree-shaped plans"
    )
    parser.add_argument("--query", action="append", dest="queries",
                        help="Query name, e.g. ic-2 or ic-1-2")
    parser.add_argument("--glogs",      default=DEFAULT_GLOGS)
    parser.add_argument("--script",     default=DEFAULT_GLOGS_SCRIPT)
    parser.add_argument("--json-dir",   default=DEFAULT_FILTER_DIR)
    parser.add_argument("--cost-scale", type=float, default=0.1)
    parser.add_argument("--all",        action="store_true",
                        help="Optimize all queries in the filter directory")
    args = parser.parse_args()

    repo_root  = Path(__file__).resolve().parents[3]
    filter_dir = (repo_root / args.json_dir).resolve()

    estimator = GLogsEstimator(
        repo_root=repo_root,
        catalog_rel=args.glogs,
        script_rel=args.script,
    )
    schema = load_ldbc_schema(repo_root)

    query_order: List[str] = []
    seen: Set[str] = set()

    def add_query(name: str) -> None:
        q = name.lower().removesuffix("_filters")
        if q not in seen:
            seen.add(q)
            query_order.append(q)

    for q in args.queries or []:
        add_query(q)

    if args.all:
        def _key(p: Path) -> Tuple[float, float, str]:
            stem = p.stem.removesuffix("_filters")
            parts = stem.split("-")
            try:
                n1 = float(parts[1]) if len(parts) > 1 else math.inf
                n2 = float(parts[2]) if len(parts) > 2 else 0.0
            except (IndexError, ValueError):
                n1 = n2 = math.inf
            return (n1, n2, stem)

        for path in sorted(filter_dir.glob("*_filters.json"), key=_key):
            add_query(path.stem)

    if not query_order:
        raise SystemExit("Specify at least one query via --query or --all")

    for qname in query_order:
        try:
            run_optimizer(
                query_name=qname,
                repo_root=repo_root,
                filter_dir=filter_dir,
                estimator=estimator,
                cost_scale=args.cost_scale,
                schema=schema,
            )
        except ValueError as exc:
            print(f"[SKIP] {qname}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
