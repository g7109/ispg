"""Generate query plan files.

For each query, generate three plans in the unified operator space and write them as
render_ascii text into separate folders for comparison:
  - ispg   : the cost-based interleaved plan (exhaustive DP, Alg. 1)
  - greedy : the polynomial-time greedy variant (Alg. 2)
  - relgo  : the MATCH-first baseline

    plans/
      ldbc/{ispg,greedy,relgo}/    ic1-1.txt ...
      job/{ispg,greedy,relgo}/     1a.txt ...

Usage:
    python main.py                      # all LDBC (and JOB if available)
    python main.py ic7-1 ic3-1          # only the named LDBC queries
    python main.py --bench job          # only JOB
    python main.py --out /tmp/plans     # custom output root (default <project_root>/plans)

Plan generation only reads the prebuilt statistics (relational catalog JSON + GLogS
catalog via PathCE); it loads no DuckDB and starts no service.
"""
from __future__ import annotations

import os
import sys

from optimizer import Optimizer, render_ascii
from queries import REGISTRY
from stats import Stats

# default output: <project_root>/plans  (project root = parent of the ispg/ package)
_DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plans")


def _load_benches() -> dict[str, tuple[dict, "Stats"]]:
    """Return {bench_name: (registry, stats)} for the available benchmarks."""
    benches: dict[str, tuple] = {"ldbc": (REGISTRY, Stats())}
    from queries_job import JOB_REGISTRY
    from stats_imdb import ImdbStats
    benches["job"] = (JOB_REGISTRY, ImdbStats())
    return benches


def _parse_args(argv: list[str]) -> tuple[list[str], str, str | None]:
    out = _DEFAULT_OUT
    bench = None
    names: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--out", "-o"):
            out = argv[i + 1]; i += 2
        elif a in ("--bench", "-b"):
            bench = argv[i + 1]; i += 2
        else:
            names.append(a); i += 1
    return names, out, bench


def _generate_bench(bench: str, registry: dict, stats: "Stats",
                    names: list[str] | None, out_root: str) -> tuple[int, list]:
    names = names or list(registry)
    ispg_dir = os.path.join(out_root, bench, "ispg")
    relgo_dir = os.path.join(out_root, bench, "relgo")
    greedy_dir = os.path.join(out_root, bench, "greedy")
    for d in (ispg_dir, relgo_dir, greedy_dir):
        os.makedirs(d, exist_ok=True)

    opt = Optimizer(stats)
    ok, failed = 0, []
    for name in names:
        if name not in registry:
            failed.append((f"{bench}/{name}", "not registered"))
            continue
        q = registry[name]
        for strategy, fn, folder in (("ISPG", opt.optimize, ispg_dir),
                                     ("RelGo", opt.optimize_relgo, relgo_dir),
                                     ("Greedy", opt.optimize_greedy, greedy_dir)):
            opt._freq_cache.clear()          # clear cache per query/strategy (freq is query-bound)
            path = os.path.join(folder, f"{name}.txt")
            try:
                text = render_ascii(fn(q))
            except Exception as e:           # strategy not applicable (e.g. RelGo on a relation-rooted query)
                text = f"=== {name} [{strategy}] ===\n!! cannot generate: {type(e).__name__}: {e}"
                failed.append((f"{bench}/{name}/{strategy}", str(e)))
            else:
                ok += 1
            with open(path, "w") as f:
                f.write(text + "\n")
    return ok, failed


def generate(names: list[str] | None = None, out_root: str = _DEFAULT_OUT,
             bench: str | None = None) -> None:
    benches = _load_benches()
    selected = [bench] if bench else list(benches)
    total_ok, total_failed = 0, []
    for b in selected:
        if b not in benches:
            print(f"unknown benchmark: {b} (available: {', '.join(benches)})")
            continue
        registry, stats = benches[b]
        ok, failed = _generate_bench(b, registry, stats, names, out_root)
        total_ok += ok
        total_failed += failed

    print(f"generated {total_ok} plans -> {os.path.abspath(out_root)}/<bench>/{{ispg,greedy,relgo}}/")
    if total_failed:
        print(f"{len(total_failed)} item(s) failed:")
        for n, msg in total_failed:
            print(f"  - {n}: {msg}")


def main() -> None:
    names, out, bench = _parse_args(sys.argv[1:])
    generate(names or None, out, bench)


if __name__ == "__main__":
    main()
