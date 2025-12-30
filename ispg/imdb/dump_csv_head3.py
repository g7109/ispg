#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p.name != "ispg" and p.parent != p:
        p = p.parent
    return p.parent if p.name == "ispg" else Path(__file__).resolve().parents[2]


def read_head_lines(file_path: Path, n: int) -> list[str]:
    lines: list[str] = []
    try:
        with file_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            for _ in range(n):
                line = f.readline()
                if not line:
                    break
                lines.append(line.rstrip("\n"))
    except OSError as e:
        lines.append(f"<ERROR: {e}>\n")
    return lines


def main() -> int:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Dump first N lines of all .csv files under a directory into a single txt file."
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=repo_root / "datasets/imdb/imdb_graph",
        help="Source directory containing .csv files.",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        default=repo_root / "ispg/imdb/imdb_graph_csv_head3.txt",
        help="Output txt file path.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="Number of lines to dump from each csv.",
    )

    args = parser.parse_args()
    src: Path = args.src
    dst: Path = args.dst
    n: int = args.n

    if n <= 0:
        raise SystemExit("--n must be positive")

    if not src.exists() or not src.is_dir():
        raise SystemExit(f"Source directory not found: {src}")

    csv_files = sorted([p for p in src.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])
    dst.parent.mkdir(parents=True, exist_ok=True)

    with dst.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# src={src}\n")
        out.write(f"# files={len(csv_files)}\n")
        out.write(f"# head_lines={n}\n\n")

        for p in csv_files:
            out.write(f"==== {p.name} ====\n")
            head = read_head_lines(p, n)
            if not head:
                out.write("<EMPTY>\n")
            else:
                for line in head:
                    out.write(line)
                    out.write("\n")
            out.write("\n")

    print(f"Wrote: {dst} (files={len(csv_files)}, head={n})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
