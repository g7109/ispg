#!/usr/bin/env python3
"""Compare generated ISPG plans against the expected order in ic1~12.txt.

Heuristics:
- Expected order is taken from the //ISPG (or //SPJG) block if present.
- If a query section has no ISPG/Relgo split, treat the single pipeline as expected.
- We compare only traversal operations: varExpand/expand_vec/expandInto (and ignore filters, projects, top, reduce).
- Relation names are normalized and lightly synonym-mapped (hasCreated -> hasCreator, beliked -> likes, etc.).

This is intended as a sanity check tool, not a strict formal verifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
TXT_PATH = ROOT / "ispg" / "ldbc" / "ic" / "ic1~12.txt"
PLAN_DIR = ROOT / "ispg" / "ldbc" / "query_plan"


def norm_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


REL_SYNONYMS = {
    "hascreated": "hascreator",
    "hascreator": "hascreator",
    "beliked": "likes",
    "liked": "likes",
    "likes": "likes",
    "hasreply": "replyof",
    "replyof": "replyof",
}


def norm_rel(s: str) -> str:
    t = norm_token(s)
    return REL_SYNONYMS.get(t, t)


def rel_from_relation_label(label: str) -> str:
    # Examples: Person_knows_Person -> knows, Post_hasCreator_Person -> hasCreator
    parts = (label or "").split("_")
    mid = parts[1] if len(parts) >= 3 else (label or "")
    return norm_rel(mid)


@dataclass
class Step:
    op: str  # varexpand|expand|expandinto
    rel: str
    src: str
    dst: str
    domain: str = ""  # match|sql|?


def parse_expected_from_txt(txt: str) -> Dict[str, List[Step]]:
    # Split sections by "## ic N #"
    sec_re = re.compile(r"^##\s*ic\s*(\d+)\s*#", re.IGNORECASE)
    pipeline_re = re.compile(r"^\s*//\s*(ispg|spjg|relgo)\b", re.IGNORECASE)

    sections: Dict[str, List[str]] = {}
    current_key: Optional[str] = None
    buf: List[str] = []

    for line in txt.splitlines():
        m = sec_re.match(line.strip())
        if m:
            if current_key is not None:
                sections[current_key] = buf
            current_key = f"ic-{int(m.group(1))}"
            buf = []
            continue
        if current_key is not None:
            buf.append(line.rstrip("\n"))

    if current_key is not None:
        sections[current_key] = buf

    # Extract expected pipeline per section
    expected: Dict[str, List[Step]] = {}

    for q, lines in sections.items():
        # Collect pipelines
        pipelines: Dict[str, List[str]] = {}
        active_name: Optional[str] = None
        active: List[str] = []
        seen_any_label = False

        def flush() -> None:
            nonlocal active_name, active
            if active_name is not None:
                pipelines[active_name] = active
            active_name = None
            active = []

        for raw in lines:
            m = pipeline_re.match(raw.strip())
            if m:
                seen_any_label = True
                flush()
                active_name = m.group(1).lower()
                continue
            if active_name is not None:
                active.append(raw)

        flush()

        chosen_lines: List[str]
        if seen_any_label:
            # Prefer ispg/spjg; else relgo
            if "ispg" in pipelines:
                chosen_lines = pipelines["ispg"]
            elif "spjg" in pipelines:
                chosen_lines = pipelines["spjg"]
            elif "relgo" in pipelines:
                chosen_lines = pipelines["relgo"]
            else:
                chosen_lines = []
        else:
            chosen_lines = lines

        expected[q] = extract_steps_from_txt_lines(chosen_lines)

    return expected


def extract_steps_from_txt_lines(lines: List[str]) -> List[Step]:
    steps: List[Step] = []

    # varExpand(2, "(a:person)-[knows]->(b:person)", ...)
    var_re = re.compile(r"\.varExpand\([^,]+,\s*\"(?P<p>[^\"]+)\"", re.IGNORECASE)
    # expand_vec("(b:person)-[f:workAt]->(g:organisation)", ...)
    exp_re = re.compile(r"\.expand_vec\(\"(?P<p>[^\"]+)\"", re.IGNORECASE)
    into_re = re.compile(r"\.expandInto\(\"(?P<p>[^\"]+)\"", re.IGNORECASE)
    macro_ic5_re = re.compile(r"\.expand_IC5\(", re.IGNORECASE)

    for raw in lines:
        line = raw.strip()
        if macro_ic5_re.search(line):
            # txt uses a macro to represent a multi-step expansion in ic-5.
            # Treat it as a wildcard for the remaining traversal steps.
            steps.append(Step(op="macro", rel="expand_ic5", src="*", dst="*"))
            continue
        m = var_re.search(line)
        if m:
            s = parse_pattern_string(m.group("p"))
            if s:
                steps.append(Step(op="varexpand", rel=s[0], src=s[1], dst=s[2]))
            continue
        m = exp_re.search(line)
        if m:
            s = parse_pattern_string(m.group("p"))
            if s:
                steps.append(Step(op="expand", rel=s[0], src=s[1], dst=s[2]))
            continue
        m = into_re.search(line)
        if m:
            s = parse_pattern_string(m.group("p"))
            if s:
                steps.append(Step(op="expandinto", rel=s[0], src=s[1], dst=s[2]))
            continue

    return steps


def parse_pattern_string(p: str) -> Optional[Tuple[str, str, str]]:
    # Supports patterns like: (a:person)-[knows]->(b:person)
    # or: (b:person)-[f:workAt]->(g:organisation)
    # or: (b:message)-[e:beliked]->(a:person)
    m = re.search(
        r"\((?P<src>[A-Za-z_][\w]*)\s*:[^)]*\)\s*[-<]*\[\s*(?P<edge>[^\]]+)\s*\]\s*[-<]*>\s*\((?P<dst>[A-Za-z_][\w]*)\s*:[^)]*\)",
        p,
    )
    if not m:
        return None
    src = m.group("src")
    dst = m.group("dst")
    edge = m.group("edge")
    # edge may be "knows" or "f:workAt" or "e:beliked"
    if ":" in edge:
        rel = edge.split(":", 1)[1]
    else:
        rel = edge
    return norm_rel(rel), src, dst


def parse_actual_from_plan_text(plan_text: str) -> List[Step]:
    steps: List[Step] = []
    # Step N: op=EXPAND, ..., from=a, to=b, detail=MATCH::Person_knows_Person
    line_re = re.compile(
        r"^\s*Step\s+\d+:\s+op=(?P<op>EXPAND|VAREXPAND|IDENTITY),.*?(?:from=(?P<src>[^,]+),\s+to=(?P<dst>[^,]+),\s+)?detail=(?P<detail>.+)$"
    )

    for raw in plan_text.splitlines():
        m = line_re.match(raw)
        if not m:
            continue
        op = m.group("op")
        if op == "IDENTITY":
            continue
        detail = m.group("detail")
        src = (m.group("src") or "").strip() if m.group("src") else ""
        dst = (m.group("dst") or "").strip() if m.group("dst") else ""

        domain = "?"
        if "MATCH::" in detail:
            domain = "match"
        elif "SQL::" in detail:
            domain = "sql"

        if op == "VAREXPAND":
            # detail: MATCH::Person_knows_Person hops 1-2 contrib=...
            rel_label = detail.split("::", 1)[1].split(" hops", 1)[0].strip()
            rel = rel_from_relation_label(rel_label)
            steps.append(Step(op="varexpand", rel=rel, src=src or "?", dst=dst or "?", domain=domain))
        else:
            # detail: MATCH::Post_hasTag_Tag
            rel_label = detail.split("::", 1)[1].strip()
            rel = rel_from_relation_label(rel_label)
            steps.append(Step(op="expand", rel=rel, src=src or "?", dst=dst or "?", domain=domain))

    return steps


def step_sig_strict(s: Step) -> Tuple[str, str, str, str]:
    # For varExpand, plan render does not always include from/to; treat as wildcard.
    if s.op == "varexpand":
        return (s.op, s.rel, "*", "*")
    return (s.op, s.rel, s.src, s.dst)


def step_sig_loose(s: Step) -> Tuple[str, str]:
    # Loose mode is intended to validate overall traversal *order*.
    # Treat expandInto as equivalent to expand (same relation traversal, different physical join shape).
    op = "expand" if s.op == "expandinto" else s.op
    return (op, s.rel)


def is_auxiliary_step(s: Step) -> bool:
    # Heuristic: some SQL-side edges represent anti-join/side constraints not present in txt pipelines.
    # Keep this very conservative.
    return s.domain == "sql" and s.rel == "hastag"


def has_ic5_macro(steps: List[Step]) -> bool:
    return any(s.op == "macro" and s.rel == "expand_ic5" for s in steps)


def drop_macros(steps: List[Step]) -> List[Step]:
    return [s for s in steps if s.op != "macro"]


def prefix_match(expected: List[Step], actual: List[Step], strict: bool) -> bool:
    if strict:
        return [step_sig_strict(s) for s in expected] == [step_sig_strict(s) for s in actual[: len(expected)]]
    return [step_sig_loose(s) for s in expected] == [step_sig_loose(s) for s in actual[: len(expected)]]


def main() -> int:
    txt = TXT_PATH.read_text(encoding="utf-8")
    expected = parse_expected_from_txt(txt)

    all_ok = True
    for i in range(1, 13):
        q = f"ic-{i}"
        plan_path = PLAN_DIR / f"{q}_ispg.plan"
        if not plan_path.exists():
            print(f"[MISS] {q}: plan not found: {plan_path}")
            all_ok = False
            continue

        plan_text = plan_path.read_text(encoding="utf-8")
        actual_raw = parse_actual_from_plan_text(plan_text)
        actual_filtered = [s for s in actual_raw if not is_auxiliary_step(s)]
        expected_steps = expected.get(q, [])

        # Handle ic-5 macro: only require the prefix before the macro to match.
        if has_ic5_macro(expected_steps):
            expected_prefix = []
            for s in expected_steps:
                if s.op == "macro" and s.rel == "expand_ic5":
                    break
                expected_prefix.append(s)
            strict_ok = prefix_match(expected_prefix, actual_raw, strict=True) or prefix_match(
                expected_prefix, actual_filtered, strict=True
            )
            loose_ok = prefix_match(expected_prefix, actual_raw, strict=False) or prefix_match(
                expected_prefix, actual_filtered, strict=False
            )
            actual_steps = actual_raw
        else:
            # Try exact match first; if it fails, try again after dropping auxiliary SQL hasTag.
            strict_ok = [step_sig_strict(s) for s in actual_raw] == [step_sig_strict(s) for s in expected_steps]
            loose_ok = [step_sig_loose(s) for s in actual_raw] == [step_sig_loose(s) for s in expected_steps]

            if not (strict_ok or loose_ok):
                strict_ok = [step_sig_strict(s) for s in actual_filtered] == [step_sig_strict(s) for s in expected_steps]
                loose_ok = [step_sig_loose(s) for s in actual_filtered] == [step_sig_loose(s) for s in expected_steps]
                actual_steps = actual_filtered
            else:
                actual_steps = actual_raw
        ok = strict_ok or loose_ok
        if ok:
            mode = "strict" if strict_ok else "loose"
            print(f"[OK]   {q}: {len(actual_steps)} steps match ({mode})")
            continue

        all_ok = False
        print(f"[DIFF] {q}:")
        print(f"  expected({len(expected_steps)}): " + " | ".join(f"{s.op}:{s.src}->{s.dst}:{s.rel}" for s in expected_steps))
        print(f"  actual  ({len(actual_steps)}): " + " | ".join(f"{s.op}:{s.src}->{s.dst}:{s.rel}[{s.domain}]" for s in actual_steps))
        print(f"  loose_expected: " + " | ".join(f"{s.op}:{s.rel}" for s in expected_steps))
        print(f"  loose_actual:   " + " | ".join(f"{s.op}:{s.rel}[{s.domain}]" for s in actual_steps))

    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
